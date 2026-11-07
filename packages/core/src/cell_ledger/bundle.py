"""Write independently loadable study bundles and a fixed, opt-in DE workflow."""

from __future__ import annotations

import json
from pathlib import Path

import anndata as ad
import numpy as np
import pandas as pd

from cell_ledger.bulk import HarmonizedSample, Validation
from cell_ledger.geo.models import GeoError, GeoSeries


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def assemble_dataset(
    root: Path,
    series: GeoSeries,
    matrix: pd.DataFrame,
    samples: list[HarmonizedSample],
    validation: Validation,
    provenance: dict,
    annotation: pd.DataFrame | None = None,
) -> None:
    """Only source-backed samples can be assembled; matrix order controls obs order."""
    source_ids = {sample.gsm for sample in series.samples}
    if not set(matrix.columns) <= source_ids:
        raise GeoError("Assembler refused a sample absent from fetched metadata")
    folder = root / "datasets" / series.gse
    folder.mkdir(parents=True, exist_ok=False)
    rows = []
    for sample in samples:
        if sample.gsm not in matrix.columns:
            continue
        rows.append(
            {
                "gsm": sample.gsm,
                "title": sample.title,
                "platform": sample.platform,
                "group": sample.group,
                "needs_review": sample.needs_review,
                **{
                    field: label.value for field, label in sample.labels.items() if field != "group"
                },
                "confidence": min(
                    (label.confidence for label in sample.labels.values()), default=0
                ),
                "evidence": json.dumps(
                    {field: label.model_dump() for field, label in sample.labels.items()}
                ),
            }
        )
    metadata = pd.DataFrame(rows).set_index("gsm").reindex(matrix.columns).fillna("")
    metadata.index.name = "gsm"
    metadata.to_csv(folder / "samples.csv")
    genes = pd.DataFrame({"gene_id": matrix.index.astype(str)})
    if annotation is not None:
        annotation = annotation.rename(columns={annotation.columns[0]: "gene_id"})
        if annotation["gene_id"].duplicated().any():
            raise GeoError("Gene annotation has duplicate original gene IDs")
        genes = genes.merge(annotation, on="gene_id", how="left", validate="one_to_one")
    genes.to_csv(folder / "genes.tsv", sep="\t", index=False)
    name = (
        "counts.tsv"
        if validation.units == "counts"
        else ("tpm.tsv" if validation.units == "tpm" else "expression.tsv")
    )
    matrix.to_csv(folder / name, sep="\t", index_label="gene_id")
    write_json(folder / "validation.json", validation.model_dump())
    write_json(folder / "source_metadata.json", series.model_dump())
    write_json(folder / "provenance.json", provenance)
    write_json(
        folder / "study.json",
        {
            "gse": series.gse,
            "title": series.value("title"),
            "summary": series.value("summary"),
            "design": series.value("overall_design"),
            "units": validation.units,
            "matrix_file": name,
            "qc_ready": validation.qc_ready,
            "de_ready": validation.de_ready,
            "orientation": "genes_by_samples",
            "analysis_executed": False,
        },
    )
    # Avoid pandas extension strings/nullable types in h5ad on different library versions.
    obs = metadata.copy()
    for column in obs.columns:
        if obs[column].dtype.kind not in "biuf":
            obs[column] = np.asarray(obs[column].astype(str), dtype=object)
    obs.index = np.asarray(obs.index.astype(str), dtype=object)
    var = genes.set_index("gene_id").fillna("")
    for column in var.columns:
        var[column] = np.asarray(var[column].astype(str), dtype=object)
    var.index = np.asarray(var.index.astype(str), dtype=object)
    dataset = ad.AnnData(X=matrix.T.to_numpy(), obs=obs, var=var)
    dataset.uns["provenance_json"] = json.dumps(provenance)
    dataset.uns["expression_units"] = validation.units
    dataset.uns["analysis_executed"] = False
    dataset.write_h5ad(folder / "dataset.h5ad")


def load_bundle(folder: str | Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    folder = Path(folder)
    study = json.loads((folder / "study.json").read_text())
    matrix = pd.read_csv(folder / study["matrix_file"], sep="\t", index_col=0).T
    samples = pd.read_csv(folder / "samples.csv", index_col="gsm", keep_default_na=False)
    genes = pd.read_csv(folder / "genes.tsv", sep="\t", dtype=str).set_index("gene_id")
    matrix.columns = matrix.columns.astype(str)
    if not matrix.index.equals(samples.index) or not matrix.columns.equals(genes.index):
        raise GeoError("Bundle sample/gene order does not match its metadata")
    return matrix, samples, genes, study


DESEQ_SCRIPT = '''"""Run approved contrasts. The agent has not executed any analysis."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
from pydeseq2.dds import DeseqDataSet
from pydeseq2.ds import DeseqStats

root = Path(__file__).resolve().parent
contrasts = json.loads((root / "contrasts.json").read_text())
if not contrasts:
    raise SystemExit("No DE-ready contrasts. Review questions.md.")
for contrast in contrasts:
    folder = root / "datasets" / contrast["gse"]
    validation = json.loads((folder / "validation.json").read_text())
    if not validation["de_ready"] or validation["units"] != "counts":
        raise ValueError("Dataset no longer passes the raw-count/design gates")
    counts = pd.read_csv(folder / "counts.tsv", sep="\\t", index_col=0).T
    metadata = pd.read_csv(folder / "samples.csv", index_col="gsm")
    if not counts.index.equals(metadata.index):
        raise ValueError("Sample identities or order changed")
    values = counts.to_numpy()
    if (
        not np.isfinite(values).all() or (values < 0).any()
        or not (values == np.floor(values)).all()
    ):
        raise ValueError("Expected nonnegative integer counts")
    if set(metadata["group"]) != {"case", "control"}:
        raise ValueError("Expected an explicit two-group design")
    if metadata.groupby("group").size().min() < contrast["min_per_group"]:
        raise ValueError("Too few biological samples")
    counts = counts.loc[:, counts.sum(axis=0) >= 10]
    dds = DeseqDataSet(counts=counts, metadata=metadata, design="~group", n_cpus=1)
    dds.deseq2()
    stats = DeseqStats(dds, contrast=["group", "case", "control"], n_cpus=1)
    stats.summary()
    stats.results_df.to_csv(folder / "deseq_results.tsv", sep="\\t")
    print(f"Completed {contrast['gse']}: case relative to control")
'''
