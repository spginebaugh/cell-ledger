"""Compare cell-ledger DE output with the differential expression the authors published.

For every (dataset, contrast) pair in ``plan()`` the pipeline's ``de_results.tsv`` (in
``data/runs/<GSE>/<contrast>/``) is joined to the published table on NCBI GeneID: Ensembl
ids go through the NCBI annotation table, gene symbols through current symbols and then
synonyms. Over the genes tested on both sides it reports rank correlation of log2 fold
changes (and of Wald statistics where the authors published them), overlap of the
significant sets at padj < 0.05, how many of the authors' significant genes the pipeline
recovers and in the same direction, and top-N overlap.

    uv run python scripts/validation/compare_published.py

Writes ``docs/validation/summary.tsv``, ``summary.md`` and ``figures/<GSE>_<contrast>.png``;
the per-gene merged tables go to ``data/validation/``.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np
import openpyxl
import pandas as pd
from scipy.stats import pearsonr, spearmanr

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).parents[2]
RUNS = ROOT / "data" / "runs"
PUBLISHED = ROOT / "data" / "published"
ANNOTATION = ROOT / "data" / "geo" / "annotation" / "Human.GRCh38.p13.annot.tsv.gz"
DOCS = ROOT / "docs" / "validation"
MERGED = ROOT / "data" / "validation"
ALPHA = 0.05

SUMMARY_COLUMNS = [
    "dataset",
    "contrast",
    "published",
    "design",
    "n",
    "shared_tested",
    "spearman_lfc_unshrunk",
    "r2_lfc_unshrunk",
    "spearman_lfc_shrunk",
    "spearman_stat",
    "sig_ours",
    "sig_pub",
    "sig_both",
    "jaccard",
    "recall_of_pub",
    "precision_vs_pub",
    "dir_agree_pub_sig",
    "opposite_both_sig",
    "top100_overlap",
    "top500_overlap",
    "jaccard_lfc1",
]


class GeneMapper:
    """Published gene identifiers -> NCBI GeneID, through the annotation table the runs use."""

    def __init__(self, annotation: Path) -> None:
        cols = ["GeneID", "Symbol", "Synonyms", "EnsemblGeneID"]
        a = pd.read_csv(annotation, sep="\t", usecols=cols, dtype=str)
        ens = a.dropna(subset=["EnsemblGeneID"]).drop_duplicates("EnsemblGeneID")
        self.ens2gid: pd.Series = ens.set_index("EnsemblGeneID")["GeneID"]
        self.sym2gid: pd.Series = a.drop_duplicates("Symbol").set_index("Symbol")["GeneID"]
        syn = a.dropna(subset=["Synonyms"]).assign(syn=lambda d: d["Synonyms"].str.split("|"))
        syn = syn.explode("syn")
        syn = syn[~syn["syn"].isin(set(self.sym2gid.index))].drop_duplicates(subset=["syn"])
        self.syn2gid: pd.Series = syn.set_index("syn")["GeneID"]

    def symbols(self, symbols: pd.Series) -> tuple[pd.Series, dict[str, int]]:
        gid = symbols.map(self.sym2gid)
        missing = gid.isna()
        gid[missing] = symbols[missing].map(self.syn2gid)
        return gid, {
            "n_input": len(symbols),
            "mapped_symbol": int((~missing).sum()),
            "mapped_synonym": int((missing & gid.notna()).sum()),
            "unmapped": int(gid.isna().sum()),
        }

    def ensembl(
        self, ensembl: pd.Series, symbols: pd.Series | None = None
    ) -> tuple[pd.Series, dict[str, int]]:
        gid = ensembl.str.replace(r"\.\d+$", "", regex=True).map(self.ens2gid)
        info = {"n_input": len(ensembl), "mapped_ensembl": int(gid.notna().sum())}
        if symbols is not None:
            missing = gid.isna()
            gid[missing] = symbols[missing].map(self.sym2gid)
            info["mapped_symbol_fallback"] = int((missing & gid.notna()).sum())
        info["unmapped"] = int(gid.isna().sum())
        return gid, info


def by_gene_id(pub: pd.DataFrame, gid: pd.Series) -> pd.DataFrame:
    """Index a published table by GeneID; unmapped rows go, duplicates keep the most significant."""
    pub = pub.assign(gene_id=gid.to_numpy()).dropna(subset=["gene_id"])
    pub = pub.sort_values("padj_pub", na_position="last").drop_duplicates("gene_id")
    return pub.set_index("gene_id")


@dataclass
class Published:
    label: str
    method: str
    table: pd.DataFrame  # GeneID index; lfc_pub, padj_pub, optional pvalue_pub / stat_pub
    mapping: dict[str, int]
    note: str = ""


def load_run(gse: str, contrast: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    run = RUNS / gse / contrast
    de = pd.read_csv(run / "de_results.tsv", sep="\t", dtype={"gene_id": str})
    report = json.loads((run / "report.json").read_text())
    summary = report["de"]["summary"]
    qc = report.get("qc") or {}
    meta = {
        "status": report["status"],
        "design": summary["design"],
        "n": f"{summary['n_case_used']} vs {summary['n_control_used']}",
        "qualifications": "; ".join(report.get("qualifications") or []),
        "dataset_flags": ",".join(qc.get("flags") or []),
        "flagged_samples": sum(1 for s in qc.get("samples") or [] if s.get("flags")),
    }
    return de.set_index("gene_id"), meta


def top_n(frame: pd.DataFrame, n: int, padj: str, tiebreak: str, *, by_effect: bool) -> set[str]:
    f = frame[[padj, tiebreak]].copy()
    if by_effect:  # larger |effect| first among equal padj
        f[tiebreak] = -f[tiebreak].abs()
    return set(f.sort_values([padj, tiebreak]).head(n).index)


def compare(gse: str, contrast: str, pub: Published) -> dict[str, Any]:
    mine, meta = load_run(gse, contrast)
    both = mine.join(pub.table, how="inner").dropna(subset=["pvalue", "lfc_pub"]).copy()
    if len(both) < 100:
        raise SystemExit(f"{gse} {contrast}: only {len(both)} genes shared with {pub.label}")
    sig_o = both["padj"] < ALPHA
    sig_p = both["padj_pub"] < ALPHA
    same = np.sign(both["log2fc_unshrunk"]) == np.sign(both["lfc_pub"])
    strong_o = sig_o & (both["log2fc_unshrunk"].abs() > 1)
    strong_p = sig_p & (both["lfc_pub"].abs() > 1)
    has_pvalue = "pvalue_pub" in both and both["pvalue_pub"].notna().any()
    has_stat = "stat_pub" in both and both["stat_pub"].notna().sum() > 100
    row: dict[str, Any] = {
        "dataset": gse,
        "contrast": contrast,
        "published": pub.label,
        "pub_method": pub.method,
        "design": meta["design"],
        "n": meta["n"],
        "ours_tested": int(mine["pvalue"].notna().sum()),
        "pub_rows": len(pub.table),
        "shared_tested": len(both),
        "spearman_lfc_unshrunk": spearmanr(both["log2fc_unshrunk"], both["lfc_pub"]).statistic,
        "pearson_lfc_unshrunk": pearsonr(both["log2fc_unshrunk"], both["lfc_pub"]).statistic,
        "r2_lfc_unshrunk": pearsonr(both["log2fc_unshrunk"], both["lfc_pub"]).statistic ** 2,
        "spearman_lfc_shrunk": spearmanr(both["log2fc"], both["lfc_pub"]).statistic,
        "spearman_stat": (
            spearmanr(both["stat"], both["stat_pub"], nan_policy="omit").statistic
            if has_stat
            else np.nan
        ),
        "sig_ours": int(sig_o.sum()),
        "sig_pub": int(sig_p.sum()),
        "sig_both": int((sig_o & sig_p).sum()),
        "jaccard": (sig_o & sig_p).sum() / max((sig_o | sig_p).sum(), 1),
        "recall_of_pub": (sig_o & sig_p).sum() / max(sig_p.sum(), 1),
        "precision_vs_pub": (sig_o & sig_p).sum() / max(sig_o.sum(), 1),
        "dir_agree_pub_sig": same[sig_p].mean() if sig_p.any() else np.nan,
        "dir_agree_both_sig": same[sig_o & sig_p].mean() if (sig_o & sig_p).any() else np.nan,
        "opposite_both_sig": int((sig_o & sig_p & ~same).sum()),
        "sig_lfc1_ours": int(strong_o.sum()),
        "sig_lfc1_pub": int(strong_p.sum()),
        "sig_lfc1_both": int((strong_o & strong_p).sum()),
        "jaccard_lfc1": (strong_o & strong_p).sum() / max((strong_o | strong_p).sum(), 1),
    }
    for n in (100, 500):
        ours = top_n(both, n, "padj", "pvalue", by_effect=False)
        if has_pvalue:
            theirs = top_n(both, n, "padj_pub", "pvalue_pub", by_effect=False)
        else:
            theirs = top_n(both, n, "padj_pub", "lfc_pub", by_effect=True)
        row[f"top{n}_overlap"] = len(ours & theirs)
    row.update(
        qualifications=meta["qualifications"],
        dataset_flags=meta["dataset_flags"],
        flagged_samples=meta["flagged_samples"],
        mapping=json.dumps(pub.mapping),
        note=pub.note,
    )
    draw(gse, contrast, pub, both, row)
    MERGED.mkdir(parents=True, exist_ok=True)
    both.to_csv(MERGED / f"{gse}_{contrast}_merged.tsv.gz", sep="\t")
    print(
        f"{gse} {contrast}: shared={len(both)} rho={row['spearman_lfc_unshrunk']:.3f} "
        f"r2={row['r2_lfc_unshrunk']:.3f} "
        f"sig ours={row['sig_ours']} pub={row['sig_pub']} both={row['sig_both']} "
        f"recall={row['recall_of_pub']:.3f} precision={row['precision_vs_pub']:.3f} "
        f"direction={row['dir_agree_pub_sig']:.3f}"
    )
    return row


def draw(gse: str, contrast: str, pub: Published, both: pd.DataFrame, row: dict[str, Any]) -> None:
    """Pipeline log2FC against the authors' for every shared gene, one colour, with R^2."""
    fig, ax = plt.subplots(figsize=(5, 5))
    ax.scatter(
        both["lfc_pub"], both["log2fc_unshrunk"], s=4, alpha=0.4, c="#2b6fc8", rasterized=True
    )
    values = np.abs(np.r_[both["lfc_pub"].to_numpy(), both["log2fc_unshrunk"].to_numpy()])
    lim = float(np.nanpercentile(values, 99.9))
    ax.plot([-lim, lim], [-lim, lim], "k--", lw=0.8)
    ax.axhline(0, c="k", lw=0.3)
    ax.axvline(0, c="k", lw=0.3)
    ax.set_xlim(-lim, lim)
    ax.set_ylim(-lim, lim)
    ax.set_xlabel(f"published log2FC ({pub.method})")
    ax.set_ylabel("cell-ledger log2FC (unshrunk)")
    ax.set_title(
        f"{gse} {contrast}\nR² {row['r2_lfc_unshrunk']:.2f}, Spearman "
        f"{row['spearman_lfc_unshrunk']:.2f}, n={len(both):,}",
        fontsize=9,
    )
    fig.tight_layout()
    (DOCS / "figures").mkdir(parents=True, exist_ok=True)
    fig.savefig(DOCS / "figures" / f"{gse}_{contrast}.png", dpi=110)
    plt.close(fig)


