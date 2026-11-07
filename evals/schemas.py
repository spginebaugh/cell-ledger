"""Export machine-readable output contracts; no gold or credentials are included."""

from pathlib import Path

from evals.contracts import Benchmark, Conditions, RunRecord, Snapshot

if __name__ == "__main__":
    import json

    output = Path(__file__).parent / "schemas"
    output.mkdir(exist_ok=True)
    for model in (Benchmark, Conditions, RunRecord, Snapshot):
        (output / f"{model.__name__}.json").write_text(
            json.dumps(model.model_json_schema(), indent=2) + "\n"
        )
