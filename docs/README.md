# Project documentation — local working record

## Current revision and validation status — November 7, 2026

GitHub `main` and local HEAD both resolve to `357998e741e8801990cff0bf0c5530fc1faa60e0`.
The four commits first prepared locally are now shared: `914003d` (repository checks),
`03521b3` (core preparation), `c72e540` (browser/API and saved runs), and `357998e`
(evaluation tools and integrity reports). This documentation refresh remains local
and uncommitted; personal roadmap/course documents and ignored research outputs are
not part of those commits. No commit or push was made by this documentation review.

The original integrity report records **289 passed / 71 skipped** at dirty `7cb4817`;
the same counts passed on the isolated final staged snapshot. At committed `357998e`,
configured compatibility checks then passed **30 tests** (all 29 previously skipped
plus one already-enabled test), and the real-data rerun passed **42 tests**, both with
zero skips or failures. All **360 unique Python cases** have therefore passed across
separate runs; there was no single new 360-pass full-suite invocation. Web tests (4),
earlier browser flows (3), production build, lint, formatting and type checks passed.

Historical reports retain their original revision and scope. Matched benchmarks,
independent biological/cross-study validation, production deployment and remaining
recovery edge cases are still pending. The successful GSE82227 marker regression is
separate from the GSE307006 research analysis. Earlier revision references below
identify historical audits, not the current branch head.


- [Current progress and component map](IMPLEMENTATION.md): product, engineering, evaluation and research work, verified results and remaining limits.
- [Decision history](decision_log.md): why changes were made, including live storage/model checks and the paired research analysis.
- [Your plain-language guide](agents/README.md): the reusable agent and standing explanation preference for your Codex projects.
- [Your evaluation workplan](EVALUATION_WORKPLAN.md): transcript/spec reconciliation, personal tasks, ownership, starter worksheets and acceptance checks.
- [Alternative spec](cell-ledger%20--%20alternative%20spec.md): newest written refinement of validation and evaluation.
- [Published-DE validation](validation/README.md): the pipeline rerun on three GEO series whose authors published differential expression tables, with per-gene agreement, figures and the scripts to reproduce it.
- [Hackathon Spec](Cell-Ledger%20%E2%80%94%20Hackathon%20Spec.md): earlier bulk RNA-seq plan and the implemented output contract.
- [Hackathon brief](hackathon-brief.md): judging criteria.
- [Implementation status](IMPLEMENTATION.md): completed work, checks, and remaining acceptance gates.

The [current product/evaluation PRD](PRD.md) covers human bulk RNA-seq and separately evaluated cross-study comparison. It distinguishes the historical `7cb4817` audit, code now pushed through `357998e`, local-only records/data and open validation gates. Consult [evaluation results](../evals/RESULTS.md) for the latest audit scope.

The local copies of the shared specs may precede the audited main revision. The PRD/workplan link to the pinned shared sources; this documentation update does not merge those upstream files.

## Local-only handling

This documentation refresh was excluded from the four code/tooling commits now on
GitHub main. New personal project documents are locally excluded from Git. Existing
tracked Markdown edits remain uncommitted. Course, roadmap, local task configuration
and ignored research outputs remain on disk. Shared specifications and teammate
ownership are unchanged. This review makes no commit or push.
