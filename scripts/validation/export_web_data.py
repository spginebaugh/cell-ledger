"""Write the hard-coded data behind the Evals page's pipeline-validation charts.

Reads ``docs/validation/summary.tsv`` and the per-gene merged tables in ``data/validation/``
(both written by ``compare_published.py``) and emits ``apps/web/src/lib/validation-results.ts``:
for every comparison the log2 fold change agreement over all shared genes (Spearman and R^2),
plus a deterministic sample of up to ``MAX_POINTS`` genes as (published log2FC, pipeline
log2FC) pairs for the scatter. The sample keeps the ``KEEP_EXTREMES`` genes furthest from the
origin so the tails are drawn in full, and fills the rest at random from the dense centre.

Pairs are quantised to 0.01 and packed as little-endian Int16 in base64, which keeps the
module small and formatter-proof.

    uv run python scripts/validation/export_web_data.py
    bun run biome check --write apps/web/src/lib/validation-results.ts
"""

from __future__ import annotations

import base64
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parents[2]
SUMMARY = ROOT / "docs" / "validation" / "summary.tsv"
MERGED = ROOT / "data" / "validation"
OUT = ROOT / "apps" / "web" / "src" / "lib" / "validation-results.ts"
MAX_POINTS = 2500
KEEP_EXTREMES = 1000
SEED = 20261107

DATASETS = [
    {
        "gse": "GSE52778",
        "title": "Dexamethasone in airway smooth muscle cells",
        "paper": "Himes et al. 2014, PLoS ONE",
        "pmid": "24926665",
        "design": "4 donor cell lines, dexamethasone vs untreated",
        "published": (
            "Cuffdiff 2.0.2 on FPKM, pooled 4 vs 4; the authors' table is deposited on GEO"
        ),
    },
    {
        "gse": "GSE147507",
        "title": "SARS-CoV-2 and other respiratory viruses in lung cell lines",
        "paper": "Blanco-Melo et al. 2020, Cell",
        "pmid": "32416070",
        "design": "infected vs mock within each GEO series, 3 or 4 replicates per arm",
        "published": (
            "DESeq2; Cell Tables S1 and S2 (log2FC and padj) and the bioRxiv v1 table for the "
            "MOI 0.2 A549 experiment"
        ),
    },
    {
        "gse": "GSE144269",
        "title": "Mongolian hepatocellular carcinoma, tumor vs paired non-tumor liver",
        "paper": "Candia et al. 2020, Nature Communications",
        "pmid": "32873799",
        "design": "paired tumor and non-tumor per patient, one contrast per molecular subclass",
        "published": "paired t-test on voom values per subclass, Supplementary Data 5",
    },
]

CONTRAST_TITLES = {
    "dex_vs_untreated": "dexamethasone vs untreated, paired by donor",
    "dex_vs_untreated_unpaired": "dexamethasone vs untreated, unpaired",
    "nhbe_sarscov2_vs_mock": "NHBE, SARS-CoV-2 vs mock",
    "nhbe_iav_vs_mock": "NHBE, influenza A vs mock",
    "nhbe_iavdns1_vs_mock": "NHBE, influenza A dNS1 vs mock",
    "a549_sarscov2_moi02_vs_mock": "A549, SARS-CoV-2 MOI 0.2 vs mock",
    "a549_sarscov2_moi2_vs_mock": "A549, SARS-CoV-2 MOI 2 vs mock",
    "calu3_sarscov2_vs_mock": "Calu-3, SARS-CoV-2 vs mock",
    "a549_rsv_vs_mock": "A549, RSV vs mock",
    "a549_hpiv3_vs_mock": "A549, HPIV3 vs mock",
    "tumor_vs_adjacent_mo1": "MO1 subclass",
    "tumor_vs_adjacent_mo2": "MO2 subclass",
    "tumor_vs_adjacent_mo3": "MO3 subclass",
    "tumor_vs_adjacent_mo4": "MO4 subclass",
}


def pack(values: np.ndarray) -> str:
    q = np.clip(np.round(values * 100), -32767, 32767).astype("<i2")
    return base64.b64encode(q.tobytes()).decode("ascii")


def sample_points(merged: pd.DataFrame, rng: np.random.RandomState) -> pd.DataFrame:
    """Up to MAX_POINTS genes: the KEEP_EXTREMES furthest from the origin, then a random draw
    from the rest, so the tails are complete and the centre keeps its density."""
    if len(merged) <= MAX_POINTS:
        return merged
    radius = np.maximum(merged["lfc_pub"].abs(), merged["log2fc_unshrunk"].abs())
    order = radius.sort_values(ascending=False).index
    extremes = merged.loc[order[:KEEP_EXTREMES]]
    rest = merged.loc[order[KEEP_EXTREMES:]]
    picked = rest.iloc[rng.choice(len(rest), MAX_POINTS - KEEP_EXTREMES, replace=False)]
    return pd.concat([picked, extremes])  # centre first, tails drawn on top


