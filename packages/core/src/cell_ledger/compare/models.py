"""Serializable cross-dataset comparison: every number the UI or the LLM may cite lives here.

A comparison consumes finished run directories (one ``AnalysisReport`` plus its DE and
enrichment tables each) for runs that answer the same question, and produces one
``ComparisonReport``. Counts are never read; every dataset keeps its own DESeq2 fit.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from cell_ledger.report.models import EnrichmentSummary, MarkerExpectation

SLUG = r"^[a-z0-9]+(_[a-z0-9]+)*$"


class QuerySetMember(BaseModel):
    gse: str = Field(pattern=r"^GSE\d+$")
    contrast: str = Field(pattern=SLUG)
    stratum: str | None = Field(
        default=None,
        pattern=SLUG,
        description="sub-question this run answers (e.g. lesional_vs_healthy); runs are pooled "
        "overall and per stratum, and concordance is judged within a stratum",
    )


class QuerySet(BaseModel):
    """Which runs answer one question. Written by the agent (or by hand), verified by code."""

    name: str = Field(pattern=SLUG)
    question: str
    case_label: str
    control_label: str
    members: list[QuerySetMember] = Field(min_length=1)
    markers: list[MarkerExpectation] = Field(default_factory=list)
    genes_of_interest: list[str] = Field(default_factory=list)


Interval = Literal["hksj", "normal"]


class CompareParams(BaseModel):
    alpha: float = Field(default=0.05, gt=0, lt=1)
    min_studies: int = Field(default=3, ge=2, description="datasets a gene must be tested in")
    low_concordance: float = Field(
        default=0.2,
        description="a run whose mean Spearman correlation of Wald statistics with the other "
        "runs of its stratum is below this is flagged 'low_concordance' (still pooled; a "
        "sensitivity result without it is reported)",
    )
    reversed_concordance: float = Field(
        default=-0.2,
        description="below this the run is flagged 'labels_reversed', left out of the default "
        "pool, and a question is written; a sensitivity result with it is reported",
    )
    pool_flagged: bool = Field(
        default=False, description="pool runs flagged labels_reversed anyway"
    )
    include_qualified: bool = True
    sign_consistency: float = Field(
        default=2 / 3,
        description="fraction of tested datasets whose sign must match the pooled direction "
        "for a 'robust' gene",
    )
    min_replication: float = Field(
        default=0.5,
        description="fraction of tested datasets in which a 'robust' gene must be significant "
        "in the pooled direction",
    )
    lfc_threshold: float = Field(
        default=1.0, description="|pooled log2FC| floor for the top-gene tables (not for 'robust')"
    )
    interval: Interval = Field(
        default="hksj",
        description="Hartung-Knapp-Sidik-Jonkman t intervals on the DerSimonian-Laird estimate "
        "(recommended for few studies) or the normal approximation",
    )
    top_n: int = 50
    figures: bool = True
    pooled_enrichment: bool = True
    gene_sets: str = "msigdb_hallmark_2020"
    permutation_num: int = 1000
    genes_of_interest: list[str] = Field(default_factory=list)
    markers: list[MarkerExpectation] = Field(default_factory=list)


Tier = Literal["clean", "qualified"]
MemberFlag = Literal["labels_reversed", "low_concordance", "concordance_unassessed"]


class Member(BaseModel):
    """One run that passed the hard gate, as the ledger shows it."""

    label: str
    gse: str
    contrast: str
    run_dir: str
    stratum: str | None = None
    concordance_group: str = Field(
        default="all", description="runs are judged against the others in this group"
    )
    tier: Tier
    pooled: bool = Field(description="contributes to the default pooled estimate")
    flags: list[MemberFlag] = Field(default_factory=list)
    case_label: str
    control_label: str
    n_case: int
    n_control: int
    n_samples_fitted: int
    design: str
    pairing: str
    collapsed_samples: int = 0
    median_library_size: float
    n_genes_tested: int
    n_sig: int
    qc_flags: list[str] = Field(default_factory=list)
    qualifications: list[str] = Field(default_factory=list)
    context: dict[str, str] = Field(default_factory=dict)
    mean_concordance: float | None = None
    weight_share: float | None = Field(
        default=None, description="mean random-effects weight share over pooled genes"
    )
    unshrunk_se_source: Literal["stored", "reconstructed"] = "stored"
    fingerprint: str | None = None
    created_at: datetime | None = None


ExclusionReason = Literal[
    "missing", "unreadable", "not_complete", "no_de_table", "qualified", "shares_samples"
]


class Exclusion(BaseModel):
    label: str
    gse: str | None = None
    contrast: str | None = None
    run_dir: str
    reason: ExclusionReason
    detail: str


class Concordance(BaseModel):
    """Pairwise Spearman correlation of Wald statistics over genes tested in both runs.

    ``mean_to_others`` is each run's mean against the other runs of its concordance
    group, leaving out runs flagged ``labels_reversed``.
    """

    members: list[str]
    spearman: list[list[float | None]]
    n_shared: list[list[int]]
    mean_to_others: dict[str, float | None]
    groups: dict[str, str] = Field(default_factory=dict, description="label -> group")


class GeneMeta(BaseModel):
    gene_id: str
    symbol: str | None = None
    n_tested: int = Field(description="datasets with a valid estimate and SE (pooled)")
    n_with_padj: int = Field(description="of those, datasets where DESeq2 reported a padj")
    n_sig: int
    n_up_sig: int
    n_down_sig: int
    n_pos: int
    n_neg: int
    n_agree_pooled: int = Field(description="datasets whose sign matches the pooled direction")
    replication: float = Field(
        description="datasets significant in the pooled direction / n_tested"
    )
    sign_consistency: float = Field(description="n_agree_pooled / n_tested")
    majority_disagrees_pooled: bool = Field(
        default=False, description="most datasets point the other way from the pooled estimate"
    )
    pooled_log2fc: float | None = None
    pooled_se: float | None = Field(default=None, description="random-effects SE (normal)")
    se_ci: float | None = Field(default=None, description="SE behind the interval and p-value")
    df: int | None = None
    ci_low: float | None = None
    ci_high: float | None = None
    z: float | None = Field(default=None, description="pooled / pooled_se, for ranking")
    pvalue: float | None = None
    padj: float | None = None
    tau2: float | None = None
    i2: float | None = None
    stouffer_z: float | None = None
    robust: bool = False


class GeneSynthesis(BaseModel):
    members: list[str]
    min_studies: int
    alpha: float
    sign_consistency: float
    min_replication: float
    interval: Interval
    n_genes_union: int
    n_genes_pooled: int
    n_sig_pooled: int
    n_robust: int
    n_robust_up: int
    n_robust_down: int
    lfc_threshold: float = Field(
        default=0.0, description="top tables list robust genes with |pooled log2FC| >= this"
    )
    n_robust_up_lfc: int = 0
    n_robust_down_lfc: int = 0
    top_up: list[GeneMeta]
    top_down: list[GeneMeta]


AcrossVerdict = Literal[
    "replicated_up",  # robust: pooled padj < alpha, consistent sign, significant in >= half
    "replicated_down",
    "pooled_up",  # pooled padj < alpha and consistent sign, but significant in < half
    "pooled_down",
    "inconsistent",  # significant in opposite directions, or pooled but signs disagree
    "no_evidence",
    "insufficient",  # tested in fewer than the effective minimum number of datasets
    "not_found",
]


class GeneLeaveOneOut(BaseModel):
    """The same gene pooled without one dataset."""

    member: str
    pooled_log2fc: float | None = None
    ci_low: float | None = None
    ci_high: float | None = None
    pvalue: float | None = None
    verdict: AcrossVerdict
    changed: bool = Field(description="verdict differs from the full-set verdict")


class GeneLookupAcross(BaseModel):
    """The direct answer to 'is gene X higher in case than control' across datasets."""

    query: str
    gene_id: str | None
    symbol: str | None
    verdict: AcrossVerdict
    detail: str
    meta: GeneMeta | None = None
    per_member: dict[str, str] = Field(
        default_factory=dict, description="label -> up / down / no_evidence / not_tested"
    )
    leave_one_out: list[GeneLeaveOneOut] = Field(default_factory=list)
    driven_by: list[str] = Field(
        default_factory=list, description="datasets whose removal changes the verdict"
    )


class MarkerAcross(BaseModel):
    expected: MarkerExpectation
    lookup: GeneLookupAcross
    recovered: bool


class MarkerAcrossScore(BaseModel):
    n_expected: int
    n_recovered: int
    fraction_recovered: float
    results: list[MarkerAcross]


class PathwayMeta(BaseModel):
    term: str
    n_members: int
    mean_nes: float
    n_pos: int
    n_neg: int
    n_sig_fdr: int
    consistency: float = Field(description="max(n_pos, n_neg) / n_members")
    nes: dict[str, float] = Field(default_factory=dict)
    fdr: dict[str, float] = Field(default_factory=dict)


class PathwaySynthesis(BaseModel):
    library: str
    gene_sets_md5: str | None = None
    members: list[str] = Field(default_factory=list)
    left_out: dict[str, str] = Field(
        default_factory=dict, description="label -> why its enrichment was not merged"
    )
    fdr_threshold: float
    n_terms: int
    n_consistent: int = Field(description="terms with the same sign in every member")
    terms: list[PathwayMeta]


class LeaveOneOut(BaseModel):
    member: str
    n_robust_without: int
    robust_retained: float = Field(description="share of robust genes still robust without it")
    spearman_pooled_z: float | None = None


class Sensitivity(BaseModel):
    """The synthesis with a flagged run's membership reversed."""

    member: str
    flag: MemberFlag
    pooled_by_default: bool
    n_robust_default: int
    n_robust_alternative: int
    robust_jaccard: float
    spearman_pooled_z: float | None = None


