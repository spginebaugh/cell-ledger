"""Render an AnalysisReport as Markdown. Every number comes from the report object."""

from __future__ import annotations

from cell_ledger.report.models import AnalysisReport, GeneRow


def _fmt(v: float | None, nd: int = 2) -> str:
    if v is None:
        return "n/a"
    return f"{v:.{nd}e}" if abs(v) < 1e-3 and v != 0 else f"{v:.{nd}f}"


def _gene_table(rows: list[GeneRow]) -> list[str]:
    out = ["| gene | symbol | log2FC | padj | baseMean |", "| --- | --- | --- | --- | --- |"]
    out += [
        f"| {r.gene_id} | {r.symbol or ''} | {r.log2fc:+.2f} | {_fmt(r.padj)} | {r.base_mean:.0f} |"
        for r in rows
    ]
    return out


def render_markdown(report: AnalysisReport) -> str:
    c = report.contrast
    lines = [
        f"# {report.gse}: {c.case_label} vs {c.control_label}",
        "",
        f"Status: **{report.status}**. Contrast `{c.name}` ({c.status}), "
        f"{len(c.case_gsms)} case / {len(c.control_gsms)} control GSMs proposed.",
        f"Generated {report.created_at:%Y-%m-%d %H:%M} UTC with pydeseq2 "
        f"{report.versions.get('pydeseq2', '?')}.",
        "",
    ]
    if c.rationale:
        lines += [f"> {c.rationale}", ""]
    if report.error:
        lines += [f"**The pipeline stopped on an error:** `{report.error}`", ""]
    if report.blockers:
        lines += ["## Blockers", ""] + [f"- {b}" for b in report.blockers] + [""]
    if report.qualifications:
        lines += ["## Read with caution", ""] + [f"- {q}" for q in report.qualifications] + [""]

    if report.reconciliation:
        r = report.reconciliation
        lines += [
            "## Samples",
            "",
            f"- {r.n_case} case and {r.n_control} control samples used "
            f"({r.n_counts_columns} columns in the counts file, "
            f"{r.n_sheet_gsms} GSMs in the sheet).",
        ]
        if r.contrast_gsms_missing_from_counts:
            lines.append(
                f"- Contrast GSMs with no counts column (NCBI did not quantify them): "
                f"{', '.join(r.contrast_gsms_missing_from_counts)}"
            )
        if r.columns_not_in_sheet:
            lines.append(
                f"- Counts columns absent from the sheet: {', '.join(r.columns_not_in_sheet)}"
            )
        lines.append("")

    if report.qc:
        q = report.qc
        lines += ["## QC", "", f"- Median library size: {q.median_library_size / 1e6:.1f}M"]
        if q.pca and q.pca.arm_r2_pc1 is not None:
            lines.append(f"- Share of PC1 variance explained by arm: {q.pca.arm_r2_pc1:.2f}")
        if q.flags:
            lines.append(f"- Dataset flags: {', '.join(q.flags)}")
        flagged = [s for s in q.samples if s.flags]
        if flagged:
            lines += ["", "| GSM | arm | library | flags |", "| --- | --- | --- | --- |"]
            lines += [
                f"| {s.gsm} | {s.arm} | {s.library_size / 1e6:.1f}M | {', '.join(s.flags)} |"
                for s in flagged
            ]
        else:
            lines.append("- No per-sample flags.")
        lines.append("")

    if report.filtering:
        f = report.filtering
        lines += [
            "## Gene filter",
            "",
            f"{f.n_genes_after} of {f.n_genes_before} genes kept "
            f"(>= {f.min_count} counts in >= {f.min_samples} samples).",
            "",
        ]

    if report.de:
        s = report.de.summary
        lines += [
            "## Differential expression",
            "",
            f"Design `{s.design}`, coefficient `{s.coefficient}`, "
            f"{'shrunk' if s.lfc_shrunk else 'unshrunk'} log2FC, alpha {s.alpha}. "
            f"Pairing: {s.pairing}"
            + (f" by `{s.blocking}`" if s.blocking else "")
            + f"; {s.n_case_used} case vs {s.n_control_used} control samples fitted"
            + (f", {len(s.dropped_unpaired)} unpaired dropped" if s.dropped_unpaired else "")
            + ".",
            f"{s.n_genes_tested} genes tested, {s.n_sig} significant: {s.n_up} higher in case "
            f"({s.n_up_lfc} with |log2FC| >= {s.lfc_threshold}), {s.n_down} higher in control "
            f"({s.n_down_lfc}).",
            "",
            "### Top genes higher in case",
            "",
            *_gene_table(report.de.top_up[:15]),
            "",
            "### Top genes higher in control",
            "",
            *_gene_table(report.de.top_down[:15]),
            "",
        ]

    if report.enrichment:
        e = report.enrichment
        lines += [
            "## Enrichment",
            "",
            f"GSEA preranked on the Wald statistic, {e.library}: {e.n_sig_fdr} of {e.n_terms} "
            f"terms at FDR < {e.fdr_threshold}.",
            "",
            "| term | NES | FDR | leading genes |",
            "| --- | --- | --- | --- |",
        ]
        lines += [
            f"| {t.term} | {t.nes:+.2f} | {t.fdr:.3f} | {', '.join(t.lead_genes[:6])} |"
            for t in e.top[:15]
        ]
        lines.append("")

    if report.gene_lookup:
        lines += [
            "## Genes of interest",
            "",
            "| query | symbol | verdict | log2FC | padj | mean case | mean control |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        for g in report.gene_lookup:
            verdict = g.verdict + (f" ({g.reason})" if g.reason else "")
            lines.append(
                f"| {g.query} | {g.symbol or ''} | {verdict} | "
                f"{'' if g.log2fc is None else f'{g.log2fc:+.2f}'} | {_fmt(g.padj)} | "
                f"{'' if g.mean_norm_case is None else f'{g.mean_norm_case:.0f}'} | "
                f"{'' if g.mean_norm_control is None else f'{g.mean_norm_control:.0f}'} |"
            )
        lines.append("")

    if report.markers:
        m = report.markers
        lines += [
            "## Expected markers",
            "",
            f"{m.n_recovered_sig} of {m.n_expected} expected markers significant "
            f"with the right sign; "
            f"{m.n_in_top_n} in the top {m.top_n} by padj.",
            "",
            "| symbol | expected | verdict | log2FC | rank |",
            "| --- | --- | --- | --- | --- |",
        ]
        for r in m.results:
            lfc = "" if r.lookup.log2fc is None else f"{r.lookup.log2fc:+.2f}"
            lines.append(
                f"| {r.expected.symbol} | {r.expected.direction} | {r.lookup.verdict} | {lfc} | "
                f"{r.lookup.rank_by_padj or ''} |"
            )
        lines.append("")

    if report.warnings:
        lines += ["## Warnings", ""] + [f"- {w}" for w in report.warnings] + [""]

    lines += ["## Steps", "", "| step | seconds | warnings |", "| --- | --- | --- |"]
    lines += [f"| {s.name} | {s.seconds:.1f} | {len(s.warnings)} |" for s in report.steps]
    lines.append("")
    if report.files:
        lines += ["## Files", ""] + [f"- `{k}`: {v}" for k, v in report.files.items()] + [""]
    if report.figures:
        lines += ["## Figures", ""] + [f"![{k}]({v})" for k, v in report.figures.items()] + [""]
    return "\n".join(lines)
