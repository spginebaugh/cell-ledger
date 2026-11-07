"""Serializable analysis report: every number the UI or the LLM may cite lives here."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from cell_ledger.samplesheet import Contrast


class StepRecord(BaseModel):
    """One pipeline step: what ran, with which parameters, how long, and what it warned."""

    name: str
    params: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime
    seconds: float = 0.0
    warnings: list[str] = Field(default_factory=list)


class Reconciliation(BaseModel):
    """How the counts matrix columns lined up with the sample sheet and contrast."""

    n_counts_columns: int
    n_sheet_gsms: int
    n_contrast_gsms: int
    gsms_used: list[str]
    contrast_gsms_missing_from_counts: list[str]
    contrast_gsms_missing_from_sheet: list[str] = Field(default_factory=list)
    sheet_gsms_missing_from_counts: list[str]
    columns_not_in_sheet: list[str]
    n_genes: int
    n_case: int
    n_control: int


class SampleQc(BaseModel):
    gsm: str
    arm: str
    library_size: int
    detected_genes: int
    pct_mito: float
    pct_ribo: float
    mean_corr_same_arm: float | None = None
    mean_corr_other_arm: float | None = None
    reported_sex: str | None = None
    predicted_sex: str | None = None
    flags: list[str] = Field(default_factory=list)


class PcaSummary(BaseModel):
    n_genes_used: int
    variance_ratio: list[float]
    coords: dict[str, list[float]]
    arm_r2_pc1: float | None = None


class QcResult(BaseModel):
    samples: list[SampleQc]
    median_library_size: float
    pca: PcaSummary | None = None
    flags: list[str] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)


class FilterSummary(BaseModel):
    n_genes_before: int
    n_genes_after: int
    min_count: int
    min_samples: int


class GeneRow(BaseModel):
    gene_id: str
    symbol: str | None
    base_mean: float
    log2fc: float
    lfc_se: float | None = None
    stat: float | None = None
    pvalue: float | None = None
    padj: float | None = None


Pairing = Literal["none", "modelled", "incomplete_dropped", "ignored"]


class DeSummary(BaseModel):
    design: str
    coefficient: str
    blocking: str | None = None
    pairing: Pairing = "none"
    n_case_used: int
    n_control_used: int
    dropped_unpaired: list[str] = Field(default_factory=list)
    lfc_shrunk: bool
    alpha: float
    lfc_threshold: float
    n_genes_tested: int
    n_sig: int
    n_up: int
    n_down: int
    n_up_lfc: int
    n_down_lfc: int


class DeResultSummary(BaseModel):
    summary: DeSummary
    top_up: list[GeneRow]
    top_down: list[GeneRow]


class EnrichmentTerm(BaseModel):
    term: str
    nes: float
    pvalue: float
    fdr: float
    size: int
    lead_genes: list[str]


class EnrichmentSummary(BaseModel):
    library: str
    n_terms: int
    n_sig_fdr: int
    fdr_threshold: float
    top: list[EnrichmentTerm]
    params: dict[str, Any] = Field(default_factory=dict)


Verdict = Literal["up", "down", "no_evidence", "untestable", "not_tested", "not_found", "not_run"]


class GeneLookupRow(BaseModel):
    """The direct answer to 'is gene X higher in case than control' for one dataset."""

    query: str
    gene_id: str | None
    symbol: str | None
    verdict: Verdict
    reason: str | None = Field(
        default=None,
        description="why no verdict: 'independent_filtering' (padj NA), 'outlier_or_all_zero' "
        "(pvalue NA), 'filtered_before_testing', 'symbol_not_in_annotation', 'de_not_run'",
    )
    log2fc: float | None = None
    padj: float | None = None
    base_mean: float | None = None
    mean_norm_case: float | None = None
    mean_norm_control: float | None = None
    rank_by_padj: int | None = None


class MarkerExpectation(BaseModel):
    symbol: str
    direction: Literal["up", "down"]


class MarkerResult(BaseModel):
    expected: MarkerExpectation
    lookup: GeneLookupRow
    recovered_sig: bool
    in_top_n_correct_sign: bool


class MarkerScore(BaseModel):
    n_expected: int
    n_recovered_sig: int
    n_in_top_n: int
    top_n: int
    fraction_recovered: float
    fraction_in_top_n: float
    results: list[MarkerResult]


Status = Literal["complete", "qc_only", "blocked"]


class AnalysisReport(BaseModel):
    gse: str
    contrast: Contrast
    status: Status
    blockers: list[str] = Field(default_factory=list)
    qualifications: list[str] = Field(
        default_factory=list,
        description="result stands but must be read with these caveats (uncertain labels etc.)",
    )
    error: str | None = Field(
        default=None, description="set when the pipeline stopped on an exception"
    )
    created_at: datetime
    versions: dict[str, str]
    params: dict[str, Any]
    steps: list[StepRecord] = Field(default_factory=list)
    reconciliation: Reconciliation | None = None
    qc: QcResult | None = None
    filtering: FilterSummary | None = None
    de: DeResultSummary | None = None
    enrichment: EnrichmentSummary | None = None
    gene_lookup: list[GeneLookupRow] = Field(default_factory=list)
    markers: MarkerScore | None = None
    warnings: list[str] = Field(default_factory=list)
    files: dict[str, str] = Field(default_factory=dict)
    figures: dict[str, str] = Field(default_factory=dict)
