"""Preparation run control, storage mirroring, and downloadable output bundles."""

import asyncio
import csv
import io
import json
import re
import shutil
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse, Response
from pydantic import BaseModel

from cell_ledger.geo import GeoClient, GeoSeriesHit
from cell_ledger.geo.cache import CachedClient
from cell_ledger.interpretation import Interpreter
from cell_ledger.pipeline import RunRequest, run_pipeline
from cell_ledger_api.discovery import ExaSearcher, find_series_on_web
from cell_ledger_api.sessions import upload_dir
from cell_ledger_api.settings import Settings
from cell_ledger_api.storage import ObjectStore

router = APIRouter()
tasks: dict[str, asyncio.Task] = {}
answers: dict[str, asyncio.Future] = {}


class RunCreated(BaseModel):
    id: str


class SavedRun(BaseModel):
    id: str
    topic: str
    status: str
    started_at: str
    dataset_count: int


class SavedRunLibrary(BaseModel):
    enabled: bool
    runs: list[SavedRun]
    unreadable_count: int = 0


class RunSnapshot(BaseModel):
    id: str
    status: str
    manifest: dict
    events: list[dict]
    questions: str
    pending_question: dict | None = None


class GroupAnswer(BaseModel):
    case: str = ""
    control: str = ""
    skip: bool = False


def run_folder(run_id: str, cfg: Settings) -> Path:
    if not re.fullmatch(r"[0-9a-f]{32}", run_id):
        raise HTTPException(404, "Run not found")
    return cfg.data_dir / "runs" / run_id


def folder_for(run_id: str, cfg: Settings) -> Path:
    folder = run_folder(run_id, cfg)
    if not folder.exists() and run_id not in tasks:
        raise HTTPException(404, "Run not found")
    return folder


def request_store(request: Request) -> ObjectStore | None:
    sessions = getattr(request.app.state, "sessions", None)
    return sessions.store if sessions is not None else None


async def saved_run(request: Request, run_id: str) -> tuple[ObjectStore, str]:
    """The ZIP is written last, so incomplete uploads are not saved runs."""
    run_folder(run_id, request.app.state.settings)
    store = request_store(request)
    if store is None:
        raise HTTPException(404, "Run not found")
    try:
        url = await store.signed_url(f"runs/{run_id}/bundle.zip", 600)
    except Exception:
        raise HTTPException(503, "Saved run storage is temporarily unavailable") from None
    if url is None:
        raise HTTPException(404, "Saved run not found or upload was incomplete")
    return store, url


async def saved_file(store: ObjectStore, run_id: str, name: str) -> bytes | None:
    try:
        return await store.get(f"runs/{run_id}/{name}")
    except Exception:
        raise HTTPException(503, "Saved run storage is temporarily unavailable") from None


async def persist_outputs(folder: Path, store: ObjectStore) -> None:
    """Save individual outputs and a ZIP bundle before reporting completion."""
    prefix = f"runs/{folder.name}"
    await upload_dir(store, prefix, folder)
    archive = await asyncio.to_thread(shutil.make_archive, str(folder), "zip", folder)
    await store.put_file(f"{prefix}/bundle.zip", Path(archive), "application/zip")


