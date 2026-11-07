# Pancreatic cancer eval pilot — review draft

> The runnable eval format changed after this draft: the discovery evals now live in
> `evals/cases/` (see `evals/README.md`), and this pilot's search-stage decisions are carried
> there as the draft case `evals/cases/pancreatic_cancer_broad.json`. The sample-level selection
> expectations below belong to the design step, which is no longer evaluated. The evidence and
> annotations in this folder remain the record behind that case's verdicts.

This folder preserves Kirsten's approved answer-key decisions and the evidence behind them. It is ready for review, not a complete executable benchmark or a report of app accuracy. All examples are development examples already inspected by the team.

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

These review JSON files intentionally are not the toolkit's final `Benchmark` schema. Adapting them to runnable stage-specific cases and adding scoring behavior remains open. Never feed annotations or audit files to the system being evaluated. A separate folder in a repository is not an access-control boundary.

## Proposed first commit boundary — no commit authorized

Include only this directory and `docs/EVAL_REVIEW_CHECKLIST.md` for a standalone reviewed-draft checkpoint. The validator needs Python's standard library only. No product code, dependency changes, old API integration, or existing untracked eval runner is required for this checkpoint.

Other files under `evals/`, the workplan, and unrelated API/web/core changes remain outside this proposed checkpoint. Do not stage the entire `evals/` directory or all working-tree changes. Nothing has been staged or committed.

Scott still needs to resolve model conflicts, reference-genome wording, time alignment and analysis suitability. A cell-line-only prompt case, runnable scoring, independent held-out cases and matched app/baseline runs remain future work. This draft is a suitable stopping point without pretending those tasks are finished.
