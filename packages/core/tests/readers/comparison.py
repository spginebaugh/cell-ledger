"""Inspect cross-study artifacts independently of product validators or scientific policy."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np
import pandas as pd

from packages.core.tests.readers.analysis import Inspection, _check, _record, _table


def _require(condition: object, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open() as stream:
        return list(csv.DictReader(stream, delimiter="\t"))


def _boolean(value: str) -> bool:
    _require(value in {"True", "False"}, "Invalid boolean in exported table")
    return value == "True"


def read_comparison(
    folder: str | Path, *, source_runs: dict[str, Path] | None = None
) -> Inspection:
    """Never follow report.run_dir automatically; source paths must be supplied explicitly."""
    root = Path(folder)
    result = Inspection("comparison")

    def report():
        value = json.loads(_record(result, root, "comparison.json").read_text())
        _require(isinstance(value, dict), "Expected a comparison report object")
        _require(
            value.get("status") in {"complete", "insufficient", "failed"},
            "Unknown comparison status",
        )
        for key in ("members", "excluded", "warnings", "questions", "sensitivity", "leave_one_out"):
            _require(isinstance(value.get(key), list), f"Invalid {key} list")
        _require(isinstance(value.get("files"), dict), "Invalid artifact map")
        _require(isinstance(value.get("figures", {}), dict), "Invalid figure map")
        _require(isinstance(value.get("strata", {}), dict), "Invalid strata map")
        return value

    doc = _check(result, "comparison_report", report)
    if doc is None:
        return result
    result.source = doc
    result.identity = {"name": str(doc.get("name", ""))}
    paths = {}
    for kind in ("files", "figures"):
        for role, name in doc.get(kind, {}).items():
            path = _check(result, f"{kind}:{role}", lambda name=name: _record(result, root, name))
            if path is not None and kind == "files":
                paths[role] = path
    members = {}
    pooled = []

    def ledger():
        for member in doc["members"]:
            label = member["label"]
            _require(label == f"{member['gse']}:{member['contrast']}", "Member identity differs")
            _require(label not in members, "Duplicate member identity")
            _require(type(member["pooled"]) is bool, "Invalid pooled membership")
            members[label] = member
            if member["pooled"]:
                pooled.append(label)
        if doc["status"] == "complete":
            _require(
                len(pooled) >= 2 and isinstance(doc.get("genes"), dict),
                "Complete comparison lacks a usable pool",
            )
            minimum = doc.get("effective_min_studies")
            _require(
                type(minimum) is int and 2 <= minimum <= len(pooled), "Invalid effective minimum"
            )
            if minimum < doc["params"]["min_studies"]:
                _require(bool(doc["warnings"]), "Reduced minimum is not disclosed")
        if doc["status"] == "insufficient":
            _require(len(pooled) < 2, "Insufficient status contradicts recorded pool size")
        if doc["status"] == "failed":
            _require(bool(doc.get("error")), "Failed status has no error record")
        if "members" in paths:
            rows = _rows(paths["members"])
            _require(
                [r["label"] for r in rows] == list(members), "Member table identities/order differ"
            )
            for row in rows:
                member = members[row["label"]]
                _require(
                    row["gse"] == member["gse"]
                    and row["contrast"] == member["contrast"]
                    and _boolean(row["pooled"]) == member["pooled"],
                    "Member table and report disagree",
                )
        elif doc["status"] != "failed":
            result.unavailable.append("Member ledger table missing")
        if "excluded" in paths:
            rows = _rows(paths["excluded"])
            _require(len(rows) == len(doc["excluded"]), "Exclusion table length differs")
            for row, item in zip(rows, doc["excluded"], strict=True):
                _require(
                    row["label"] == item["label"] and row["reason"] == item["reason"],
                    "Exclusion table differs",
                )

    _check(result, "membership_ledger", ledger)

    def concordance():
        corr = doc["concordance"]
        labels = corr["members"]
        _require(
            len(set(labels)) == len(labels) and set(labels) == set(members),
            "Concordance axes differ",
        )
        n = len(labels)
        values = np.array(
            [[np.nan if x is None else x for x in row] for row in corr["spearman"]], dtype=float
        )
        shared = np.asarray(corr["n_shared"])
        _require(values.shape == shared.shape == (n, n), "Concordance matrix shape differs")
        _require(np.allclose(values, values.T, equal_nan=True), "Asymmetric concordance matrix")
        finite = values[np.isfinite(values)]
        _require((abs(finite) <= 1).all(), "Correlation outside its range")
        _require(
            np.array_equal(shared, shared.T)
            and (shared >= 0).all()
            and (shared == np.floor(shared)).all(),
            "Invalid shared-gene counts",
        )
        if "concordance" in paths:
            table = _table(paths["concordance"])
            _require(
                list(table.index) == list(table.columns) == labels, "Concordance table axes differ"
            )
            observed = table.apply(pd.to_numeric, errors="coerce").to_numpy()
            _require(
                np.allclose(observed, values, rtol=0, atol=0.0000501, equal_nan=True),
                "Concordance table values differ",
            )
        else:
            result.unavailable.append("Concordance table unavailable")

    if doc.get("concordance") is not None:
        _check(result, "concordance", concordance)

    def gene_summary(summary, path, expected_labels):
        _require(summary["members"] == expected_labels, "Gene synthesis pool differs from ledger")
        table = _table(path)
        _require(len(table) == summary["n_genes_union"], "Gene union count differs")
        for prefix in ("lfc__", "padj__"):
            labels = {
                name.removeprefix(prefix) for name in table.columns if name.startswith(prefix)
            }
            _require(labels == set(expected_labels), "Per-study gene columns differ from pool")
        numeric = {}
        for name in (
            "n_tested",
            "n_with_padj",
            "n_sig",
            "n_up_sig",
            "n_down_sig",
            "n_pos",
            "n_neg",
            "n_agree_pooled",
        ):
            value = np.asarray(pd.to_numeric(table[name], errors="raise"), dtype=float)
            _require(
                np.isfinite(value).all()
                and (value >= 0).all()
                and (value == np.floor(value)).all(),
                f"Invalid {name} counts",
            )
            numeric[name] = value
        tested = numeric["n_tested"]
        _require(
            (tested <= len(expected_labels)).all(), "Gene claims more tested studies than pool"
        )
        _require(
            (numeric["n_sig"] <= numeric["n_with_padj"]).all()
            and (numeric["n_with_padj"] <= tested).all(),
            "Significance denominator counts disagree",
        )
        _require(
            (numeric["n_up_sig"] + numeric["n_down_sig"] <= numeric["n_sig"]).all(),
            "Directional significance exceeds total",
        )
        _require(
            (numeric["n_pos"] + numeric["n_neg"] <= tested).all()
            and (numeric["n_agree_pooled"] <= tested).all(),
            "Sign counts exceed tested studies",
        )
        estimates = np.asarray(
            pd.to_numeric(table["pooled_log2fc"].replace("", np.nan), errors="raise"), dtype=float
        )
        has_estimate = np.isfinite(estimates)
        _require(int(has_estimate.sum()) == summary["n_genes_pooled"], "Pooled gene count differs")
        for name in ("sign_consistency", "replication"):
            observed = np.asarray(pd.to_numeric(table[name], errors="raise"), dtype=float)
            numerator = (
                numeric["n_agree_pooled"]
                if name == "sign_consistency"
                else np.where(estimates > 0, numeric["n_up_sig"], numeric["n_down_sig"])
            )
            expected = np.divide(numerator, tested, out=np.zeros(len(table)), where=tested > 0)
            expected = np.where(has_estimate, expected, 0)
            _require(
                np.allclose(observed, expected, rtol=0, atol=0.0000051),
                f"{name} disagrees with recorded denominator",
            )
        robust = np.array([_boolean(v) for v in table["robust"]])
        _require(int(robust.sum()) == summary["n_robust"], "Robust gene count differs")
        _require(
            int((robust & (estimates > 0)).sum()) == summary["n_robust_up"]
            and int((robust & (estimates < 0)).sum()) == summary["n_robust_down"],
            "Robust direction counts differ",
        )
        for direction in ("top_up", "top_down"):
            _require(
                all(item["gene_id"] in table.index for item in summary[direction]),
                "Top gene absent from table",
            )

    if doc.get("genes"):
        if "gene_table" in paths:
            _check(
                result,
                "gene_summary",
                lambda: gene_summary(doc["genes"], paths["gene_table"], pooled),
            )
        else:
            result.unavailable.append("Gene synthesis has no readable gene table")
    for name, summary in doc.get("strata", {}).items():
        labels = [label for label in pooled if members[label].get("stratum") == name]
        path = paths.get(f"stratum_{name}")
        if path is None:
            result.unavailable.append(f"Stratum table missing: {name}")
        else:
            _check(
                result,
                f"stratum:{name}",
                lambda s=summary, p=path, labels=labels: gene_summary(s, p, labels),
            )

    def sensitivity():
        seen = set()
        for row in doc["sensitivity"]:
            key = (row["member"], row["flag"])
            _require(
                key not in seen and row["member"] in members,
                "Unknown or duplicate sensitivity membership",
            )
            seen.add(key)
            member = members[row["member"]]
            _require(
                row["flag"] in member["flags"] and row["pooled_by_default"] == member["pooled"],
                "Sensitivity flag or membership differs",
            )
            _require(0 <= row["robust_jaccard"] <= 1, "Sensitivity overlap outside its range")
        expected = {
            (label, flag)
            for label, member in members.items()
            for flag in member["flags"]
            if flag in {"labels_reversed", "low_concordance"}
            and len(pooled) + (-1 if member["pooled"] else 1) >= 2
        }
        if doc["status"] == "complete":
            _require(seen == expected, "Missing sensitivity result for a flagged member")
            loo = [item["member"] for item in doc["leave_one_out"]]
            _require(len(set(loo)) == len(loo), "Duplicate leave-one-out result")
            if len(pooled) >= 3:
                _require(set(loo) == set(pooled), "Leave-one-out pool differs")
        if any("labels_reversed" in member["flags"] for member in members.values()):
            _require(bool(doc["questions"]), "Suspected reversal has no recorded question")

    _check(result, "sensitivity_membership", sensitivity)
    if source_runs is None:
        result.unavailable.append(
            "Member source reports not supplied; source identity/overlap unchecked"
        )
    else:
        pooled_samples: set[str] = set()
        for label, member in members.items():
            if label not in source_runs:
                result.unavailable.append(f"Member source report missing: {label}")
                continue

            def source(label=label, member=member):
                folder = Path(source_runs[label])
                observed = Inspection("member")
                path = _record(observed, folder, "report.json")
                result.sha256[f"source:{label}/report.json"] = observed.sha256["report.json"]
                original = json.loads(path.read_text())
                _require(
                    original["gse"] == member["gse"]
                    and original["contrast"]["name"] == member["contrast"],
                    "Source identity differs",
                )
                _require(
                    original["status"] == "complete" and original.get("de"),
                    "Included source is not a completed analysis",
                )
                summary = original["de"]["summary"]
                ids = summary.get("gsms_fitted", []) or original["reconciliation"]["gsms_used"]
                _require(len(set(ids)) == len(ids), "Duplicate fitted source sample IDs")
                if member["pooled"]:
                    _require(not pooled_samples & set(ids), "Pooled reports reuse source samples")
                    pooled_samples.update(ids)
                _require(
                    member["n_case"] == summary["n_case_used"]
                    and member["n_control"] == summary["n_control_used"],
                    "Source fitted counts differ",
                )

            _check(result, f"source:{label}", source)
    result.unavailable.extend(
        [
            "Scientific comparability, family/donor independence and numerical reference "
            "not adjudicated",
            "Excluded-input reasons and pooled statistics are preserved, "
            "not independently reproduced",
        ]
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument(
        "--source-map",
        type=Path,
        help="JSON mapping of member labels to explicitly approved source folders",
    )
    args = parser.parse_args()
    sources = json.loads(args.source_map.read_text()) if args.source_map else None
    result = read_comparison(args.folder, source_runs=sources)
    print(json.dumps(result.result(), indent=2))
    raise SystemExit(1 if result.errors else 0)


if __name__ == "__main__":
    main()
