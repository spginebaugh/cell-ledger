import asyncio
import io
import zipfile

import httpx

from cell_ledger_api.main import create_app
from cell_ledger_api.routes import topic_runs as runs
from cell_ledger_api.settings import settings


async def test_run_refusal_survives_reload_and_download(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.delenv("CELL_LEDGER_MODEL", raising=False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()), base_url="http://test"
    ) as client:
        response = await client.post("/api/runs", json={"topic": "mouse single-cell"})
        assert response.status_code == 202
        run_id = response.json()["id"]
        task = runs.tasks.get(run_id)
        if task:
            await task
        snapshot = (await client.get(f"/api/runs/{run_id}")).json()
        assert snapshot["status"] == "unsupported"
        assert "outside" in snapshot["questions"]
        bundle = await client.get(f"/api/runs/{run_id}/bundle")
        assert bundle.status_code == 200
        with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
            assert "manifest.json" in archive.namelist()
            assert "run_deseq.py" in archive.namelist()
        assert (await client.get("/api/runs/not-a-run")).status_code == 404


async def test_concurrent_run_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    blocker = asyncio.Event()
    tasks = [asyncio.create_task(blocker.wait()) for _ in range(2)]
    runs.tasks.update({"one": tasks[0], "two": tasks[1]})
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app()), base_url="http://test"
        ) as client:
            assert (await client.post("/api/runs", json={"topic": "human"})).status_code == 429
    finally:
        blocker.set()
        await asyncio.gather(*tasks)
        runs.tasks.clear()


async def test_question_answer_resumes_active_run(tmp_path, monkeypatch):
    import json

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "model", None)

    async def pipeline(request, folder, client, *, emit, interpreter, ask, web_search=None):
        folder.mkdir(parents=True)
        (folder / "manifest.json").write_text(json.dumps({"status": "running"}))
        assert ask is not None
        decision = await ask("GSE1", ["treated", "mock"])
        assert decision == ("treated", "mock")
        (folder / "manifest.json").write_text(json.dumps({"status": "complete"}))

    monkeypatch.setattr(runs, "run_pipeline", pipeline)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()), base_url="http://test"
    ) as client:
        response = await client.post("/api/runs", json={"topic": "human IFNG", "ask_user": True})
        run_id = response.json()["id"]
        task = runs.tasks[run_id]
        await asyncio.sleep(0)
        snapshot = (await client.get(f"/api/runs/{run_id}")).json()
        assert snapshot["pending_question"]["options"] == ["treated", "mock"]
        invalid = await client.post(
            f"/api/runs/{run_id}/answer", json={"case": "invented", "control": "mock"}
        )
        assert invalid.status_code == 422
        valid = await client.post(
            f"/api/runs/{run_id}/answer", json={"case": "treated", "control": "mock"}
        )
        assert valid.status_code == 200
        await task
        assert (await client.get(f"/api/runs/{run_id}")).json()["status"] == "complete"
        assert not (tmp_path / "runs" / run_id / "pending_question.json").exists()


async def test_preparation_mirrors_nested_outputs_and_waits_for_storage(tmp_path, monkeypatch):
    import json

    from cell_ledger_api.storage import MemoryStore

    entered = asyncio.Event()
    release = asyncio.Event()

    class PausedStore(MemoryStore):
        async def put_file(self, path, file, content_type):
            entered.set()
            await release.wait()
            await super().put_file(path, file, content_type)

    store = PausedStore()
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "model", None)

    async def pipeline(request, folder, client, **kwargs):
        folder.mkdir(parents=True)
        (folder / "manifest.json").write_text(json.dumps({"status": "complete"}))
        dataset = folder / "datasets" / "GSE1"
        dataset.mkdir(parents=True)
        (dataset / "counts.csv").write_text("gene,sample\nA,42\n")

    monkeypatch.setattr(runs, "run_pipeline", pipeline)
    app = create_app(store=store)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        response = await client.post("/api/runs", json={"topic": "synthetic human"})
        run_id = response.json()["id"]
        task = runs.tasks[run_id]
        try:
            await asyncio.wait_for(entered.wait(), 5)
            snapshot = (await client.get(f"/api/runs/{run_id}")).json()
            assert snapshot["status"] == "running"
            assert (await client.get(f"/api/runs/{run_id}/bundle")).status_code == 409
        finally:
            release.set()
            await task
        snapshot = (await client.get(f"/api/runs/{run_id}")).json()
        assert snapshot["status"] == "complete"
        assert "saved to Supabase" in snapshot["events"][-1]["message"]
        prefix = f"runs/{run_id}"
        assert store.objects[f"{prefix}/datasets/GSE1/counts.csv"] == b"gene,sample\nA,42\n"
        with zipfile.ZipFile(io.BytesIO(store.objects[f"{prefix}/bundle.zip"])) as archive:
            assert archive.read("datasets/GSE1/counts.csv") == b"gene,sample\nA,42\n"
            assert json.loads(archive.read("manifest.json"))["status"] == "complete"


