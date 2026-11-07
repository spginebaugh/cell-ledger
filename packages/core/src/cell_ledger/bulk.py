"""Conservative human bulk RNA-seq contract, evidence checks, and matrix QC."""

from __future__ import annotations

import csv
import gzip
import io
import re
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from cell_ledger.geo.models import GeoError, GeoSample, GeoSeries


class Label(BaseModel):
    value: str
    evidence: str = Field(min_length=1)
    source_field: str
    confidence: float = Field(ge=0, le=1)


class HarmonizedSample(BaseModel):
    gsm: str = Field(pattern=r"^GSM\d+$")
    title: str
    platform: str
    group: Literal["case", "control", "other", "unknown"] = "unknown"
    labels: dict[str, Label] = Field(default_factory=dict)
    needs_review: bool = True
    issues: list[str] = Field(default_factory=list)


LABEL_FIELDS = {
    "group",
    "condition",
    "treatment",
    "dose",
    "time_point",
    "tissue",
    "cell_type",
    "cell_line",
    "genotype",
    "sex",
    "age",
    "replicate",
    "donor",
    "batch",
}
ALIASES = {
    "condition": "condition",
    "disease": "condition",
    "disease state": "condition",
    "infection": "condition",
    "treatment": "treatment",
    "dose": "dose",
    "time": "time_point",
    "time point": "time_point",
    "tissue": "tissue",
    "cell type": "cell_type",
    "cell line": "cell_line",
    "genotype": "genotype",
    "sex": "sex",
    "age": "age",
    "donor": "donor",
    "donor id": "donor",
    "batch": "batch",
    "replicate": "replicate",
}


def validate_labels(sample: GeoSample, proposals: dict[str, Label]) -> HarmonizedSample:
    result = HarmonizedSample(
        gsm=sample.gsm,
        title=sample.value("title"),
        platform=sample.value("platform_id"),
    )
    for field, label in proposals.items():
        if field not in LABEL_FIELDS:
            result.issues.append(f"Unsupported label: {field}")
        elif label.evidence not in sample.values(label.source_field):
            result.issues.append(f"{field}: evidence does not exactly match a source field")
        elif label.confidence < 0.7:
            result.issues.append(f"{field}: confidence below 0.7")
        elif field == "group" and label.value not in {"case", "control", "other", "unknown"}:
            result.issues.append("Invalid group label")
        else:
            result.labels[field] = label
    group = result.labels.get("group")
    if group:
        result.group = group.value  # type: ignore[assignment]
    result.needs_review = result.group == "unknown" or bool(result.issues)
    return result


def harmonize_rules(
    sample: GeoSample, *, case: str | None = None, control: str | None = None
) -> HarmonizedSample:
    """Copy known fields; assign roles only from explicitly supplied exact labels."""
    proposals: dict[str, Label] = {}
    conflicts: set[str] = set()
    for line in sample.values("characteristics_ch1"):
        key, separator, value = line.partition(":")
        field = ALIASES.get(key.strip().lower().replace("_", " "))
        if separator and field and value.strip():
            if field in proposals and proposals[field].value != value.strip():
                conflicts.add(field)
            proposals[field] = Label(
                value=value.strip(), evidence=line, source_field="characteristics_ch1", confidence=1
            )
    for field in conflicts:
        proposals.pop(field, None)
    matches = []
    for field in ("condition", "treatment"):
        label = proposals.get(field)
        if label:
            for role, target in (("case", case), ("control", control)):
                if target and label.value.casefold() == target.casefold():
                    matches.append((role, label))
    if len({role for role, _ in matches}) == 1:
        role, label = matches[0]
        proposals["group"] = label.model_copy(update={"value": role})
    result = validate_labels(sample, proposals)
    result.issues += [f"Conflicting source values for {field}" for field in sorted(conflicts)]
    result.needs_review = result.needs_review or bool(conflicts)
    return result


def sample_eligibility(sample: GeoSample) -> list[str]:
    reasons = []
    if sample.values("organism_ch1") != ["Homo sapiens"]:
        reasons.append(f"{sample.gsm}: organism is not unambiguously Homo sapiens")
    if sample.values("library_strategy") != ["RNA-Seq"]:
        reasons.append(f"{sample.gsm}: library strategy is not RNA-Seq")
    text = " ".join(value for values in sample.fields.values() for value in values).lower()
    if re.search(r"single[ -](cell|nucle)|scrna|snrna|10x|spatial|pseudobulk", text):
        reasons.append(f"{sample.gsm}: single-cell, nuclei, spatial or pseudobulk evidence")
    return reasons


