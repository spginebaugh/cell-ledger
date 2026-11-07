"""Score independently annotated study bundles; never infer gold from our validators."""

import argparse
import json
from pathlib import Path

import pandas as pd


def score(gold: dict, root: Path) -> dict:
    result = {"correct_studies": 0, "total_studies": 0, "critical_errors": []}
    manifest = json.loads((root / "manifest.json").read_text())
    considered = {item["gse"]: item for item in manifest["datasets"]}
    for gse, expected in gold["studies"].items():
        result["total_studies"] += 1
        errors = []
        if gse not in considered:
            errors.append("Expected study absent from candidates")
        elif expected["status"] == "excluded":
            if considered[gse]["status"] != "excluded":
                errors.append("Unsafe study was not excluded")
        else:
            folder = root / "datasets" / gse
            if not (folder / "study.json").exists():
                errors.append("Expected study bundle is missing")
            else:
                study = json.loads((folder / "study.json").read_text())
                if study["units"] != expected["units"]:
                    errors.append("Wrong expression units")
                if study["de_ready"] != expected["de_ready"]:
                    errors.append("Wrong DE capability")
                samples = pd.read_csv(folder / "samples.csv", index_col="gsm")
                expected_groups = expected["groups"]
                if set(samples.index) != set(expected_groups):
                    errors.append("Incorrect exported sample identities")
                for gsm, group in expected_groups.items():
                    if gsm in samples.index and samples.loc[gsm, "group"] != group:
                        errors.append(f"Wrong group for {gsm}")
        if errors:
            result["critical_errors"].append({"gse": gse, "errors": errors})
        else:
            result["correct_studies"] += 1
    result["fraction_correct"] = (
        result["correct_studies"] / result["total_studies"] if result["total_studies"] else None
    )
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gold", type=Path)
    parser.add_argument("bundle", type=Path)
    args = parser.parse_args()
    print(json.dumps(score(json.loads(args.gold.read_text()), args.bundle), indent=2))