async def test_storage_failure_is_visible_and_local_bundle_survives(tmp_path, monkeypatch):
    from cell_ledger_api.storage import MemoryStore

    class BrokenStore(MemoryStore):
        async def put_file(self, path, file, content_type):
            raise RuntimeError("private provider error")

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "model", None)
    app = create_app(store=BrokenStore())
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        response = await client.post("/api/runs", json={"topic": "mouse single-cell"})
        run_id = response.json()["id"]
        await runs.tasks[run_id]
        snapshot = await client.get(f"/api/runs/{run_id}")
        assert snapshot.json()["status"] == "error"
        assert "Could not save outputs to Supabase" in snapshot.text
        assert "private provider error" not in snapshot.text
        assert (await client.get(f"/api/runs/{run_id}/bundle")).status_code == 200


async def test_saved_run_survives_missing_local_files(tmp_path, monkeypatch):
    import json
    import shutil

    from cell_ledger_api.storage import MemoryStore

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    store = MemoryStore()
    run_id = "a" * 32
    folder = tmp_path / "runs" / run_id
    dataset = folder / "datasets" / "GSE1"
    dataset.mkdir(parents=True)
    (folder / "manifest.json").write_text(json.dumps({"status": "complete", "datasets": []}))
    (folder / "questions.md").write_text("Review these source labels.")
    (dataset / "samples.csv").write_text("sample,group\nGSM1,case\n")
    await runs.persist_outputs(folder, store)
    shutil.rmtree(folder)
    folder.with_suffix(".zip").unlink()
    app = create_app(store=store)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        snapshot = (await client.get(f"/api/runs/{run_id}")).json()
        assert snapshot["status"] == "complete"
        assert snapshot["questions"] == "Review these source labels."
        assert snapshot["pending_question"] is None
        assert "Loaded saved" in snapshot["events"][-1]["message"]
        samples = await client.get(f"/api/runs/{run_id}/samples/GSE1")
        assert samples.json() == [{"sample": "GSM1", "group": "case"}]
        assert (await client.get(f"/api/runs/{run_id}/samples/GSE2")).status_code == 404
        bundle = await client.get(f"/api/runs/{run_id}/bundle")
        assert bundle.status_code == 307
        assert bundle.headers["location"] == f"memory://runs/{run_id}/bundle.zip?expires_in=600"
        assert not folder.exists()  # no full dataset download needed to view metadata
        assert (await client.get("/api/runs/not-a-run")).status_code == 404
        assert (await client.get(f"/api/runs/{'b' * 32}")).status_code == 404
        del store.objects[f"runs/{run_id}/bundle.zip"]
        assert (await client.get(f"/api/runs/{run_id}")).status_code == 404
        assert (await client.get(f"/api/runs/{run_id}/bundle")).status_code == 404


async def test_saved_run_storage_outage_is_retryable(tmp_path, monkeypatch):
    from cell_ledger_api.storage import MemoryStore

    class UnavailableStore(MemoryStore):
        async def signed_url(self, path, expires_in):
            raise RuntimeError("private provider details")

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    app = create_app(store=UnavailableStore())
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        for suffix in ("", "/samples/GSE1", "/bundle"):
            response = await client.get(f"/api/runs/{'a' * 32}{suffix}")
            assert response.status_code == 503
            assert "private provider" not in response.text


async def test_saved_library_discovers_only_finished_remote_runs(tmp_path, monkeypatch):
    import json

    from cell_ledger_api.storage import MemoryStore

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    store = MemoryStore()
    for number, date in [(1, "2026-11-01"), (2, "2026-11-07"), (3, "2026-11-08")]:
        run_id = str(number) * 32
        await store.put(
            f"runs/{run_id}/manifest.json",
            json.dumps(
                {
                    "request": {"topic": f"Topic {number}"},
                    "status": "complete",
                    "started_at": date,
                    "datasets": [{"samples": 20}, {"status": "excluded"}],
                }
            ).encode(),
            "application/json",
        )
        if number != 3:  # a partial upload must not appear
            await store.put(f"runs/{run_id}/bundle.zip", b"zip", "application/zip")
    await store.put(f"runs/{'4' * 32}/bundle.zip", b"zip", "application/zip")
    app = create_app(store=store)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        response = await client.get("/api/runs")
        assert response.status_code == 200
        body = response.json()
        assert body["enabled"] is True
        assert [r["id"] for r in body["runs"]] == ["2" * 32, "1" * 32]
        assert body["runs"][0]["dataset_count"] == 1
        assert body["unreadable_count"] == 1
        assert not (tmp_path / "runs").exists()
        store.objects.clear()
        assert (await client.get("/api/runs")).json()["runs"] == []