Status = Literal["complete", "insufficient", "failed"]


class ComparisonReport(BaseModel):
    name: str
    question: str
    case_label: str
    control_label: str
    status: Status
    error: str | None = None
    created_at: datetime
    versions: dict[str, str]
    params: dict[str, Any]
    effective_min_studies: int | None = Field(
        default=None, description="min_studies actually applied (lowered when few datasets)"
    )
    members: list[Member] = Field(default_factory=list)
    excluded: list[Exclusion] = Field(default_factory=list)
    questions: list[str] = Field(
        default_factory=list, description="what a person must decide before trusting the pool"
    )
    concordance: Concordance | None = None
    genes: GeneSynthesis | None = None
    strata: dict[str, GeneSynthesis] = Field(default_factory=dict)
    gene_lookup: list[GeneLookupAcross] = Field(default_factory=list)
    markers: MarkerAcrossScore | None = None
    pathways: PathwaySynthesis | None = None
    pooled_enrichment: EnrichmentSummary | None = Field(
        default=None, description="GSEA preranked on the pooled z over genes with a symbol"
    )
    pooled_enrichment_coverage: dict[str, int] = Field(default_factory=dict)
    leave_one_out: list[LeaveOneOut] = Field(default_factory=list)
    sensitivity: list[Sensitivity] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    files: dict[str, str] = Field(default_factory=dict)
    figures: dict[str, str] = Field(default_factory=dict)
