"""Command line entry point: run the standard pipeline on a dataset design file.

cell-ledger run GSE82227 --genes CXCL9,CXCL10
cell-ledger run-all --no-enrichment
cell-ledger run-set hcc_tumor_vs_adjacent          # every member run, then the comparison
cell-ledger compare --out data/queries/x --name x --question "..." data/runs/GSE1/c data/runs/GSE2/c
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cell_ledger.analysis.pipeline import (
    PipelineParams,
    compute_fingerprint,
    load_design,
    run_pipeline,
)
from cell_ledger.compare import CompareParams, QuerySet, compare_query_set, run_comparison
from cell_ledger.progress import PROGRESS_PREFIX, print_progress, set_progress_sink
from cell_ledger.report.models import MarkerExpectation

DEFAULT_DATA = Path("data/geo")
DEFAULT_DESIGNS = Path("packages/core/tests/fixtures/geo_examples")
DEFAULT_SETS = Path("packages/core/tests/fixtures/query_sets")
DEFAULT_RUNS = Path("data/runs")
DEFAULT_QUERIES = Path("data/queries")
ANNOTATION = "annotation/Human.GRCh38.p13.annot.tsv.gz"


def _params_from(args: argparse.Namespace, markers: list) -> PipelineParams:  # type: ignore[type-arg]
    return PipelineParams(
        run_enrichment=not args.no_enrichment,
        lfc_shrink=not args.no_shrink,
        figures=not args.no_figures,
        genes_of_interest=[g for g in (args.genes or "").split(",") if g],
        markers=markers,
        alpha=args.alpha,
        min_per_group=args.min_per_group,
        n_cpus=args.n_cpus,
        permutation_num=args.permutations,
    )


def run_one(
    gse: str,
    args: argparse.Namespace,
    *,
    only_contrast: str | None = None,
    extra_markers: list[MarkerExpectation] | None = None,
    skip_existing: bool = False,
) -> int:
    design = (
        Path(args.design) if getattr(args, "design", None) else args.designs_dir / f"{gse}.json"
    )
    if not design.exists():
        print(f"{gse}: no design file at {design}", file=sys.stderr)
        return 2
    sheet, contrasts, markers = load_design(design)
    if extra_markers:
        seen = {m.symbol.upper() for m in markers}
        markers = [*markers, *(m for m in extra_markers if m.symbol.upper() not in seen)]
    wanted = only_contrast or args.contrast
    if wanted:
        contrasts = [c for c in contrasts if c.name == wanted]
        if not contrasts:
            print(f"{gse}: no contrast named {wanted}", file=sys.stderr)
            return 2
    counts = (
        Path(args.counts)
        if getattr(args, "counts", None)
        else args.data_dir / gse / f"{gse}_raw_counts_GRCh38.p13_NCBI.tsv.gz"
    )
    annotation = Path(args.annotation) if args.annotation else args.data_dir / ANNOTATION
    for missing in (p for p in (counts, annotation) if not p.exists()):
        print(f"{gse}: missing {missing} (run scripts/fetch_geo_examples.py)", file=sys.stderr)
        return 2
    rc = 0
    for contrast in contrasts:
        out = args.out_root / gse / contrast.name
        if skip_existing and (out / "report.json").exists():
            params = _params_from(args, markers)
            reason = _reusable(out / "report.json", counts, annotation, sheet, contrast, params)
            if reason is None:
                print(f"{gse} {contrast.name}: cached run matches inputs and parameters, skipped")
                continue
            print(f"{gse} {contrast.name}: cached run not reused ({reason}); rerunning")
        if getattr(args, "progress", False):
            set_progress_sink(print_progress, gse=gse, contrast=contrast.name)
        report = run_pipeline(
            counts_path=counts,
            annotation_path=annotation,
            sheet=sheet,
            contrast=contrast,
            out_dir=out,
            params=_params_from(args, markers),
        )
        de = report.de.summary if report.de else None
        line = f"{gse} {contrast.name}: {report.status}"
        if report.qualifications:
            line += " (qualified)"
        if report.error:
            line += f" ERROR {report.error}"
        if report.reconciliation:
            line += f" ({report.reconciliation.n_case} vs {report.reconciliation.n_control})"
        if de:
            line += f" design={de.design!r} sig={de.n_sig} up={de.n_up} down={de.n_down}"
        if report.markers:
            m = report.markers
            line += f" markers={m.n_recovered_sig}/{m.n_expected} top{m.top_n}={m.n_in_top_n}"
        if report.blockers:
            line += f" blockers={report.blockers}"
        line += f" -> {out / 'report.md'}"
        print(line, flush=True)
        set_progress_sink(None)
        if report.status != "complete":
            rc = 1
    return rc


def _reusable(
    report_path: Path, counts: Path, annotation: Path, sheet, contrast, params
) -> str | None:  # type: ignore[no-untyped-def]
    """None when the cached report may be reused, else why not."""
    from cell_ledger.report.models import AnalysisReport

    try:
        cached = AnalysisReport.model_validate_json(report_path.read_text())
    except Exception as exc:  # malformed or from an older schema
        return f"unreadable report: {type(exc).__name__}"
    if cached.status != "complete":
        return f"status {cached.status}"
    if not cached.fingerprint:
        return "no fingerprint recorded"
    if cached.fingerprint != compute_fingerprint(counts, annotation, sheet, contrast, params):
        return "fingerprint differs (inputs, design, parameters or code version changed)"
    return None


def _print_comparison(report, out: Path) -> None:  # type: ignore[no-untyped-def]
    line = f"{report.name}: {report.status} members={len(report.members)} excluded="
    line += ",".join(f"{e.gse}({e.reason})" for e in report.excluded) or "none"
    if report.genes:
        g = report.genes
        line += (
            f" pooled={g.n_genes_pooled} robust={g.n_robust} "
            f"(up={g.n_robust_up} down={g.n_robust_down})"
        )
    if report.markers:
        line += f" markers={report.markers.n_recovered}/{report.markers.n_expected}"
    if report.error:
        line += f" ERROR {report.error}"
    print(f"{line} -> {out / 'comparison.md'}")


def _compare_params(args: argparse.Namespace) -> CompareParams:
    return CompareParams(
        alpha=args.alpha,
        min_studies=args.min_studies,
        low_concordance=args.low_concordance,
        reversed_concordance=args.reversed_concordance,
        pool_flagged=args.pool_flagged,
        include_qualified=not args.exclude_qualified,
        interval=args.interval,
        figures=not args.no_figures,
        pooled_enrichment=not args.no_enrichment,
        genes_of_interest=[g for g in (args.genes or "").split(",") if g],
    )


def run_set(name: str, args: argparse.Namespace) -> int:
    path = Path(args.set_file) if args.set_file else args.sets_dir / f"{name}.json"
    if not path.exists():
        print(f"{name}: no query set file at {path}", file=sys.stderr)
        return 2
    qs = QuerySet.model_validate_json(path.read_text())
    rc = 0
    if not args.compare_only:
        for member in qs.members:
            rc = max(
                rc,
                run_one(
                    member.gse,
                    args,
                    only_contrast=member.contrast,
                    extra_markers=qs.markers,
                    skip_existing=args.skip_existing,
                ),
            )
    out = args.queries_root / qs.name
    report = compare_query_set(qs, args.out_root, out, params=_compare_params(args))
    _print_comparison(report, out)
    return max(rc, 0 if report.status == "complete" else 1)


def compare_dirs(args: argparse.Namespace) -> int:
    out = Path(args.out)
    report = run_comparison(
        [Path(d) for d in args.run_dirs],
        out,
        name=args.name,
        question=args.question or args.name,
        case_label=args.case_label,
        control_label=args.control_label,
        params=_compare_params(args),
    )
    _print_comparison(report, out)
    return 0 if report.status == "complete" else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="cell-ledger", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
        sp.add_argument("--designs-dir", type=Path, default=DEFAULT_DESIGNS)
        sp.add_argument("--out-root", type=Path, default=DEFAULT_RUNS)
        sp.add_argument("--annotation", help="annotation table (default <data-dir>/annotation/...)")
        sp.add_argument("--contrast", help="contrast name; default all in the design file")
        sp.add_argument("--genes", help="comma-separated symbols or GeneIDs to look up")
        sp.add_argument("--alpha", type=float, default=0.05)
        sp.add_argument("--min-per-group", type=int, default=3)
        sp.add_argument("--permutations", type=int, default=1000)
        sp.add_argument("--n-cpus", type=int, default=None)
        sp.add_argument("--no-enrichment", action="store_true")
        sp.add_argument("--no-shrink", action="store_true", help="report unshrunk log2FC")
        sp.add_argument("--no-figures", action="store_true")
        sp.add_argument(
            "--progress",
            action="store_true",
            help=f"print one '{PROGRESS_PREFIX.strip()} {{json}}' line per step on stdout",
        )

    one = sub.add_parser("run", help="run one GSE")
    one.add_argument("gse")
    one.add_argument("--design", help="design JSON (default <designs-dir>/<GSE>.json)")
    one.add_argument("--counts", help="counts file (default <data-dir>/<GSE>/<GSE>_raw_counts...)")
    common(one)
    allp = sub.add_parser("run-all", help="run every design in --designs-dir")
    common(allp)

    def compare_common(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--min-studies", type=int, default=3)
        sp.add_argument("--low-concordance", type=float, default=0.2, help="flag below this")
        sp.add_argument(
            "--reversed-concordance", type=float, default=-0.2, help="quarantine below this"
        )
        sp.add_argument("--pool-flagged", action="store_true", help="pool quarantined runs too")
        sp.add_argument("--exclude-qualified", action="store_true")
        sp.add_argument("--interval", choices=["hksj", "normal"], default="hksj")

    setp = sub.add_parser("run-set", help="run every member of a query set, then compare them")
    setp.add_argument("name")
    setp.add_argument("--set-file", help="query set JSON (default <sets-dir>/<name>.json)")
    setp.add_argument("--sets-dir", type=Path, default=DEFAULT_SETS)
    setp.add_argument("--queries-root", type=Path, default=DEFAULT_QUERIES)
    setp.add_argument("--skip-existing", action="store_true", help="reuse runs with a report.json")
    setp.add_argument("--compare-only", action="store_true", help="do not (re)run members")
    common(setp)
    compare_common(setp)

    cmp = sub.add_parser("compare", help="compare finished run directories")
    cmp.add_argument("run_dirs", nargs="+")
    cmp.add_argument("--out", required=True)
    cmp.add_argument("--name", required=True)
    cmp.add_argument("--question")
    cmp.add_argument("--case-label", default="case")
    cmp.add_argument("--control-label", default="control")
    cmp.add_argument("--genes")
    cmp.add_argument("--alpha", type=float, default=0.05)
    cmp.add_argument("--no-figures", action="store_true")
    cmp.add_argument("--no-enrichment", action="store_true", help="skip pooled GSEA")
    compare_common(cmp)

    args = p.parse_args(argv)
    if args.cmd == "run":
        return run_one(args.gse, args)
    if args.cmd == "run-set":
        return run_set(args.name, args)
    if args.cmd == "compare":
        return compare_dirs(args)
    rc = 0
    for design in sorted(args.designs_dir.glob("GSE*.json")):
        rc = max(rc, run_one(design.stem, args))
    return rc


if __name__ == "__main__":
    sys.exit(main())
