"""Command line entry point: run the standard pipeline on a dataset design file.

cell-ledger run GSE82227 --genes CXCL9,CXCL10
cell-ledger run-all --no-enrichment
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cell_ledger.analysis.pipeline import PipelineParams, load_design, run_pipeline

DEFAULT_DATA = Path("data/geo")
DEFAULT_DESIGNS = Path("packages/core/tests/fixtures/geo_examples")
DEFAULT_RUNS = Path("data/runs")
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


def run_one(gse: str, args: argparse.Namespace) -> int:
    design = (
        Path(args.design) if getattr(args, "design", None) else args.designs_dir / f"{gse}.json"
    )
    if not design.exists():
        print(f"{gse}: no design file at {design}", file=sys.stderr)
        return 2
    sheet, contrasts, markers = load_design(design)
    if args.contrast:
        contrasts = [c for c in contrasts if c.name == args.contrast]
        if not contrasts:
            print(f"{gse}: no contrast named {args.contrast}", file=sys.stderr)
            return 2
    counts = args.data_dir / gse / f"{gse}_raw_counts_GRCh38.p13_NCBI.tsv.gz"
    annotation = args.data_dir / ANNOTATION
    for missing in (p for p in (counts, annotation) if not p.exists()):
        print(f"{gse}: missing {missing} (run scripts/fetch_geo_examples.py)", file=sys.stderr)
        return 2
    rc = 0
    for contrast in contrasts:
        out = args.out_root / gse / contrast.name
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
        print(line)
        if report.status != "complete":
            rc = 1
    return rc


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="cell-ledger", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
        sp.add_argument("--designs-dir", type=Path, default=DEFAULT_DESIGNS)
        sp.add_argument("--out-root", type=Path, default=DEFAULT_RUNS)
        sp.add_argument("--contrast", help="contrast name; default all in the design file")
        sp.add_argument("--genes", help="comma-separated symbols or GeneIDs to look up")
        sp.add_argument("--alpha", type=float, default=0.05)
        sp.add_argument("--min-per-group", type=int, default=3)
        sp.add_argument("--permutations", type=int, default=1000)
        sp.add_argument("--n-cpus", type=int, default=None)
        sp.add_argument("--no-enrichment", action="store_true")
        sp.add_argument("--no-shrink", action="store_true", help="report unshrunk log2FC")
        sp.add_argument("--no-figures", action="store_true")

    one = sub.add_parser("run", help="run one GSE")
    one.add_argument("gse")
    one.add_argument("--design", help="design JSON (default <designs-dir>/<GSE>.json)")
    common(one)
    allp = sub.add_parser("run-all", help="run every design in --designs-dir")
    common(allp)

    args = p.parse_args(argv)
    if args.cmd == "run":
        return run_one(args.gse, args)
    rc = 0
    for design in sorted(args.designs_dir.glob("GSE*.json")):
        rc = max(rc, run_one(design.stem, args))
    return rc


if __name__ == "__main__":
    sys.exit(main())