# ------------------------------------------------------------------- published tables


def sheet_frame(
    path: Path, sheet: str | int = 1, header_row: int = 0, first_col: int = 0
) -> pd.DataFrame:
    wb = openpyxl.load_workbook(path, read_only=True)
    ws = wb[sheet] if isinstance(sheet, str) else wb.worksheets[sheet]
    rows = list(ws.iter_rows(values_only=True))
    header = [str(h) for h in rows[header_row][first_col:] if h is not None]
    width = len(header)
    body = [r[first_col : first_col + width] for r in rows[header_row + 1 :] if r[first_col]]
    return pd.DataFrame(body, columns=header)


def numeric(s: pd.Series) -> np.ndarray:
    return pd.to_numeric(s, errors="coerce").to_numpy()


def himes_2014(m: GeneMapper) -> Published:
    """GSE52778: the Cuffdiff gene_exp.diff the authors deposited on GEO (Dex vs Untreated)."""
    path = PUBLISHED / "GSE52778" / "GSE52778_Dex_vs_Untreated_gene_exp.diff.gz"
    p = pd.read_csv(path, sep="\t")
    if not ((p["sample_1"] == "Dex").all() and (p["sample_2"] == "Untreated").all()):
        raise SystemExit("GSE52778: unexpected sample order in gene_exp.diff")
    p = p[p["status"] == "OK"]
    # Cuffdiff reports log2(value_2 / value_1) = log2(Untreated / Dex); flip to Dex over
    # Untreated so a positive value means higher after dexamethasone, like the case arm.
    with np.errstate(divide="ignore"):  # an FPKM of 0 gives an infinite ratio, dropped below
        lfc = np.log2(p["value_1"].to_numpy() / p["value_2"].to_numpy())
    table = pd.DataFrame(
        {
            "lfc_pub": lfc,
            "padj_pub": p["q_value"].to_numpy(),
            "pvalue_pub": p["p_value"].to_numpy(),
            "stat_pub": -p["test_stat"].to_numpy(),
        },
        index=p["gene"].to_numpy(),
    ).replace([np.inf, -np.inf], np.nan)
    gid, info = m.symbols(pd.Series(table.index, index=table.index))
    return Published(
        "Himes 2014 GEO suppl gene_exp.diff (Cuffdiff 2.0.2, pooled 4 vs 4)",
        "Cuffdiff FPKM",
        by_gene_id(table, gid),
        info,
        "Cuffdiff's test statistic is not a Wald z; only its sign and rank are comparable.",
    )


