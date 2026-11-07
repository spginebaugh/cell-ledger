"""Read shared collection/analysis outputs without running or scientifically scoring them."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import anndata as ad
import numpy as np
import pandas as pd


@dataclass
class Inspection:
    """Observed facts; consistency is not scientific correctness or workflow success."""

    kind: str
    identity: dict[str, str] = field(default_factory=dict)
    source: dict[str, Any] = field(default_factory=dict)
    checks: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    unavailable: list[str] = field(default_factory=list)
    sha256: dict[str, str] = field(default_factory=dict)

    def result(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "consistent": False if self.errors else None if self.unavailable else True,
            "scientific_score": None,
        }


def _file(root: Path, name: str) -> Path:
    relative = Path(name)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"Unsafe artifact path: {name}")
    p = root
    for part in relative.parts:
        p = p / part
        if p.is_symlink():
            raise ValueError(f"Linked artifact path: {name}")
    if not p.is_file():
        raise ValueError(f"Missing artifact: {name}")
    return p


def _hash(path: Path, algorithm: str = "sha256") -> str:
    h = hashlib.new(algorithm)
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _record(result: Inspection, root: Path, name: str) -> Path:
    path = _file(root, name)
    result.sha256[name] = _hash(path)
    return path


def _object(path: Path, kind: str) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")
    _require(
        isinstance(value.get("gse"), str) and bool(re.fullmatch(r"GSE\d+", value["gse"])),
        "Missing or invalid study accession",
    )
    _require(isinstance(value.get("status"), str), "Missing reported status")
    _require(isinstance(value.get("files"), dict), "Missing artifact map")
    if kind == "collection":
        _require(
            isinstance(value.get("samples"), list)
            and all(isinstance(s, dict) for s in value["samples"]),
            "Invalid sample records",
        )
        _require(type(value.get("n_eligible")) is int, "Missing eligible-sample count")
        _require(all(isinstance(v, dict) for v in value["files"].values()), "Invalid file records")
    else:
        contrast = value.get("contrast")
        if not isinstance(contrast, dict) or not isinstance(contrast.get("name"), str):
            raise ValueError("Missing contrast identity")
        _require(contrast.get("gse") == value["gse"], "Report and contrast accession differ")
        _require(isinstance(value.get("figures", {}), dict), "Invalid figure map")
        _require(
            all(
                isinstance(v, str)
                for v in [*value["files"].values(), *value.get("figures", {}).values()]
            ),
            "Invalid artifact names",
        )
        for key in ("reconciliation", "filtering", "de"):
            _require(
                value.get(key) is None or isinstance(value[key], dict), f"Invalid {key} record"
            )
    return value


def _table(path: Path, delimiter: str = "\t") -> pd.DataFrame:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt") as stream:
        rows = list(csv.reader(stream, delimiter=delimiter))
    if len(rows) < 2 or len(rows[0]) < 2:
        raise ValueError(f"Empty or invalid table: {path.name}")
    if any(len(row) != len(rows[0]) for row in rows[1:]):
        raise ValueError(f"Ragged table: {path.name}")
    ids = [row[0] for row in rows[1:]]
    columns = rows[0][1:]
    if (
        not all(ids)
        or not all(columns)
        or len(set(ids)) != len(ids)
        or len(set(columns)) != len(columns)
    ):
        raise ValueError(f"Duplicate or blank table identifiers: {path.name}")
    return pd.DataFrame([row[1:] for row in rows[1:]], index=ids, columns=columns)


def _counts(path: Path, *, validate: bool = True) -> pd.DataFrame:
    table = pd.DataFrame(_table(path).apply(pd.to_numeric, errors="raise"))
    values = table.to_numpy()
    if validate and (
        not np.isfinite(values).all() or (values < 0).any() or (values != np.floor(values)).any()
    ):
        raise ValueError(f"Invalid raw count values: {path.name}")
    return table


def _check(result: Inspection, name: str, operation):
    try:
        value = operation()
        result.checks[name] = "passed"
        return value
    except (OSError, ValueError, KeyError, TypeError, IndexError, EOFError, AttributeError) as exc:
        result.checks[name] = "failed"
        result.errors.append(f"{name}: {exc}")
        return None


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def read_collection(folder: str | Path) -> Inspection:
    """Inspect one Mandee collection folder, including a legitimate excluded record."""
    root = Path(folder)
    result = Inspection("collection")
    doc = _check(
        result,
        "dataset_record",
        lambda: _object(_record(result, root, "dataset.json"), "collection"),
    )
    if doc is None:
        return result
    result.source = doc  # Keep exclusions, provenance and reported status verbatim.
    result.identity = {"gse": str(doc.get("gse", ""))}

    def identifiers():
        _require(doc["gse"] == root.name, "Folder and record accession differ")
        ids = [s["gsm"] for s in doc["samples"]]
        _require(len(ids) == len(set(ids)), "Duplicate sample records")
        _require(
            doc["n_eligible"] == sum(not s["exclusions"] for s in doc["samples"]),
            "Eligible count disagrees with recorded exclusions",
        )

    _check(result, "sample_records", identifiers)
    paths: dict[str, Path] = {}
    for role, record in doc.get("files", {}).items():

        def verify(record=record):
            p = _record(result, root, record["name"])
            _require(p.stat().st_size == record["bytes"], "Recorded byte size differs")
            _require(_hash(p, "md5") == record["md5"], "Recorded MD5 differs")
            return p

        path = _check(result, f"file:{role}", verify)
        if path is not None:
            paths[role] = path
    if "counts" not in paths:
        result.unavailable.append(
            "Raw counts inspection unavailable; see recorded exclusions/errors"
        )
    else:
        counts = _check(result, "raw_counts", lambda: _counts(paths["counts"], validate=False))
        if counts is not None:

            def coverage():
                samples = doc["samples"]
                ids = {s["gsm"] for s in samples}
                check = doc["counts_check"]
                _require(check["n_genes"] == len(counts), "Reported gene count differs")
                _require(check["n_columns"] == len(counts.columns), "Reported column count differs")
                _require(
                    check["all_nonneg_integers"]
                    == bool(
                        np.isfinite(counts.to_numpy()).all()
                        and (counts.to_numpy() >= 0).all()
                        and (counts.to_numpy() == np.floor(counts.to_numpy())).all()
                    ),
                    "Reported count validation differs",
                )
                _require(
                    check["columns_not_in_soft"] == [g for g in counts.columns if g not in ids],
                    "Unknown-column report differs",
                )
                for sample in samples:
                    _require(
                        sample["in_counts"] == (sample["gsm"] in counts.columns),
                        f"Count coverage differs for {sample['gsm']}",
                    )
                    _require(
                        ("not_in_counts" in sample["exclusions"]) == (not sample["in_counts"]),
                        f"Count-coverage exclusion differs for {sample['gsm']}",
                    )

            _check(result, "count_coverage", coverage)
    if "soft" not in paths:
        result.unavailable.append("Source metadata inspection unavailable")
    else:

        def metadata():
            records: dict[str, dict[str, list[str]]] = {}
            current = None
            series_ids = []
            with gzip.open(paths["soft"], "rt") as stream:
                for line in stream:
                    line = line.rstrip("\r\n")
                    if line.startswith("^SAMPLE = "):
                        gsm = line.split(" = ", 1)[1]
                        _require(gsm not in records, "Duplicate SOFT sample")
                        current = records[gsm] = {}
                    elif line.startswith("^"):
                        current = None
                        if line.startswith("^SERIES = "):
                            series_ids.append(line.split(" = ", 1)[1])
                    elif current is not None and line.startswith("!Sample_") and " = " in line:
                        key, value = line.removeprefix("!Sample_").split(" = ", 1)
                        current.setdefault(key, []).append(value)
            _require(series_ids == [doc["gse"]], "SOFT series accession differs")
            _require(set(records) == {s["gsm"] for s in doc["samples"]}, "SOFT sample set differs")
            for sample in doc["samples"]:
                raw = records[sample["gsm"]]
                for output, source in [
                    ("title", "title"),
                    ("source_name", "source_name_ch1"),
                    ("organism", "organism_ch1"),
                    ("library_strategy", "library_strategy"),
                ]:
                    _require(
                        sample[output] == raw.get(source, [""])[-1],
                        f"SOFT {output} differs for {sample['gsm']}",
                    )
                _require(
                    sample["characteristics"] == raw.get("characteristics_ch1", []),
                    f"SOFT characteristics differ for {sample['gsm']}",
                )

        _check(result, "source_metadata", metadata)
    return result


def read_analysis(folder: str | Path, *, source_counts: str | Path | None = None) -> Inspection:
    """Inspect one Scott analysis folder. Each contrast remains a separate observation."""
    root = Path(folder)
    result = Inspection("analysis")
    doc = _check(
        result, "analysis_report", lambda: _object(_record(result, root, "report.json"), "analysis")
    )
    if doc is None:
        return result
    result.source = doc  # External report is canonical; never reconstruct scientific judgments.
    result.identity = {
        "gse": str(doc.get("gse", "")),
        "contrast": str(doc.get("contrast", {}).get("name", "")),
    }
    paths: dict[str, Path] = {}
    for role, name in {**doc.get("files", {}), **doc.get("figures", {})}.items():
        p = _check(result, f"file:{role}", lambda name=name: _record(result, root, name))
        if p is not None:
            paths[role] = p
    counts = (
        _check(result, "exported_counts", lambda: _counts(paths["counts"]))
        if "counts" in paths
        else None
    )
    samples = (
        _check(result, "sample_table", lambda: _table(paths["samples"], ","))
        if "samples" in paths
        else None
    )
    dataset = (
        _check(result, "anndata", lambda: ad.read_h5ad(paths["anndata"]))
        if "anndata" in paths
        else None
    )
    for role in ("counts", "samples", "anndata"):
        if role not in paths:
            result.unavailable.append(f"{role} unavailable; reported status/error preserved")
    if counts is not None and samples is not None:

        def selection():
            rec = doc["reconciliation"]
            _require(
                list(counts.columns) == list(samples.index) == rec["gsms_used"],
                "Counts, samples and reconciliation identities/order differ",
            )
            _require(len(counts) == rec["n_genes"], "Reconciliation gene count differs")
            contrast = doc["contrast"]
            for gsm, arm in samples["arm"].items():
                expected = (
                    "case"
                    if gsm in contrast["case_gsms"]
                    else "control"
                    if gsm in contrast["control_gsms"]
                    else None
                )
                _require(bool(arm == expected), f"Contrast arm differs for {gsm}")
            _require(
                sum(samples["arm"] == "case") == rec["n_case"]
                and sum(samples["arm"] == "control") == rec["n_control"],
                "Reported arm counts differ",
            )

        _check(result, "selection", selection)
    if counts is not None and dataset is not None:

        def matrix():
            genes, gsms = list(dataset.var_names), list(dataset.obs_names)
            _require(
                len(set(genes)) == len(genes) and len(set(gsms)) == len(gsms),
                "Duplicate AnnData identities",
            )
            _require(
                set(genes) <= set(counts.index) and set(gsms) <= set(counts.columns),
                "AnnData has unknown identities",
            )
            dropped = (
                doc.get("de", {}).get("summary", {}).get("dropped_unpaired", [])
                if doc.get("de")
                else []
            )
            _require(
                len(set(dropped)) == len(dropped) and set(dropped) <= set(counts.columns),
                "Invalid dropped-sample identities",
            )
            _require(
                gsms == [g for g in counts.columns if g not in dropped],
                "Unaccounted sample removal/order change",
            )
            filtering = doc.get("filtering")
            _require(
                len(genes) == (filtering["n_genes_after"] if filtering else len(counts)),
                "Unaccounted gene removal",
            )
            layer = dataset.layers["counts"]
            toarray = getattr(layer, "toarray", None)
            array = np.asarray(toarray() if callable(toarray) else layer)
            _require(
                np.array_equal(array, counts.loc[genes, gsms].T.to_numpy()),
                "AnnData raw counts differ from exported subset",
            )
            _require(str(dataset.uns["gse"]) == doc["gse"], "AnnData accession differs")
            _require(
                json.loads(str(dataset.uns["contrast"])) == doc["contrast"],
                "AnnData contrast differs",
            )
            if samples is not None:
                for col in ("group", "arm"):
                    _require(
                        dataset.obs[col].astype(str).tolist() == samples.loc[gsms, col].tolist(),
                        f"AnnData {col} differs",
                    )

        _check(result, "anndata_subset", matrix)
    if source_counts is None:
        result.unavailable.append(
            "Original source counts not supplied; source-to-export equality unchecked"
        )
    elif counts is not None:

        def original():
            path = Path(source_counts)
            _require(not path.is_symlink(), "Source counts must not be a symlink")
            result.sha256["source_counts"] = _hash(path)
            source = _counts(path)
            _require(list(source.index) == list(counts.index), "Exported source genes/order differ")
            _require(
                np.array_equal(
                    source.loc[counts.index, counts.columns].to_numpy(), counts.to_numpy()
                ),
                "Exported values differ from original counts",
            )

        _check(result, "source_counts", original)
    if dataset is not None and "de_results" in paths:

        def de_results():
            table = _table(paths["de_results"])
            _require(
                set(table.index) == set(dataset.var_names),
                "DE result gene identities differ",
            )

        _check(result, "de_result_ids", de_results)
    summary = doc.get("de", {}).get("summary", {}) if doc.get("de") else {}
    collapsed = summary.get("collapsed", {})
    units: dict[str, list[str]] | None = None
    if collapsed and dataset is not None and samples is not None:

        def combined_observations():
            _require(isinstance(collapsed, dict), "Invalid combined-observation mapping")
            fitted = list(dataset.obs_names)
            _require(summary["gsms_fitted"] == fitted, "Fitted sample identities/order differ")
            _require(
                json.loads(str(dataset.uns["collapsed"])) == collapsed,
                "Report and AnnData combined-observation mappings differ",
            )
            seen: set[str] = set()
            blocking = summary["blocking"]
            _require(isinstance(blocking, str) and blocking in samples, "Missing blocking labels")
            for unit, members in collapsed.items():
                _require(
                    isinstance(unit, str) and bool(unit) and unit not in fitted,
                    "Combined observation collides with sample identity",
                )
                _require(
                    isinstance(members, list)
                    and len(members) >= 2
                    and all(isinstance(g, str) for g in members),
                    "Invalid combined members",
                )
                _require(
                    len(set(members)) == len(members) and not (seen & set(members)),
                    "Duplicate sample membership in combined observations",
                )
                _require(set(members) <= set(fitted), "Unknown or dropped combined sample")
                rows = samples.loc[members]
                _require(len(set(rows["arm"])) == 1, "Combined observation mixes arms")
                blocks = set(rows[blocking])
                _require(
                    len(blocks) == 1 and bool(next(iter(blocks))),
                    "Combined observation mixes or lacks blocking labels",
                )
                seen.update(members)
            _require(
                summary["n_samples_collapsed"] == len(seen),
                "Reported combined-sample count differs",
            )
            mapping = {g: [g] for g in fitted if g not in seen}
            mapping.update(collapsed)
            arms = [samples.loc[members[0], "arm"] for members in mapping.values()]
            _require(
                arms.count("case") == summary["n_case_used"]
                and arms.count("control") == summary["n_control_used"],
                "Reported fitted-observation arm counts differ",
            )
            return mapping

        units = _check(result, "combined_observations", combined_observations)
    elif collapsed:
        result.unavailable.append(
            "Combined membership cannot be checked without AnnData and samples"
        )
    if collapsed:
        result.unavailable.append(
            "Combined normalized values and pre-fit sums have no independent fitted matrix "
            "in these artifacts; membership and value validity do not verify "
            "normalization or fitting"
        )
    if dataset is not None and "normalized_counts" in paths:

        def normalized():
            table = _table(paths["normalized_counts"]).astype(float)
            values = table.to_numpy()
            _require(
                bool(np.isfinite(values).all() and (values >= 0).all()),
                "Normalized counts contain non-finite or negative values",
            )
            _require(
                list(table.index) == list(dataset.var_names),
                "Normalized gene identities/order differ",
            )
            if collapsed:
                _require(units is not None, "Combined observation membership not verified")
                _require(
                    set(table.columns) == set(units or {}),
                    "Normalized combined-observation identities differ",
                )
                return
            _require(
                list(table.columns) == list(dataset.obs_names), "Normalized table identities differ"
            )
            layer = np.asarray(dataset.layers["normed_counts"])
            _require(
                np.allclose(table.T.to_numpy(), layer, rtol=0, atol=0.0005001),
                "Normalized counts differ beyond export rounding",
            )

        _check(result, "normalized_counts", normalized)
    if doc.get("de"):
        for role in ("de_results", "normalized_counts"):
            if role not in paths:
                result.unavailable.append(f"Reported DE has no readable {role} artifact")
    result.unavailable.append(
        "Field-specific evidence attribution is not recoverable from flattened samples.csv"
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=("collection", "analysis"))
    parser.add_argument("folder", type=Path)
    parser.add_argument("--source-counts", type=Path)
    args = parser.parse_args()
    if args.kind == "collection" and args.source_counts:
        parser.error("--source-counts applies only to analysis")
    result = (
        read_collection(args.folder)
        if args.kind == "collection"
        else read_analysis(args.folder, source_counts=args.source_counts)
    )
    print(json.dumps(result.result(), indent=2))
    raise SystemExit(1 if result.errors else 0)


if __name__ == "__main__":
    main()
