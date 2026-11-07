"""Render a ComparisonReport as Markdown. Every number comes from the report object."""

from __future__ import annotations

from cell_ledger.compare.models import ComparisonReport, GeneMeta, GeneSynthesis


def _fmt(v: float | None, nd: int = 2) -> str:
    if v is None:
        return "n/a"
    return f"{v:.{nd}e}" if abs(v) < 1e-3 and v != 0 else f"{v:.{nd}f}"


def _pct(v: float) -> str:
    return f"{v * 100:.0f}%"


def _rep(g: GeneMeta) -> str:
    return f"{round(g.replication * g.n_tested)}/{g.n_tested}"


def _gene_rows(rows: list[GeneMeta]) -> list[str]:
    out = [
        "| gene | symbol | pooled log2FC [95% CI] | padj | replicated | sign agreement | I² |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for g in rows:
        out.append(
            f"| {g.gene_id} | {g.symbol or ''} | "
            f"{_fmt(g.pooled_log2fc)} [{_fmt(g.ci_low)}, {_fmt(g.ci_high)}] | {_fmt(g.padj)} | "
            f"{_rep(g)} | {g.n_agree_pooled}/{g.n_tested} | {_fmt(g.i2)} |"
        )
    return out


def _robust_definition(s: GeneSynthesis) -> str:
    return (
        f"pooled padj < {s.alpha:g}, sign matching the pooled direction in >= "
        f"{_pct(s.sign_consistency)} of the datasets that tested the gene, significant in that "
        f"direction in >= {_pct(s.min_replication)} of them, tested in >= {s.min_studies}"
    )


def render_markdown(r: ComparisonReport) -> str:
    interval = r.params.get("interval", "hksj")
    pooled_n = sum(m.pooled for m in r.members)
    lines = [
        f"# {r.question}",
        "",
        f"Comparison `{r.name}`: {r.case_label} vs {r.control_label}. Status: **{r.status}**. "
        f"{len(r.members)} datasets in the ledger, {pooled_n} pooled by default, "
        f"{len(r.excluded)} excluded. Generated {r.created_at:%Y-%m-%d %H:%M} UTC.",
        "",
        "Each dataset keeps its own DESeq2 fit. Pooled effects are DerSimonian-Laird "
        "random-effects estimates of the unshrunk per-dataset log2FC"
        + (
            " with Hartung-Knapp-Sidik-Jonkman t intervals"
            if interval == "hksj"
            else " with normal-approximation intervals"
        )
        + "; samples are never merged.",
        "",
    ]
    if r.error:
        lines += [f"**The comparison stopped on an error:** `{r.error}`", ""]

    if r.questions:
        lines += ["## Questions for the user", ""] + [f"- {q}" for q in r.questions] + [""]

    if r.members:
        lines += [
            "## Datasets",
            "",
            "| dataset | contrast | stratum | tier | pooled | flags | case / control | design | "
            "median library | genes tested | significant | mean concordance | weight | QC flags |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for m in r.members:
            design = f"`{m.design}`" + (
                f" ({m.collapsed_samples} collapsed)" if m.collapsed_samples else ""
            )
            lines.append(
                f"| {m.gse} | {m.contrast} | {m.stratum or ''} | {m.tier} | "
                f"{'yes' if m.pooled else 'no'} | {', '.join(m.flags)} | "
                f"{m.n_case} / {m.n_control} | {design} | {m.median_library_size / 1e6:.1f}M | "
                f"{m.n_genes_tested} | {m.n_sig} | {_fmt(m.mean_concordance)} | "
                f"{'' if m.weight_share is None else _pct(m.weight_share)} | "
                f"{', '.join(m.qc_flags)} |"
            )
        lines.append("")
        quals = [(m, q) for m in r.members for q in m.qualifications]
        if quals:
            lines += ["Read with caution:", ""] + [f"- {m.gse}: {q}" for m, q in quals] + [""]

    if r.excluded:
        lines += [
            "## Excluded",
            "",
            "| dataset | contrast | reason | detail |",
            "| --- | --- | --- | --- |",
        ]
        lines += [
            f"| {e.gse or e.label} | {e.contrast or ''} | {e.reason} | {e.detail} |"
            for e in r.excluded
        ]
        lines.append("")

    if r.genes:
        g = r.genes
        lines += [
            "## Genes",
            "",
            f"{g.n_genes_pooled} of {g.n_genes_union} genes were pooled over at least "
            f"{g.min_studies} datasets; {g.n_sig_pooled} have pooled padj < {g.alpha:g}. "
            f"{g.n_robust} are robust ({_robust_definition(g)}): {g.n_robust_up} higher in "
            f"{r.case_label}, {g.n_robust_down} higher in {r.control_label}. With |pooled "
            f"log2FC| >= {g.lfc_threshold:g}: {g.n_robust_up_lfc} up, {g.n_robust_down_lfc} down.",
            "",
            f"### Robust genes higher in {r.case_label} (|log2FC| >= {g.lfc_threshold:g})",
            "",
            *_gene_rows(g.top_up[:15]),
            "",
            f"### Robust genes higher in {r.control_label} (|log2FC| >= {g.lfc_threshold:g})",
            "",
            *_gene_rows(g.top_down[:15]),
            "",
        ]
    for name, s in r.strata.items():
        lines += [
            f"### Stratum `{name}` ({len(s.members)} datasets)",
            "",
            f"{s.n_robust} robust genes ({s.n_robust_up} up, {s.n_robust_down} down) over "
            f"{s.n_genes_pooled} pooled genes. Top up (|log2FC| >= {s.lfc_threshold:g}): "
            + ", ".join(x.symbol or x.gene_id for x in s.top_up[:10])
            + ". Top down: "
            + ", ".join(x.symbol or x.gene_id for x in s.top_down[:10])
            + ".",
            "",
        ]

    if r.gene_lookup:
        lines += [
            "## Genes of interest",
            "",
            "| query | symbol | verdict | pooled log2FC [95% CI] | padj | replicated | "
            "driven by | detail |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for q in r.gene_lookup:
            m = q.meta
            driven = ", ".join(d.split(":")[0] for d in q.driven_by)
            lines.append(
                f"| {q.query} | {q.symbol or ''} | {q.verdict} | "
                + (
                    f"{_fmt(m.pooled_log2fc)} [{_fmt(m.ci_low)}, {_fmt(m.ci_high)}] | "
                    f"{_fmt(m.padj)} | {_rep(m)} |"
                    if m
                    else " | | |"
                )
                + f" {driven} | {q.detail} |"
            )
        lines += [
            "",
            "'Driven by' lists datasets whose removal changes the verdict "
            "(leave-one-out per gene).",
            "",
        ]

    if r.markers:
        mk = r.markers
        lines += [
            "## Expected markers",
            "",
            f"{mk.n_recovered} of {mk.n_expected} expected markers replicated with the right sign.",
            "",
            "| symbol | expected | verdict | replicated | pooled log2FC |",
            "| --- | --- | --- | --- | --- |",
        ]
        for x in mk.results:
            m = x.lookup.meta
            lines.append(
                f"| {x.expected.symbol} | {x.expected.direction} | {x.lookup.verdict} | "
                f"{_rep(m) if m else ''} | {_fmt(m.pooled_log2fc) if m else ''} |"
            )
        lines.append("")

    if r.pathways:
        p = r.pathways
        lines += [
            "## Pathways",
            "",
            f"GSEA NES per dataset, {p.library}"
            + (f" (md5 {p.gene_sets_md5[:8]})" if p.gene_sets_md5 else "")
            + f", {len(p.members)} datasets: {p.n_consistent} of {p.n_terms} terms have the "
            "same sign in every dataset.",
        ]
        if p.left_out:
            lines.append("Left out: " + "; ".join(f"{k}: {v}" for k, v in p.left_out.items()))
        lines += [
            "",
            f"| term | datasets | same sign | FDR < {p.fdr_threshold} | mean NES |",
            "| --- | --- | --- | --- | --- |",
        ]
        for t in p.terms[:20]:
            lines.append(
                f"| {t.term} | {t.n_members} | {max(t.n_pos, t.n_neg)}/{t.n_members} "
                f"({'+' if t.n_pos >= t.n_neg else '-'}) | {t.n_sig_fdr} | {t.mean_nes:+.2f} |"
            )
        lines.append("")

    if r.pooled_enrichment:
        e = r.pooled_enrichment
        cov = r.pooled_enrichment_coverage
        lines += [
            "## Enrichment of the pooled statistic",
            "",
            f"GSEA preranked on the pooled z (random-effects estimate / SE), {e.library}: "
            f"{e.n_sig_fdr} of {e.n_terms} terms at FDR < {e.fdr_threshold}. Ranked genes: "
            f"{cov.get('ranked', 0)} of {cov.get('pooled', 0)} pooled genes carried a symbol.",
            "",
            "| term | NES | FDR | leading genes |",
            "| --- | --- | --- | --- |",
        ]
        lines += [
            f"| {t.term} | {t.nes:+.2f} | {t.fdr:.3f} | {', '.join(t.lead_genes[:6])} |"
            for t in e.top[:15]
        ]
        lines.append("")

    if r.sensitivity:
        lines += [
            "## Sensitivity",
            "",
            "| dataset | flag | pooled by default | robust genes (default) | robust genes "
            "(membership reversed) | Jaccard | Spearman of pooled z |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        lines += [
            f"| {s.member} | {s.flag} | {'yes' if s.pooled_by_default else 'no'} | "
            f"{s.n_robust_default} | {s.n_robust_alternative} | {s.robust_jaccard:.2f} | "
            f"{_fmt(s.spearman_pooled_z)} |"
            for s in r.sensitivity
        ]
        lines.append("")

    if r.leave_one_out:
        lines += [
            "## Leave one out",
            "",
            "| dataset left out | robust genes without it | robust retained | "
            "Spearman of pooled z |",
            "| --- | --- | --- | --- |",
        ]
        lines += [
            f"| {x.member} | {x.n_robust_without} | {x.robust_retained:.2f} | "
            f"{_fmt(x.spearman_pooled_z)} |"
            for x in r.leave_one_out
        ]
        lines.append("")

    if r.warnings:
        lines += ["## Warnings", ""] + [f"- {w}" for w in r.warnings] + [""]
    if r.files:
        lines += ["## Files", ""] + [f"- `{k}`: {v}" for k, v in r.files.items()] + [""]
    if r.figures:
        lines += ["## Figures", ""] + [f"![{k}]({v})" for k, v in r.figures.items()] + [""]
    return "\n".join(lines)