async def test_saved_library_unconfigured_and_unavailable():
    from cell_ledger_api.storage import MemoryStore

    class UnavailableStore(MemoryStore):
        async def list_paths(self, prefix):
            raise RuntimeError("private details")

    app = create_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        assert (await c.get("/api/runs")).json() == {
            "enabled": False,
            "runs": [],
            "unreadable_count": 0,
        }
    app = create_app(store=UnavailableStore())
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c,
    ):
        response = await c.get("/api/runs")
        assert response.status_code == 503
        assert "private details" not in response.text


async def test_main_form_run_uses_exa_and_reports_fallback(tmp_path, monkeypatch):
    import json

    from cell_ledger_api.discovery import WebSearchResult

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "model", None)
    exa, geo = object(), object()
    calls = []

    async def discover(actual_exa, actual_geo, topic, objective):
        assert actual_exa is exa and actual_geo is geo
        calls.append(topic)
        if topic == "provider outage":
            raise RuntimeError("sensitive provider detail")
        return WebSearchResult(
            query=topic, objective=objective, nominated=[], verified=[], rejected=[]
        )

    async def pipeline(request, folder, client, *, web_search, **kwargs):
        folder.mkdir(parents=True)
        assert await web_search(request.topic) == []
        (folder / "manifest.json").write_text(json.dumps({"status": "complete"}))

    monkeypatch.setattr(runs, "find_series_on_web", discover)
    monkeypatch.setattr(runs, "run_pipeline", pipeline)
    app = create_app()
    app.state.exa, app.state.geo = exa, geo
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        for topic in ("human IFNG", "provider outage"):
            response = await client.post("/api/runs", json={"topic": topic})
            assert response.status_code == 202
            run_id = response.json()["id"]
            await runs.tasks[run_id]
            snapshot = (await client.get(f"/api/runs/{run_id}")).json()
            assert snapshot["status"] == "complete"
            messages = str(snapshot["events"])
            assert "sensitive provider detail" not in messages
            assert ("Exa found 0" if topic == "human IFNG" else "unavailable") in messages
            assert (tmp_path / "runs" / run_id / "exa_search.json").is_file()
    assert calls == ["human IFNG", "provider outage"]


async def test_custom_app_settings_control_run_paths_and_model(tmp_path, monkeypatch):
    import json

    from cell_ledger_api.settings import Settings

    cfg = Settings.model_construct(data_dir=tmp_path / "custom", model="configured-model")
    cfg.anthropic_api_key = None
    cfg.ncbi_api_key = None
    monkeypatch.setattr(settings, "data_dir", tmp_path / "wrong")
    observed = {}

    async def pipeline(request, folder, client, **kwargs):
        observed.update(folder=folder, cache=client.directory, interpreter=kwargs["interpreter"])
        folder.mkdir(parents=True)
        (folder / "manifest.json").write_text(json.dumps({"status": "complete"}))
        (folder / "questions.md").write_text("")
        dataset = folder / "datasets/GSE1"
        dataset.mkdir(parents=True)
        (dataset / "samples.csv").write_text("gsm,group\nGSM1,case\n")

    monkeypatch.setattr(runs, "run_pipeline", pipeline)
    app = create_app(cfg)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        rejected = await client.post("/api/runs", json={"topic": "human study"})
        assert rejected.status_code == 503  # The supplied model setting is honored.
        response = await client.post("/api/runs", json={"topic": "human study", "offline": True})
        run_id = response.json()["id"]
        await runs.tasks[run_id]
        assert observed["folder"] == cfg.data_dir / "runs" / run_id
        assert observed["cache"] == cfg.data_dir / "geo/cache"
        assert observed["interpreter"].model == "configured-model"
        assert (await client.get(f"/api/runs/{run_id}")).json()["status"] == "complete"
        assert (await client.get(f"/api/runs/{run_id}/samples/GSE1")).json()[0]["gsm"] == "GSM1"
        assert (await client.get(f"/api/runs/{run_id}/bundle")).status_code == 200
        assert (
            await client.post(f"/api/runs/{run_id}/answer", json={"skip": True})
        ).status_code == 409
        assert not (tmp_path / "wrong").exists()