def ts_string(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


def main() -> int:
    summary = pd.read_csv(SUMMARY, sep="\t")
    rng = np.random.RandomState(SEED)
    comparisons = []
    for row in summary.to_dict("records"):
        path = MERGED / f"{row['dataset']}_{row['contrast']}_merged.tsv.gz"
        merged = pd.read_csv(path, sep="\t", dtype={"gene_id": str}).set_index("gene_id")
        merged = merged.dropna(subset=["lfc_pub", "log2fc_unshrunk", "pvalue"])
        values = np.abs(np.r_[merged["lfc_pub"].to_numpy(), merged["log2fc_unshrunk"].to_numpy()])
        lim = float(np.ceil(np.nanpercentile(values, 99.9) * 2) / 2)
        pts = sample_points(merged, rng)
        comparisons.append(
            {
                "gse": row["dataset"],
                "contrast": row["contrast"],
                "title": CONTRAST_TITLES[row["contrast"]],
                "published": row["published"],
                "design": row["design"],
                "n": row["n"],
                "shared": int(row["shared_tested"]),
                "spearman": round(float(row["spearman_lfc_unshrunk"]), 3),
                "r2": round(float(row["r2_lfc_unshrunk"]), 3),
                "lim": lim,
                "shown": len(pts),
                "px": pack(pts["lfc_pub"].to_numpy()),
                "ox": pack(pts["log2fc_unshrunk"].to_numpy()),
                "symbols": "|".join(str(s) for s in pts["symbol"].fillna("")),
            }
        )
    generated = datetime.now(UTC).date().isoformat()
    lines = [
        "// Generated by scripts/validation/export_web_data.py from docs/validation/summary.tsv",
        "// and data/validation/*_merged.tsv.gz (mise run validate:published). Do not edit.",
        "//",
        "// Each comparison carries a sample of its genes as log2 fold change pairs, quantised to",
        "// 0.01 and packed as little-endian Int16 in base64 (decodeLfc in lib/validation.ts):",
        "// px is the authors' value, ox the pipeline's unshrunk estimate; symbols has one gene",
        "// symbol per point. The correlations are over every gene tested on both sides, not the",
        "// sample.",
        "",
        "export interface ValidationDataset {",
        "  gse: string;",
        "  title: string;",
        "  paper: string;",
        "  pmid: string;",
        "  design: string;",
        "  published: string;",
        "}",
        "",
        "export interface ValidationComparison {",
        "  gse: string;",
        "  contrast: string;",
        "  title: string;",
        "  published: string;",
        "  design: string;",
        "  n: string;",
        "  shared: number;",
        "  spearman: number;",
        "  r2: number;",
        "  lim: number;",
        "  shown: number;",
        "  px: string;",
        "  ox: string;",
        "  symbols: string;",
        "}",
        "",
        "export interface ValidationResults {",
        "  generated: string;",
        "  maxPoints: number;",
        "  datasets: ValidationDataset[];",
        "  comparisons: ValidationComparison[];",
        "}",
        "",
        "export const VALIDATION_RESULTS: ValidationResults = {",
        f"  generated: {ts_string(generated)},",
        f"  maxPoints: {MAX_POINTS},",
        "  datasets: [",
    ]
    for d in DATASETS:
        lines.append("    {")
        lines.extend(f"      {k}: {ts_string(v)}," for k, v in d.items())
        lines.append("    },")
    lines += ["  ],", "  comparisons: ["]
    for c in comparisons:
        lines.append("    {")
        for k, v in c.items():
            if isinstance(v, str):
                lines.append(f"      {k}: {ts_string(v)},")
            elif isinstance(v, list):
                lines.append(f"      {k}: [{', '.join(ts_string(x) for x in v)}],")
            else:
                lines.append(f"      {k}: {v},")
        lines.append("    },")
    lines += ["  ],", "};", ""]
    OUT.write_text("\n".join(lines))
    size = OUT.stat().st_size
    shown = sum(c["shown"] for c in comparisons)
    print(
        f"wrote {OUT.relative_to(ROOT)}: {len(comparisons)} comparisons, {shown} points, "
        f"{size / 1024:.0f} KB"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