@dataclass(frozen=True)
class CellColumns:
    """One comparison in Blanco-Melo 2020 Cell Table S1 (mmc1) or S2 (mmc2)."""

    contrast: str
    file: str
    sheet: str
    lfc: str
    padj: str
    label: str


CELL_TABLES = [
    CellColumns(
        "nhbe_sarscov2_vs_mock",
        "mmc2.xlsx",
        "DESeq2_NHBECells",
        "SARS-CoV-2_L2FC",
        "padj_SARS-CoV-2",
        "Cell Table S2 NHBE SARS-CoV-2",
    ),
    CellColumns(
        "nhbe_iav_vs_mock",
        "mmc2.xlsx",
        "DESeq2_NHBECells",
        "IAV_L2FC",
        "padj_IAV",
        "Cell Table S2 NHBE IAV",
    ),
    CellColumns(
        "nhbe_iavdns1_vs_mock",
        "mmc2.xlsx",
        "DESeq2_NHBECells",
        "IAVDNS1_L2FC",
        "padj_IAVDNS1",
        "Cell Table S2 NHBE IAVdNS1",
    ),
    CellColumns(
        "a549_sarscov2_moi2_vs_mock",
        "mmc1.xlsx",
        "DESeq2_Results",
        "SARS-CoV-2(A549)_L2FC",
        "padj_SARS-CoV-2(A549)",
        "Cell Table S1 A549 SARS-CoV-2 MOI 2",
    ),
    CellColumns(
        "calu3_sarscov2_vs_mock",
        "mmc1.xlsx",
        "DESeq2_Results",
        "SARS-CoV-2(Calu-3)_L2FC",
        "padj_SARS-CoV-2(Calu-3)",
        "Cell Table S1 Calu-3 SARS-CoV-2",
    ),
    CellColumns(
        "a549_rsv_vs_mock",
        "mmc1.xlsx",
        "DESeq2_Results",
        "RSV_L2FC",
        "padj_RSV",
        "Cell Table S1 A549 RSV",
    ),
    CellColumns(
        "a549_hpiv3_vs_mock",
        "mmc1.xlsx",
        "DESeq2_Results",
        "HPIV3_L2FC",
        "padj_HPIV3",
        "Cell Table S1 A549 HPIV3",
    ),
]


