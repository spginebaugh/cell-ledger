"""Analysis steps as pure functions over count matrices / AnnData plus a SampleSheet.

Every step records its parameters so a report can be reproduced exactly.
"""

from cell_ledger.analysis.annotation import load_annotation
from cell_ledger.analysis.bundle import build_anndata, load_counts
from cell_ledger.analysis.de import DeParams, run_de
from cell_ledger.analysis.enrichment import EnrichmentParams, run_prerank
from cell_ledger.analysis.filtering import filter_genes
from cell_ledger.analysis.genes import lookup_genes, score_markers
from cell_ledger.analysis.pipeline import PipelineParams, load_design, run_pipeline
from cell_ledger.analysis.qc import run_qc

__all__ = [
    "DeParams",
    "EnrichmentParams",
    "PipelineParams",
    "build_anndata",
    "filter_genes",
    "load_annotation",
    "load_counts",
    "load_design",
    "lookup_genes",
    "run_de",
    "run_pipeline",
    "run_prerank",
    "run_qc",
    "score_markers",
]
