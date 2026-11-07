# Review validation

## Evaluation revision and validation status — November 7, 2026

The evaluation implementation and reruns below refer to commit
`357998e741e8801990cff0bf0c5530fc1faa60e0`, which includes evaluation tools and
integrity reports.

The original integrity report records **289 passed / 71 skipped** at dirty `7cb4817`;
the same counts passed on the isolated final staged snapshot. At committed `357998e`,
configured compatibility checks then passed **30 tests** (all 29 previously skipped
plus one already-enabled test), and the real-data rerun passed **42 tests**, both with
zero skips or failures. All **360 unique Python cases** have therefore passed across
separate runs; there was no single new 360-pass full-suite invocation. These are
software and regression checks, not a scientific performance score for this pilot.

Historical reports retain their original revision and scope. Matched benchmarks
and independent biological/cross-study validation remain pending. The successful
GSE82227 marker regression and the separate GSE307006 research analysis do not
validate the pancreatic pilot's scientific conclusions. Earlier revision references
below identify historical audits, not the revision of the evaluation reruns above.

2026-11-07: standalone draft consistency validator passed, including all 37 evidence/annotation hashes, source-backed treatment groups, exact model/time labels, 40 approved organoids and 28 unresolved records, 35 covered and five uncovered organoids, and prompt/stage distinctions.

Existing `evals/tests/test_evaluation.py` passed in the existing project virtual environment. Only dependency deprecation warnings were reported. Those tests exercise the existing evaluator, not live model or scientific performance; the toolkit was outside that historical checkpoint.

The reviewed-draft checkpoint was subsequently committed in `5b68ac7` and confirmed on audited main `7cb4817`. Its scope was this directory and `docs/EVAL_REVIEW_CHECKLIST.md`; unfinished toolkit/product changes were outside it. The November 7 main audit reran the standalone validator successfully. Documentation status corrections do not change the hashed source evidence or annotations.

Current state: three runnable development cases, stage-specific scoring and shared-output reader compatibility are implemented. A complete independent benchmark, measured matched pilot runs, numeric source-matrix validation for the pancreatic selection cases, and scientific resolution of Scott's queue remain open. The separate GSE307006 paired analysis does not close those gates. This validator checks the preserved draft, not scientific performance.
