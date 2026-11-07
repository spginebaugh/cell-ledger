"""Pathway-level concordance: NES per term across members (already normalised, so no model).

Only enrichment tables computed against the same gene-set library (same name and
checksum) are merged; the rest are listed as left out.
"""

from __future__ import annotations

from collections import Counter
from typing import cast

import numpy as np
import pandas as pd

from cell_ledger.compare.load import RunData
from cell_ledger.compare.models import PathwayMeta, PathwaySynthesis

TERM, NES, FDR = "Term", "NES", "FDR q-val"


def _signature(r: RunData) -> tuple[str, str | None] | None:
    e = r.report.enrichment
    if e is None or r.enrichment is None or not {TERM, NES, FDR} <= set(r.enrichment.columns):
        return None
    return e.library, cast(str | None, e.params.get("gene_sets_md5"))


def nes_matrices(runs: list[RunData]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """terms x members frames of NES and FDR; members without enrichment are left out."""
    nes: dict[str, pd.Series] = {}
    fdr: dict[str, pd.Series] = {}
    for r in runs:
        e = r.enrichment
        if e is None or not {TERM, NES, FDR} <= set(e.columns):
            continue
        t = e.drop_duplicates(TERM).set_index(TERM)
        nes[r.label] = cast(pd.Series, pd.to_numeric(cast(pd.Series, t[NES]), errors="coerce"))
        fdr[r.label] = cast(pd.Series, pd.to_numeric(cast(pd.Series, t[FDR]), errors="coerce"))
    return pd.DataFrame(nes), pd.DataFrame(fdr)


def synthesize_pathways(
    runs: list[RunData], *, fdr_threshold: float = 0.25
) -> PathwaySynthesis | None:
    signatures = {r.label: _signature(r) for r in runs}
    present = {lab: s for lab, s in signatures.items() if s is not None}
    if not present:
        return None
    majority, _ = Counter(present.values()).most_common(1)[0]
    library, md5 = majority
    left_out: dict[str, str] = {}
    members: list[RunData] = []
    for r in runs:
        s = signatures[r.label]
        if s is None:
            left_out[r.label] = "no enrichment table"
        elif s != majority:
            left_out[r.label] = (
                f"enrichment used {s[0]} (md5 {s[1] or 'unrecorded'}), not {library} "
                f"(md5 {md5 or 'unrecorded'})"
            )
        else:
            members.append(r)
    nes, fdr = nes_matrices(members)
    rows: list[PathwayMeta] = []
    for term in nes.index:
        row = nes.loc[term]
        present_row = row.notna()
        n = int(present_row.sum())
        if n == 0:
            continue
        n_pos = int((row > 0).sum())
        n_neg = int((row < 0).sum())
        f = fdr.loc[term].reindex(nes.columns)
        rows.append(
            PathwayMeta(
                term=str(term),
                n_members=n,
                mean_nes=float(row.mean(skipna=True)),
                n_pos=n_pos,
                n_neg=n_neg,
                n_sig_fdr=int(((f < fdr_threshold) & present_row).sum()),
                consistency=max(n_pos, n_neg) / n,
                nes={str(c): float(v) for c, v in row.items() if not np.isnan(v)},
                fdr={str(c): float(v) for c, v in f.items() if not np.isnan(v)},
            )
        )
    rows.sort(key=lambda p: (-p.consistency, -p.n_sig_fdr, -abs(p.mean_nes)))
    return PathwaySynthesis(
        library=library,
        gene_sets_md5=md5,
        members=[r.label for r in members],
        left_out=left_out,
        fdr_threshold=fdr_threshold,
        n_terms=len(rows),
        n_consistent=sum(p.consistency == 1.0 and p.n_members >= 2 for p in rows),
        terms=rows,
    )