def blanco_melo_cell(m: GeneMapper, c: CellColumns) -> Published:
    """GSE147507: one comparison (log2FC + padj columns) from Cell Table S1 or S2.

    The tables fill genes that were not tested in a comparison with log2FC 0 and padj 0
    (or 1); exact zeros in either column are treated as untested.
    """
    df = sheet_frame(PUBLISHED / "GSE147507" / "europepmc" / c.file, c.sheet)
    table = pd.DataFrame(
        {"lfc_pub": numeric(df[c.lfc]), "padj_pub": numeric(df[c.padj])},
        index=df["GeneName"].astype(str),
    )
    zero = (table["lfc_pub"] == 0) | (table["padj_pub"] == 0)
    table.loc[zero, ["lfc_pub", "padj_pub"]] = np.nan
    gid, info = m.symbols(pd.Series(table.index, index=table.index))
    info["zero_filled_dropped"] = int(zero.sum())
    return Published(
        c.label,
        "DESeq2 (authors)",
        by_gene_id(table, gid),
        info,
        "Cell tables give log2FC and padj only; exact-zero fill values treated as untested.",
    )


def blanco_melo_biorxiv(m: GeneMapper) -> Published:
    """GSE147507 Series2: full DESeq2 output for A549 SARS-CoV-2 from the bioRxiv v1 tables."""
    df = sheet_frame(PUBLISHED / "GSE147507" / "biorxiv_media-2.xlsx", "DESeq2-CoV (A549)")
    df = df[df["status"] == "OK"]
    table = pd.DataFrame(
        {
            "lfc_pub": numeric(df["log2FoldChange"]),
            "padj_pub": numeric(df["padj"]),
            "pvalue_pub": numeric(df["pvalue"]),
            "stat_pub": numeric(df["stat"]),
        },
        index=df["GeneName"].astype(str),
    )
    gid, info = m.symbols(pd.Series(table.index, index=table.index))
    return Published(
        "Blanco-Melo bioRxiv v1 Supp Table 2 A549 SARS-CoV-2 (full DESeq2 output)",
        "DESeq2 (authors)",
        by_gene_id(table, gid),
        info,
        "The preprint table is the only author table with full DESeq2 output for Series2.",
    )


