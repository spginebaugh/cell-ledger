"""Bounded topic-to-bundle workflow. No differential expression runs implicitly."""

from __future__ import annotations

import asyncio
import gzip
import io
import json
import re
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pandas as pd
from pydantic import BaseModel, Field

from cell_ledger.bulk import harmonize_rules, parse_matrix, qc_dataset, sample_eligibility
from cell_ledger.bundle import DESEQ_SCRIPT, assemble_dataset, write_json
from cell_ledger.geo.cache import CachedClient
from cell_ledger.geo.client import GeoSeriesHit
from cell_ledger.geo.models import GeoError
from cell_ledger.geo.retrieval import expression_sources, get_series_metadata, search_geo
from cell_ledger.interpretation import Interpreter, Ranking, SearchPlan


class RunRequest(BaseModel):
    topic: str = Field(min_length=3, max_length=2000)
    organism: str = "human"
    max_datasets: int = Field(default=3, ge=1, le=10)
    min_per_group: int = Field(default=3, ge=3, le=100)
    since: int | None = Field(default=None, ge=1900, le=2100)
    case: str | None = Field(default=None, max_length=200)
    control: str | None = Field(default=None, max_length=200)
    offline: bool = False
    ask_user: bool = False
    max_bytes: int = Field(default=500_000_000, ge=1000, le=500_000_000)


def scope_reason(request: RunRequest) -> str | None:
    if request.organism.casefold() not in {"human", "homo sapiens"}:
        return "Only human bulk RNA-seq is supported; choose a human GEO study."
    if re.search(
        r"\b(mouse|mice|murine|single[ -]cell|single[ -]nucleus|scrna|snrna|spatial|"
        r"microarray|atac|chip.seq|proteomics|fastq|bam|tcga|pseudobulk)\b",
        request.topic,
        re.I,
    ):
        return "This request is outside human bulk RNA-seq with precomputed GEO matrices."
    if request.case and request.control and request.case.casefold() == request.control.casefold():
        return "Case and control must be different labels."
    return None


