"""NCBI gene annotation table shared by every human series (``Human.GRCh38.p13.annot.tsv.gz``)."""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

ANNOTATION_COLUMNS = [
    "Symbol",
    "Description",
    "GeneType",
    "EnsemblGeneID",
    "ChrAcc",
    "ChrStart",
    "ChrStop",
    "Orientation",
    "Length",
]
MITO_SYMBOL = re.compile(r"^MT-")
RIBO_SYMBOL = re.compile(r"^RP[SL]\d+[A-Z]?\d*$")
PROTEIN_CODING = "protein-coding"


def load_annotation(path: str | Path) -> pd.DataFrame:
    """Annotation indexed by Entrez GeneID (as str); only the columns we use are kept."""
    df = pd.read_csv(path, sep="\t", dtype=str, keep_default_na=False)
    if "GeneID" not in df.columns:
        raise ValueError(f"{path}: expected a GeneID column, got {list(df.columns)[:5]}")
    df = df.set_index("GeneID")
    df.index = df.index.astype(str)
    keep = [c for c in ANNOTATION_COLUMNS if c in df.columns]
    out = pd.DataFrame(df.loc[:, keep])
    if "Length" in out.columns:
        out["Length"] = pd.to_numeric(out["Length"], errors="coerce")
    return out


def symbol_to_gene_id(var: pd.DataFrame) -> dict[str, str]:
    """Upper-cased symbol -> GeneID; the first GeneID wins when a symbol repeats."""
    out: dict[str, str] = {}
    if "Symbol" not in var.columns:
        return out
    for gene_id, symbol in var["Symbol"].items():
        if isinstance(symbol, str) and symbol:
            out.setdefault(symbol.upper(), str(gene_id))
    return out


def _symbols(var: pd.DataFrame) -> pd.Series:
    if "Symbol" not in var.columns:
        return pd.Series("", index=var.index, dtype=str)
    return pd.Series(var["Symbol"].fillna("").astype(str).to_numpy(), index=var.index, dtype=str)


def mito_mask(var: pd.DataFrame) -> pd.Series:
    return _symbols(var).map(lambda s: bool(MITO_SYMBOL.match(s)))


def ribo_mask(var: pd.DataFrame) -> pd.Series:
    mask = _symbols(var).map(lambda s: bool(RIBO_SYMBOL.match(s)))
    if "GeneType" in var.columns:
        mask &= var["GeneType"].fillna("").astype(str) == PROTEIN_CODING
    return mask
