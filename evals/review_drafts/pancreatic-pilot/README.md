# Pancreatic cancer eval pilot — review draft

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

This folder preserves Kirsten's approved answer-key decisions and the evidence behind them. The review checkpoint was committed in `5b68ac7` and confirmed on audited main `7cb4817`. It is not a complete executable benchmark or a report of app accuracy. All examples are development examples already inspected by the team.

## What is approved

- Six original candidates are exclusion examples under the agreed eligibility requirements.
- GSE273398 is accepted for the broad pancreatic cancer question. Its six samples are PATU8988 cell-line samples: three controls and three CLIC1-knockdown samples. It does not match an organoid-only final-selection request.
- GSE262627 is a mixed study. Forty sample records are classified as patient-derived organoids; 28 cell-line records retain reported labels but have unresolved conflicts with the growth protocol.
- NCBI's table header contains 35 of the 40 organoid sample IDs. The other five records remain preserved and disclosed, not invented or discarded. PDO6/ZT24 and PDO15/ZT0 are separately absent from the saved sample records.
- Search may return GSE262627 as a candidate. After inspection, the app should identify the supported subset, disclose coverage limitations, and preserve uncertainty. The 35-sample subset is approved for organoid-only selection; this is not approval for downstream analysis.
- PDO and patient-derived organoid are equivalent only when defined by the source. PDO6 and PDO10 remain different model identifiers. Knockdown and knockout remain different treatment labels.

## Read the draft

- [Cell-line study annotations](annotations/GSE273398.json)
- [Mixed-study annotations](annotations/GSE262627.json)
- [Six exclusions](annotations/exclusions.json)
- [Scott's questions and unfinished work](../../../docs/EVAL_REVIEW_CHECKLIST.md)
- `sources/`: portable GEO field excerpts, including all reviewed sample descriptions; contact details omitted.
- `evidence/`: saved search responses, count availability checks, header coverage and time inventory.
- `audit/`: user-authorized decisions with original working-file provenance.
- `evidence_manifest.json`: hashes for detecting changes to packaged evidence and annotations.

Historical paths in annotations/audit refer to the ignored working files under `data/evals/`. The relevant portable evidence is included here; the originals have not been removed. No expression matrix, credentials, or provider setup is included. The NCBI check inspected the count-table header, not all numeric values.

## Validation

From the repository root:

```sh
python3 evals/review_drafts/pancreatic-pilot/validate_review.py
```

This standard-library validator checks preserved IDs/time labels, treatment evidence, 40/28 classification totals, 35/5 count coverage, selection boundaries, unresolved labels, terminology and source hashes. It does not run a model or establish biological validity.

These review JSON files intentionally are not the toolkit's final `Benchmark` schema. Three runnable development cases and stage-specific scoring are implemented in the separate pilot contract; a complete independent benchmark remains open. Never feed annotations or audit files to the system being evaluated. A separate folder in a repository is not an access-control boundary.

## Committed checkpoint and remaining integration

Commit `5b68ac7` contains this review directory and `docs/EVAL_REVIEW_CHECKLIST.md`; the audit confirmed it on main `7cb4817`. Earlier statements that these files were untracked described preparation before that commit. The checkpoint uses a standard-library validator and did not depend on the later evaluator or product commits.

The subsequent documentation update changes status explanations only; source excerpts, annotations, audit decisions and the 37-file evidence manifest remain unchanged. Reader compatibility against pinned `7cb4817` producer code, three stage-specific cases and separate cross-study artifact inspection are implemented and tested. Independent cross-study scientific evaluation remains open.

Scott still needs to resolve model conflicts, reference-genome wording, time alignment and analysis suitability. A cell-line-only prompt case, independent held-out cases and matched app/baseline runs remain future work; development scoring is implemented. This draft is a suitable stopping point without pretending those tasks are finished.