async def run_pipeline(
    request: RunRequest,
    output: Path,
    client: CachedClient,
    *,
    emit: Callable[[str, str], None] | None = None,
    interpreter: Interpreter | None = None,
    ask: Callable[[str, list[str]], Awaitable[tuple[str, str] | None]] | None = None,
    candidate_pool: list[GeoSeriesHit] | None = None,
    snapshot_sha256: str | None = None,
    web_search: Callable[[str], Awaitable[list[GeoSeriesHit]]] | None = None,
) -> dict:
    if (candidate_pool is None) != (snapshot_sha256 is None):
        raise ValueError("Frozen evaluation needs both a candidate pool and its snapshot hash")
    if candidate_pool is not None and (not client.offline or len(candidate_pool) > 20):
        raise ValueError(
            "Frozen evaluation requires offline source access and at most 20 candidates"
        )
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    manifest = {
        "schema_version": 2,
        "request": request.model_dump(),
        "started_at": datetime.now(UTC).isoformat(),
        "queries": [],
        "datasets": [],
        "status": "running",
        "analysis_executed": False,
        "mode": "model_assisted" if interpreter else "deterministic",
        "model": interpreter.model if interpreter else None,
        "search_limit": 20,
        "clarifications": [],
        "ranking": [],
        "recommendations": [],
        "eval_protocol": "frozen_pool" if candidate_pool is not None else "live_search",
        "source_snapshot_sha256": snapshot_sha256,
    }
    questions: list[str] = []
    contrasts = []

    def event(stage: str, message: str):
        with (output / "audit.jsonl").open("a") as stream:
            stream.write(
                json.dumps(
                    {"time": datetime.now(UTC).isoformat(), "stage": stage, "message": message}
                )
                + "\n"
            )
        if emit:
            emit(stage, message)
        write_json(output / "manifest.json", manifest)

    reason = scope_reason(request)
    try:
        plan = SearchPlan(queries=[request.topic])
        if interpreter and not reason and candidate_pool is None:
            plan = await interpreter.extract(
                "Expand the topic into up to six GEO queries. Set scope_issue for non-human "
                "or non-bulk requests.",
                {"topic": request.topic},
                SearchPlan,
            )
            reason = plan.scope_issue
        if reason:
            questions.append(reason)
            manifest["status"] = "unsupported"
        else:
            manifest["queries"] = plan.queries
            event("search", "Searching human sequencing studies in GEO")
            found = {hit.gse: hit for hit in candidate_pool} if candidate_pool is not None else {}
            if candidate_pool is None:
                if web_search is not None and not request.offline and not client.offline:
                    for hit in await web_search(request.topic):
                        if request.since is None or (
                            hit.published is not None and hit.published.year >= request.since
                        ):
                            found.setdefault(hit.gse, hit)
                for query in plan.queries:
                    for hit in await search_geo(client, query, limit=20, since=request.since):
                        found.setdefault(hit.gse, hit)
            hits = list(found.values())[:20]
            manifest["discovered_count"] = len(found)
            ranking = {}
            if interpreter and hits:
                scored = await interpreter.extract(
                    "Score all candidates for topic relevance. Use only supplied GSE IDs. "
                    "Scores below 0.5 mean low relevance.",
                    {
                        "topic": request.topic,
                        "candidates": [hit.model_dump(mode="json") for hit in hits],
                    },
                    Ranking,
                )
                ranking = {score.gse: score for score in scored.candidates}
                if len(ranking) != len(scored.candidates) or set(ranking) != {
                    hit.gse for hit in hits
                }:
                    raise GeoError("Model ranking did not match retrieved accessions exactly")
                hits.sort(key=lambda hit: ranking[hit.gse].score, reverse=True)
            manifest["ranking"] = [hit.gse for hit in hits]
            if not hits:
                questions.append(
                    "No series found. Try broader topic synonyms or fewer constraints."
                )
            for index, hit in enumerate(hits):
                item = {"gse": hit.gse, "title": hit.title, "status": "pending", "reasons": []}
                manifest["datasets"].append(item)
                if hit.gse in ranking:
                    item["relevance"] = ranking[hit.gse].model_dump()
                    if ranking[hit.gse].score < 0.5:
                        item.update(status="excluded", reasons=["Low topic relevance"])
                        continue
                if index >= request.max_datasets:
                    item.update(status="not_inspected", reasons=["Maximum dataset limit reached"])
                    continue
                try:
                    async with asyncio.timeout(300):
                        event("fetch", f"Fetching source metadata for {hit.gse}")
                        series = await get_series_metadata(client, hit.gse)
                        labels = [
                            harmonize_rules(sample, case=request.case, control=request.control)
                            for sample in series.samples
                        ]
                        sources = await expression_sources(client, series)
                        if interpreter and not (request.case and request.control):
                            event("label", f"{hit.gse}: labeling eligible samples in small batches")
                            labels = await interpreter.label_samples(request.topic, series)
                        if not sources:
                            raise GeoError("No supported NCBI or submitter tabular matrix found")
                        eligible_ids = {
                            sample.gsm
                            for sample in series.samples
                            if not sample_eligibility(sample)
                        }
                        eligible_labels = [label for label in labels if label.gsm in eligible_ids]
                        if ask and any(label.group == "unknown" for label in eligible_labels):
                            options = sorted(
                                {
                                    label.value
                                    for sample in eligible_labels
                                    for field, label in sample.labels.items()
                                    if field in {"condition", "treatment"}
                                }
                            )
                            clarification = {
                                "gse": hit.gse,
                                "asked": True,
                                "question": "Which source labels identify case and control?",
                                "options": options,
                                "answer": None,
                            }
                            manifest["clarifications"].append(clarification)
                            event("question", f"{hit.gse}: {clarification['question']}")
                            decision = await ask(hit.gse, options)
                            if decision:
                                case, control = decision
                                if case not in options or control not in options or case == control:
                                    raise GeoError(
                                        "Case/control choices must be distinct source labels"
                                    )
                                labels = [
                                    harmonize_rules(sample, case=case, control=control)
                                    for sample in series.samples
                                ]
                                item["user_decision"] = {"case": case, "control": control}
                                clarification["answer"] = item["user_decision"]
                        source = sources[0]
                        event("download", f"{hit.gse}: {source['rule']}")
                        payload, provenance = await client.get(source["url"])
                        matrix = parse_matrix(payload, max_bytes=request.max_bytes)
                        embedded_annotation = matrix.attrs.pop("gene_annotation", None)
                        source_format = matrix.attrs.pop("source_format", "expression matrix")
                        matrix, validation = qc_dataset(
                            series,
                            matrix,
                            labels,
                            units=source["kind"],
                            min_per_group=request.min_per_group,
                        )
                        if matrix.empty:
                            raise GeoError("; ".join(validation.issues))
                        provenance.update(
                            {
                                "selection_rule": source["rule"],
                                "units_evidence": source.get("units_evidence"),
                                "source_format": source_format,
                                "metadata_url": series.source_url,
                                "qc": validation.model_dump(),
                                "caveats": [
                                    "NCBI-generated counts can differ from published counts; "
                                    "multiple sequencing runs per GSM may be summed."
                                ],
                            }
                        )
                        annotation = (
                            pd.DataFrame(embedded_annotation)
                            if embedded_annotation is not None
                            else None
                        )
                        if "annotation_url" in source:
                            try:
                                raw_annotation, annotation_provenance = await client.get(
                                    source["annotation_url"]
                                )
                                if raw_annotation.startswith(b"\x1f\x8b"):
                                    with gzip.GzipFile(
                                        fileobj=io.BytesIO(raw_annotation)
                                    ) as archive:
                                        raw_annotation = archive.read(request.max_bytes + 1)
                                if len(raw_annotation) > request.max_bytes:
                                    raise GeoError(
                                        "Expanded gene annotation exceeds the size limit"
                                    )
                                annotation = pd.read_csv(
                                    io.BytesIO(raw_annotation), sep="\t", dtype=str
                                )
                                provenance["gene_annotation"] = annotation_provenance
                            except (GeoError, ValueError, OSError) as exc:
                                annotation = None
                                note = f"Gene annotation unavailable: {exc}; original IDs preserved"
                                provenance["caveats"].append(note)
                                questions.append(f"{hit.gse}: {note}")
                        assemble_dataset(
                            output,
                            series,
                            matrix,
                            labels,
                            validation,
                            provenance,
                            annotation=annotation,
                        )
                        status = "de_ready" if validation.de_ready else "needs_review"
                        item.update(
                            status=status,
                            reasons=validation.issues,
                            samples=matrix.shape[1],
                            genes=matrix.shape[0],
                            units=validation.units,
                        )
                        manifest["recommendations"].append(hit.gse)
                        questions.extend(f"{hit.gse}: {issue}" for issue in validation.issues)
                        if validation.de_ready:
                            contrasts.append(
                                {
                                    "gse": hit.gse,
                                    "case": "case",
                                    "control": "control",
                                    "min_per_group": request.min_per_group,
                                }
                            )
                        event("verdict", f"{hit.gse}: {status}")
                except (GeoError, ValueError, TimeoutError, UnicodeError, httpx.HTTPError) as exc:
                    item.update(status="excluded", reasons=[str(exc)])
                    item["error_kind"] = (
                        "timeout"
                        if isinstance(exc, TimeoutError)
                        else "source_access"
                        if isinstance(exc, httpx.HTTPError)
                        or isinstance(exc.__cause__, httpx.HTTPError)
                        or "Offline cache miss" in str(exc)
                        or "browser challenge" in str(exc)
                        else "validation_or_processing"
                    )
                    questions.append(f"{hit.gse}: {exc}")
                    event("excluded", f"{hit.gse}: {exc}")
            manifest["status"] = "complete"
    except (GeoError, ValueError, httpx.HTTPError) as exc:
        manifest["status"] = "error"
        questions.append(str(exc))
    except BaseException:
        manifest["status"] = "error"
        questions.append("Run interrupted; no further datasets or contrasts were prepared.")
        raise
    finally:
        manifest["elapsed_seconds"] = round(time.monotonic() - started, 2)
        manifest["finished_at"] = datetime.now(UTC).isoformat()
        write_json(output / "manifest.json", manifest)
        write_json(output / "contrasts.json", contrasts)
        (output / "questions.md").write_text("\n".join(f"- {q}" for q in questions) + "\n")
        lines = ["# Dataset shortlist", "", "No analysis has been executed.", ""]
        for item in manifest["datasets"]:
            lines += [
                f"## {item['gse']} — {item['status']}",
                item["title"],
                *[f"- {reason}" for reason in item["reasons"]],
                "",
            ]
        (output / "shortlist.md").write_text("\n".join(lines))
        (output / "run_deseq.py").write_text(DESEQ_SCRIPT)
    return manifest