async def execute(
    run_id: str,
    request: RunRequest,
    store: ObjectStore | None = None,
    *,
    cfg: Settings,
    exa: ExaSearcher | None = None,
    geo: GeoClient | None = None,
) -> None:
    folder = cfg.data_dir / "runs" / run_id

    def emit(stage: str, message: str):
        with (folder / "events.jsonl").open("a") as stream:
            stream.write(json.dumps({"id": uuid4().hex, "stage": stage, "message": message}) + "\n")

    async def ask(gse: str, options: list[str]) -> tuple[str, str] | None:
        question = folder / "pending_question.json"
        question.write_text(json.dumps({"gse": gse, "options": options}))
        future = asyncio.get_running_loop().create_future()
        answers[run_id] = future
        emit("question", f"{gse}: which source labels identify case and control?")
        try:
            return await future
        finally:
            answers.pop(run_id, None)
            question.unlink(missing_ok=True)

    client = CachedClient(
        cfg.data_dir / "geo/cache",
        offline=request.offline,
        max_bytes=request.max_bytes,
        api_key=cfg.ncbi_api_key.get_secret_value() if cfg.ncbi_api_key else None,
    )
    interpreter = None

    async def web_search(topic: str) -> list[GeoSeriesHit]:
        if exa is None or geo is None:
            return []
        emit("search", "Searching the web with Exa and verifying studies against GEO…")
        try:
            result = await asyncio.wait_for(
                find_series_on_web(
                    exa,
                    geo,
                    topic,
                    "Find human bulk RNA-seq GEO studies relevant to this research request: "
                    + topic
                    + ". Prefer GEO pages and paper data availability sections. "
                    "Exclude non-human, single-cell and microarray studies. "
                    "Extract GEO series accessions and their source URLs.",
                ),
                timeout=60,
            )
        except Exception:
            (folder / "exa_search.json").write_text(json.dumps({"status": "unavailable"}))
            emit(
                "search",
                "Exa search or GEO verification was unavailable; "
                "continuing with GEO keyword search.",
            )
            return []
        (folder / "exa_search.json").write_text(result.model_dump_json(indent=2))
        emit(
            "search",
            f"Exa found {len(result.verified)} GEO-verified studies; "
            "combining with GEO keyword search.",
        )
        return [item.hit for item in result.verified]

    model = cfg.model
    key = cfg.anthropic_api_key.get_secret_value() if cfg.anthropic_api_key else None
    if model and (key or request.offline):
        interpreter = Interpreter(
            model, key or "", cfg.data_dir / "interpretations", offline=request.offline
        )
    try:
        await run_pipeline(
            request,
            folder,
            client,
            emit=emit,
            interpreter=interpreter,
            ask=ask if request.ask_user else None,
            web_search=web_search if exa is not None and geo is not None else None,
        )
        if store is not None:
            emit("storage", "Saving preparation outputs to Supabase…")
            try:
                await persist_outputs(folder, store)
            except Exception:
                emit("storage", "Could not save outputs to Supabase. Local files are available.")
                (folder / "error.txt").write_text("Could not save outputs to Supabase.")
            else:
                emit("storage", "Preparation outputs and ZIP saved to Supabase.")
        else:
            emit("storage", "Supabase is not configured. Outputs are saved on local disk only.")
    except Exception:
        # Preserve source errors in the manifest; never expose provider credentials/tracebacks.
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "error.txt").write_text(
            "Run interrupted by an internal error. Check server logs."
        )
    finally:
        tasks.pop(run_id, None)


@router.post("/runs", response_model=RunCreated, status_code=202, operation_id="createRun")
async def create_run(request: RunRequest, http_request: Request) -> RunCreated:
    cfg = http_request.app.state.settings
    if len(tasks) >= 2:
        raise HTTPException(429, "Two runs are already active. Wait for one to finish.")
    key = cfg.anthropic_api_key.get_secret_value() if cfg.anthropic_api_key else ""
    if cfg.model and not key and not request.offline:
        raise HTTPException(503, "Model configured but ANTHROPIC_API_KEY is missing")
    run_id = uuid4().hex
    store = request_store(http_request)
    tasks[run_id] = asyncio.create_task(
        execute(
            run_id,
            request,
            store,
            cfg=cfg,
            exa=getattr(http_request.app.state, "exa", None),
            geo=getattr(http_request.app.state, "geo", None),
        )
    )
    return RunCreated(id=run_id)


@router.get("/runs", response_model=SavedRunLibrary, operation_id="listSavedRuns")
async def list_saved_runs(request: Request) -> SavedRunLibrary:
    store = request_store(request)
    if store is None:
        return SavedRunLibrary(enabled=False, runs=[])
    try:
        paths = await store.list_paths("runs")
        ids = sorted(
            {p.split("/")[1] for p in paths if re.fullmatch(r"runs/[0-9a-f]{32}/bundle\.zip", p)}
        )
        gate = asyncio.Semaphore(8)

        async def summary(run_id: str) -> SavedRun | None:
            async with gate:
                data = await store.get(f"runs/{run_id}/manifest.json")
            try:
                manifest = json.loads(data or b"null")
                return SavedRun(
                    id=run_id,
                    topic=manifest.get("request", {}).get("topic", "Untitled run"),
                    status=manifest.get("status", "error"),
                    started_at=manifest.get("started_at", ""),
                    dataset_count=sum(
                        d.get("samples") is not None for d in manifest.get("datasets", [])
                    ),
                )
            except (ValueError, TypeError, AttributeError):
                return None

        summaries = await asyncio.gather(*(summary(run_id) for run_id in ids))
    except Exception:
        raise HTTPException(503, "Saved run storage is temporarily unavailable") from None
    runs = sorted(
        (s for s in summaries if s is not None), key=lambda s: (s.started_at, s.id), reverse=True
    )
    return SavedRunLibrary(enabled=True, runs=runs, unreadable_count=len(ids) - len(runs))