def parse_matrix(payload: bytes, *, max_bytes: int = 500_000_000) -> pd.DataFrame:
    if payload.startswith(b"\x1f\x8b"):
        with gzip.GzipFile(fileobj=io.BytesIO(payload)) as archive:
            payload = archive.read(max_bytes + 1)
    if len(payload) > max_bytes:
        raise GeoError("Expanded matrix exceeds the configured size limit")
    text = payload.decode("utf-8-sig")
    if not text.strip() or text.lstrip().startswith("<"):
        raise GeoError("Download is not a text matrix")
    header = text.splitlines()[0]
    delimiter = "\t" if "\t" in header else ","
    columns = next(csv.reader([header], delimiter=delimiter))
    if len(columns) < 2 or len(set(columns[1:])) != len(columns[1:]):
        raise GeoError("Missing or duplicate matrix sample identifiers")
    table = pd.read_csv(io.StringIO(text), sep=delimiter, dtype=str, index_col=0)
    if table.empty or table.index.has_duplicates or table.index.isna().any():
        raise GeoError("Missing or duplicate gene identifiers")
    annotations = None
    if columns[:6] == ["Geneid", "Chr", "Start", "End", "Strand", "Length"]:
        if len(columns) <= 6:
            raise GeoError("FeatureCounts matrix has no sample columns")
        annotations = table.iloc[:, :5].reset_index().rename(columns={"Geneid": "gene_id"})
        table = table.iloc[:, 5:]
    try:
        table = pd.DataFrame(table.apply(pd.to_numeric, errors="raise"))
    except (ValueError, TypeError) as exc:
        raise GeoError("Matrix contains non-numeric expression values") from exc
    values = table.to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values < 0).any():
        raise GeoError("Matrix contains missing, infinite or negative expression values")
    table.index = table.index.astype(str)
    if annotations is not None:
        table.attrs["gene_annotation"] = annotations.to_dict(orient="list")
        table.attrs["source_format"] = "featureCounts"
    return table


class Validation(BaseModel):
    units: str
    qc_ready: bool = False
    de_ready: bool = False
    issues: list[str] = Field(default_factory=list)
    excluded_samples: dict[str, str] = Field(default_factory=dict)
    missing_samples: list[str] = Field(default_factory=list)
    library_sizes: dict[str, float] = Field(default_factory=dict)
    detected_genes: dict[str, int] = Field(default_factory=dict)
    sample_mapping: dict[str, dict[str, str]] = Field(default_factory=dict)


def map_sample_columns(series: GeoSeries, matrix: pd.DataFrame):
    """Resolve unique source aliases, never fuzzy matches or positional guesses."""
    aliases: dict[str, list[dict[str, str]]] = {}
    for sample in series.samples:
        for field in ("title", "description"):
            for value in sample.values(field):
                alias = value if field == "title" else ""
                if field == "description":
                    match = re.fullmatch(r"(?:Library name|Column name in [^:]+):\s*(.+)", value)
                    if match:
                        alias = match[1]
                if alias:
                    aliases.setdefault(alias, []).append(
                        {
                            "gsm": sample.gsm,
                            "source_field": field,
                            "evidence": value,
                            "rule": "exact source alias",
                        }
                    )
    # A uniform assay prefix is allowed only with a complete one-to-one cohort match.
    titles = {sample.gsm: sample.value("title") for sample in series.samples}
    stripped = {gsm: title.removeprefix("RNAseq_") for gsm, title in titles.items()}
    if (
        len(titles) > 1
        and all(title.startswith("RNAseq_") for title in titles.values())
        and len(set(stripped.values())) == len(stripped)
        and set(stripped.values()) == set(matrix.columns)
    ):
        for gsm, alias in stripped.items():
            aliases.setdefault(alias, []).append(
                {
                    "gsm": gsm,
                    "source_field": "title",
                    "evidence": titles[gsm],
                    "rule": "uniform RNAseq_ title prefix; complete bijection",
                }
            )
    mapping = {}
    for column in matrix.columns:
        if column in titles:
            mapping[column] = {
                "gsm": column,
                "source_field": "geo_accession",
                "evidence": column,
                "rule": "exact GSM",
            }
        elif column in aliases:
            candidates = aliases[column]
            if len({candidate["gsm"] for candidate in candidates}) != 1:
                raise GeoError(f"Ambiguous sample alias: {column}")
            mapping[column] = candidates[0]
    renamed = matrix.rename(columns={column: proof["gsm"] for column, proof in mapping.items()})
    if renamed.columns.has_duplicates:
        raise GeoError("Multiple matrix columns map to the same GEO sample")
    return renamed, mapping