def candia_2020(m: GeneMapper, subclass: str) -> Published:
    """GSE144269: Supplementary Data 5, tumor vs non-tumor per molecular subclass."""
    path = PUBLISHED / "GSE144269" / "europepmc" / "41467_2020_18186_MOESM7_ESM.xlsx"
    df = sheet_frame(path, 0, header_row=1, first_col=1)
    table = pd.DataFrame(
        {
            "lfc_pub": numeric(df[f"{subclass}_FC"]),
            "pvalue_pub": numeric(df[f"{subclass}_p"]),
            "padj_pub": numeric(df[f"{subclass}_p.FDR"]),
        },
        index=df["Ensembl"].astype(str),
    )
    symbols = pd.Series(df["HUGO"].astype(str).to_numpy(), index=table.index)
    gid, info = m.ensembl(pd.Series(table.index, index=table.index), symbols)
    return Published(
        f"Candia 2020 Supplementary Data 5, {subclass} subclass (paired t-test on voom values)",
        "authors (log2 FC, FDR)",
        by_gene_id(table, gid),
        info,
        "Published per molecular subclass; the contrast uses the same patients, paired.",
    )


def plan(m: GeneMapper) -> list[tuple[str, str, Published]]:
    himes = himes_2014(m)
    out: list[tuple[str, str, Published]] = [
        ("GSE52778", "dex_vs_untreated", himes),
        ("GSE52778", "dex_vs_untreated_unpaired", himes),
    ]
    out += [("GSE147507", c.contrast, blanco_melo_cell(m, c)) for c in CELL_TABLES]
    out.append(("GSE147507", "a549_sarscov2_moi02_vs_mock", blanco_melo_biorxiv(m)))
    for mo in ("MO1", "MO2", "MO3", "MO4"):
        out.append(("GSE144269", f"tumor_vs_adjacent_{mo.lower()}", candia_2020(m, mo)))
    return out


def markdown_table(summary: pd.DataFrame, columns: list[str]) -> str:
    lines = ["| " + " | ".join(columns) + " |", "|" + "|".join(["---"] * len(columns)) + "|"]
    for _, r in summary.iterrows():
        cells = []
        for c in columns:
            v = r[c]
            if isinstance(v, float):
                cells.append("" if np.isnan(v) else f"{v:.3f}")
            else:
                cells.append(str(v))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def main() -> int:
    mapper = GeneMapper(ANNOTATION)
    rows = []
    for gse, contrast, pub in plan(mapper):
        if not (RUNS / gse / contrast / "de_results.tsv").exists():
            print(f"{gse} {contrast}: no run in {RUNS / gse / contrast}, skipped", file=sys.stderr)
            continue
        rows.append(compare(gse, contrast, pub))
    summary = pd.DataFrame(rows)
    DOCS.mkdir(parents=True, exist_ok=True)
    summary.to_csv(DOCS / "summary.tsv", sep="\t", index=False, float_format="%.4f")
    (DOCS / "summary.md").write_text(markdown_table(summary, SUMMARY_COLUMNS))
    print(f"wrote {DOCS / 'summary.tsv'} ({len(summary)} comparisons)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
