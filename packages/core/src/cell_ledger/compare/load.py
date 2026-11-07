"""Read finished run directories (report.json + de_results.tsv + enrichment.tsv)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

import numpy as np
import pandas as pd

from cell_ledger.analysis.pipeline import REPORT_JSON
from cell_ledger.report.models import AnalysisReport

UNSHRUNK_LFC = "log2fc_unshrunk"
UNSHRUNK_SE = "lfc_se_unshrunk"


@dataclass
class RunData:
    run_dir: Path
    report: AnalysisReport
    de: pd.DataFrame | None
    enrichment: pd.DataFrame | None

    @property
    def label(self) -> str:
        return f"{self.report.gse}:{self.report.contrast.name}"

    @property
    def gsms_fitted(self) -> set[str]:
        """GSMs that contributed to the DE fit (after dropping unpaired samples)."""
        de = self.report.de.summary if self.report.de else None
        if de and de.gsms_fitted:
            return set(de.gsms_fitted)
        rec = self.report.reconciliation
        used = set(rec.gsms_used) if rec else set(self.report.contrast.gsms)
        return used - set(de.dropped_unpaired) if de else used

    @property
    def n_fitted(self) -> int:
        """Observations in the fit (collapsed units count once)."""
        de = self.report.de.summary if self.report.de else None
        return (de.n_case_used + de.n_control_used) if de else len(self.gsms_fitted)

    @property
    def unshrunk_se_source(self) -> Literal["stored", "reconstructed"]:
        return (
            "stored" if self.de is not None and UNSHRUNK_SE in self.de.columns else "reconstructed"
        )

    def effect_table(self) -> pd.DataFrame | None:
        """Per-gene inputs for synthesis: unshrunk log2FC and SE, Wald stat, padj, symbol.

        Runs written before ``lfc_se_unshrunk`` existed get the SE reconstructed exactly
        from the unshrunk estimate and the Wald statistic (``stat = lfc / se``); the
        shrunk SE is never paired with the unshrunk estimate.
        """
        if self.de is None:
            return None
        df = self.de
        lfc = cast(
            pd.Series,
            pd.to_numeric(df[UNSHRUNK_LFC] if UNSHRUNK_LFC in df.columns else df["log2fc"]),
        )
        stat = cast(pd.Series, pd.to_numeric(df["stat"], errors="coerce"))
        if UNSHRUNK_SE in df.columns:
            se = cast(pd.Series, pd.to_numeric(df[UNSHRUNK_SE], errors="coerce"))
        else:
            lfc_a = lfc.to_numpy(dtype=float)
            stat_a = stat.to_numpy(dtype=float)
            with np.errstate(divide="ignore", invalid="ignore"):
                ratio = np.abs(lfc_a / stat_a)
            se = pd.Series(np.where(stat_a != 0, ratio, np.nan), index=df.index)
        out = pd.DataFrame(
            {
                "lfc": lfc,
                "se": se,
                "stat": stat,
                "padj": pd.to_numeric(df["padj"], errors="coerce"),
                "pvalue": pd.to_numeric(df["pvalue"], errors="coerce"),
                "symbol": df["symbol"].fillna("").astype(str),
            },
            index=df.index.astype(str),
        )
        # a gene contributes when DESeq2 produced an estimate with a finite, positive SE
        ok = out["pvalue"].notna() & out["lfc"].notna() & out["se"].notna() & (out["se"] > 0)
        return out.loc[ok]


def load_run(run_dir: str | Path) -> RunData:
    d = Path(run_dir)
    report = AnalysisReport.model_validate_json((d / REPORT_JSON).read_text())
    de = None
    de_file = report.files.get("de_results")
    if de_file and (d / de_file).exists():
        de = pd.read_csv(d / de_file, sep="\t", index_col=0, dtype={"symbol": str})
        de.index = de.index.astype(str)
    enr = None
    enr_file = report.files.get("enrichment")
    if enr_file and (d / enr_file).exists():
        enr = pd.read_csv(d / enr_file, sep="\t")
    return RunData(run_dir=d, report=report, de=de, enrichment=enr)