@router.get("/runs/{run_id}", response_model=RunSnapshot, operation_id="getRun")
async def get_run(run_id: str, request: Request) -> RunSnapshot:
    folder = run_folder(run_id, request.app.state.settings)
    if not folder.exists() and run_id not in tasks:
        store, _ = await saved_run(request, run_id)
        manifest_bytes = await saved_file(store, run_id, "manifest.json")
        if manifest_bytes is None:
            raise HTTPException(404, "Saved run manifest is missing")
        try:
            manifest = json.loads(manifest_bytes)
            events_bytes = await saved_file(store, run_id, "events.jsonl")
            events = [json.loads(line) for line in (events_bytes or b"").splitlines()]
            questions = (await saved_file(store, run_id, "questions.md") or b"").decode()
            status = manifest.get("status", "error")
            if status == "running":
                status = "error"
            events.append(
                {
                    "id": "storage-restored",
                    "stage": "storage",
                    "message": "Loaded saved preparation outputs from Supabase.",
                }
            )
            return RunSnapshot(
                id=run_id, status=status, manifest=manifest, events=events, questions=questions
            )
        except (ValueError, TypeError, AttributeError):
            raise HTTPException(502, "Saved run metadata could not be read") from None
    manifest_file = folder / "manifest.json"
    manifest = json.loads(manifest_file.read_text()) if manifest_file.exists() else {}
    status = manifest.get("status", "running")
    if run_id in tasks:
        status = "running"
    if (folder / "error.txt").exists() or (status == "running" and run_id not in tasks):
        status = "error"
    events_file = folder / "events.jsonl"
    events = (
        [json.loads(line) for line in events_file.read_text().splitlines()]
        if events_file.exists()
        else []
    )
    questions_file = folder / "questions.md"
    questions = questions_file.read_text() if questions_file.exists() else ""
    question_file = folder / "pending_question.json"
    pending = json.loads(question_file.read_text()) if question_file.exists() else None
    return RunSnapshot(
        id=run_id,
        status=status,
        manifest=manifest,
        events=events,
        questions=questions,
        pending_question=pending if run_id in answers else None,
    )


@router.post("/runs/{run_id}/answer", operation_id="answerRun")
async def answer_run(run_id: str, answer: GroupAnswer, request: Request) -> dict:
    folder = folder_for(run_id, request.app.state.settings)
    future = answers.get(run_id)
    if future is None or future.done():
        raise HTTPException(409, "This run is not waiting for an answer")
    options = json.loads((folder / "pending_question.json").read_text())["options"]
    if not answer.skip and (
        answer.case not in options or answer.control not in options or answer.case == answer.control
    ):
        raise HTTPException(422, "Select two distinct labels from the source metadata")
    future.set_result(None if answer.skip else (answer.case, answer.control))
    return {"accepted": True}


@router.get("/runs/{run_id}/samples/{gse}", operation_id="getSamples")
async def get_samples(run_id: str, gse: str, request: Request) -> list[dict[str, str]]:
    folder = run_folder(run_id, request.app.state.settings)
    if not re.fullmatch(r"GSE\d+", gse):
        raise HTTPException(404, "Dataset not found")
    samples = folder / "datasets" / gse / "samples.csv"
    if not samples.exists():
        store, _ = await saved_run(request, run_id)
        content = await saved_file(store, run_id, f"datasets/{gse}/samples.csv")
        if content is None:
            raise HTTPException(404, "Sample sheet is not available")
        return list(csv.DictReader(io.StringIO(content.decode())))
    with samples.open() as stream:
        return list(csv.DictReader(stream))


@router.get("/runs/{run_id}/bundle", operation_id="downloadBundle")
async def download_bundle(run_id: str, request: Request) -> Response:
    folder = run_folder(run_id, request.app.state.settings)
    if run_id in tasks:
        raise HTTPException(409, "Run is still in progress")
    if not folder.exists():
        _, url = await saved_run(request, run_id)
        return RedirectResponse(url)
    archive = await asyncio.to_thread(shutil.make_archive, str(folder), "zip", folder)
    return FileResponse(archive, media_type="application/zip", filename=f"cell-ledger-{run_id}.zip")