def qc_dataset(
    series: GeoSeries,
    matrix: pd.DataFrame,
    samples: list[HarmonizedSample],
    *,
    units: str,
    min_per_group: int = 3,
) -> tuple[pd.DataFrame, Validation]:
    result = Validation(units=units)
    values = matrix.to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values < 0).any():
        raise GeoError("Expression values must be finite and nonnegative")
    if matrix.index.has_duplicates or matrix.columns.has_duplicates:
        raise GeoError("Duplicate gene or sample identifiers")
    matrix, result.sample_mapping = map_sample_columns(series, matrix)
    metadata = {sample.gsm: sample for sample in series.samples}
    labels = {sample.gsm: sample for sample in samples}
    if len(labels) != len(samples) or set(labels) != set(metadata):
        raise GeoError("Harmonized samples must match fetched GEO samples exactly")
    keep = []
    for column in matrix.columns:
        if column not in metadata:
            result.excluded_samples[column] = "No exact GSM match in metadata"
        else:
            reasons = sample_eligibility(metadata[column])
            if reasons:
                result.excluded_samples[column] = "; ".join(reasons)
            else:
                keep.append(column)
    result.missing_samples = sorted(set(metadata) - set(matrix.columns))
    aligned = matrix.loc[:, keep].copy()
    if not keep:
        result.issues.append("No eligible human bulk RNA-seq samples align to the matrix")
        return aligned, result
    if result.excluded_samples or result.missing_samples:
        result.issues.append("Incomplete sample mapping; exclusions require review")
    values = aligned.to_numpy(dtype=float)
    if units == "counts" and not (values == np.floor(values)).all():
        result.units = "unknown"
        result.issues.append("Claimed raw counts contain fractional values")
    if result.units not in {"counts", "tpm", "normalized"}:
        result.issues.append(
            "Expression units are unverified; integer-looking values are not proof"
        )
    result.qc_ready = result.units in {"counts", "tpm", "normalized"}
    result.detected_genes = {str(k): int(v) for k, v in (aligned > 0).sum().items()}
    if result.units == "counts":
        result.library_sizes = {str(k): float(v) for k, v in aligned.sum().items()}
        if (
            min(result.library_sizes.values()) < 100_000
            or np.median(list(result.library_sizes.values())) < 1_000_000
        ):
            result.issues.append("Low library size: sample <100k or median <1M counts")
    else:
        result.issues.append("Only documented raw counts can enter DESeq2")
    if aligned.T.duplicated().any():
        result.issues.append("Identical expression columns; possible duplicate samples")
    selected = [labels[gsm] for gsm in keep]
    for group in ("case", "control"):
        if sum(sample.group == group for sample in selected) < min_per_group:
            result.issues.append(f"Fewer than {min_per_group} {group} samples")
    if any(sample.needs_review or sample.group not in {"case", "control"} for sample in selected):
        result.issues.append("Unresolved or low-confidence sample labels")
    donors = [sample.labels["donor"].value for sample in selected if "donor" in sample.labels]
    if len(donors) != len(selected):
        result.issues.append("Biological independence is unresolved: donor identities are missing")
    if len(set(donors)) < len(donors):
        result.issues.append("Repeated donors: paired or technical replicate design is unsupported")
    design = series.value("overall_design").lower()
    if re.search(
        r"single[ -](cell|nucle)|scrna|snrna|spatial|pseudobulk",
        " ".join(series.value(key) for key in ("title", "summary", "overall_design")),
        re.I,
    ):
        result.issues.append("Series describes an unsupported or mixed single-cell/spatial assay")
    if re.search(r"paired|repeated.measure|technical replicate|pooled", design):
        result.issues.append("Design indicates paired, repeated, technical or pooled samples")
    for field in ("batch", "tissue", "time_point", "platform"):
        groups = {group: set() for group in ("case", "control")}
        for sample in selected:
            value = (
                sample.platform
                if field == "platform"
                else (sample.labels[field].value if field in sample.labels else "")
            )
            if value and sample.group in groups:
                groups[sample.group].add(value)
        if groups["case"] and groups["control"] and groups["case"].isdisjoint(groups["control"]):
            result.issues.append(f"Condition is confounded with {field}")
    result.de_ready = result.qc_ready and result.units == "counts" and not result.issues
    return aligned, result
