"""Inspect exported artifacts without trusting success flags or executing generated code."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path
from typing import Literal

import anndata as ad
import numpy as np
import pandas as pd

from cell_ledger.bulk import LABEL_FIELDS
from evals.contracts import BundleObservation, Conditions, Evidence, RunRecord, SamplePrediction


def file_hash(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1 << 20):
            hasher.update(block)
    return hasher.hexdigest()


def safe_file(folder: Path, name: str) -> Path:
    path = folder / name
    if Path(name).is_absolute() or not path.resolve().is_relative_to(folder.resolve()):
        raise ValueError("Artifact path escapes its bundle")
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Missing or linked artifact: {name}")
    return path


def inspect_bundle(folder: Path) -> tuple[BundleObservation, list[SamplePrediction]]:
    gse = folder.name
    errors: list[str] = []
    predictions = []
    sample_ids: list[str] = []
    units = "unknown"
    de_ready = False
    try:
        study = json.loads(safe_file(folder, "study.json").read_text())
        if study.get("gse") != gse:
            errors.append("Study accession does not match bundle directory")
        units, de_ready = study["units"], study["de_ready"]
        with safe_file(folder, "samples.csv").open() as stream:
            rows = list(csv.DictReader(stream))
        sample_ids = [row["gsm"] for row in rows]
        if not rows or len(set(sample_ids)) != len(sample_ids):
            errors.append("Missing or duplicate sample identifiers")
        matrix_file = safe_file(folder, study["matrix_file"])
        delimiter = "\t"
        with matrix_file.open() as stream:
            header = next(csv.reader(stream, delimiter=delimiter))
        if header[1:] != sample_ids:
            errors.append("Raw matrix columns do not match sample sheet order exactly")
        matrix = pd.read_csv(matrix_file, sep=delimiter, index_col=0)
        matrix.index = matrix.index.astype(str)
        values = matrix.to_numpy(dtype=float)
        if matrix.empty or matrix.index.has_duplicates or not np.isfinite(values).all():
            errors.append("Empty, duplicate-gene, or non-finite matrix")
        if (values < 0).any() or (units == "counts" and not (values == np.floor(values)).all()):
            errors.append("Matrix values contradict declared units")
        if de_ready and units != "counts":
            errors.append("DE advertised for non-count values")
        genes = pd.read_csv(safe_file(folder, "genes.tsv"), sep="\t", dtype=str)
        if list(genes["gene_id"]) != list(matrix.index):
            errors.append("Gene annotation identifiers/order mismatch")
        dataset = ad.read_h5ad(safe_file(folder, "dataset.h5ad"))
        if list(dataset.obs_names) != sample_ids or list(dataset.var_names) != list(matrix.index):
            errors.append("AnnData sample/gene identities differ from TSV/CSV")
        to_array = getattr(dataset.X, "toarray", None)
        x = to_array() if callable(to_array) else dataset.X
        if not isinstance(x, np.ndarray):
            errors.append("AnnData expression matrix is missing or unsupported")
        elif not np.array_equal(x, matrix.T.to_numpy()):
            errors.append("AnnData values differ from the expression table")
        if dataset.uns.get("expression_units") != units:
            errors.append("AnnData expression units differ from study metadata")
        if "group" not in dataset.obs or dataset.obs["group"].astype(str).tolist() != [
            r["group"] for r in rows
        ]:
            errors.append("AnnData groups differ from sample sheet")
        for row in rows:
            labels = json.loads(row.get("evidence", "{}"))
            fields = {field: row.get(field) or None for field in LABEL_FIELDS | {"material_type"}}
            if fields.get("group") == "unknown":
                fields["group"] = None
            evidence = {
                field: Evidence(
                    gse=gse, gsm=row["gsm"], field=label["source_field"], quote=label["evidence"]
                )
                for field, label in labels.items()
            }
            predictions.append(
                SamplePrediction(gse=gse, gsm=row["gsm"], fields=fields, evidence=evidence)
            )
    except (OSError, ValueError, KeyError, TypeError, StopIteration) as exc:
        errors.append(f"Artifact inspection failed: {exc}")
    return BundleObservation(
        gse=gse,
        sample_ids=sample_ids,
        units=units,
        de_ready=de_ready,
        integrity_passed=not errors,
        integrity_errors=errors,
    ), predictions


def capture_run(
    root: Path, case_id: str, system: Literal["specialist", "baseline"], conditions: Conditions
) -> RunRecord:
    manifest_file = safe_file(root, "manifest.json")
    manifest = json.loads(manifest_file.read_text())
    if manifest.get("eval_protocol") != conditions.protocol:
        raise ValueError("Observed run protocol does not match the declared evaluation conditions")
    if conditions.protocol == "frozen_pool" and (
        manifest.get("source_snapshot_sha256") != conditions.snapshot_sha256
    ):
        raise ValueError("Frozen run did not record the declared source snapshot")
    bundles, samples = [], []
    for folder in sorted((root / "datasets").glob("GSE*")):
        if folder.is_dir() and re.fullmatch(r"GSE\d+", folder.name) and not folder.is_symlink():
            bundle, predictions = inspect_bundle(folder)
            bundles.append(bundle)
            samples.extend(predictions)
    clarifications = manifest.get("clarifications", [])
    asked = [item for item in clarifications if item.get("asked")]
    status = manifest["status"]
    source_failure = any(
        item.get("error_kind") in {"source_access", "timeout"}
        for item in manifest.get("datasets", [])
    )
    if asked:
        action = "ask"
    elif status == "unsupported":
        action = "decline"
    elif status == "error":
        action = "error"
    elif manifest.get("datasets"):
        action = "proceed" if bundles else "no_results"
    else:
        action = "no_results"
    # Old manifests have no reliable clarification trace. Never infer an ask from questions.md.
    if "clarifications" not in manifest:
        raise ValueError("Legacy manifest lacks clarification audit; rerun to score uncertainty")
    ranking = manifest.get("ranking", [item["gse"] for item in manifest["datasets"]])
    recommendations = manifest.get("recommendations", [bundle.gse for bundle in bundles])
    return RunRecord(
        case_id=case_id,
        system=system,
        conditions=conditions,
        run_status="complete"
        if status in {"complete", "unsupported"} and not source_failure
        else "error",
        action=action,
        ranking=ranking,
        recommendations=recommendations,
        questions=[str(item["question"]) for item in asked],
        # A human reviewer, not this adapter, assesses the question's actual specificity.
        samples=samples,
        bundles=bundles,
        elapsed_seconds=manifest.get("elapsed_seconds", 0),
        clarification_answers=sum(bool(item.get("answer")) for item in asked),
        raw_output_sha256=file_hash(manifest_file),
    )
