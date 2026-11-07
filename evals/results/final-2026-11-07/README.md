# Final discovery eval result (sealed 2026-11-07)

Cell Ledger's discover step against the same Claude model with web search and web fetch, on
12 narrow cases, one repeat each. This folder is the result of record: it holds every run
record, the scored report, the run's conditions, and a snapshot of the cases exactly as they
were scored, so later edits to `evals/cases/` cannot change it.

Run `all12-r2`, started 2026-11-07T15:04:10+00:00; model `claude-opus-5-5`, effort `medium`;
concurrency 4; code revision `4032f8cb3e85` with uncommitted changes (`dirty: true`);
suite `5c2b23011a22`.

## Headline

| Metric | Baseline (Claude + web) | Cell Ledger |
| --- | --- | --- |
| Cases passed | 42% (5/12) | 92% (11/12) |
| Right first move | 58% (7/12) | 92% (11/12) |
| Asked when it should | 100% (4/4) | 100% (4/4) |
| Asked when it should not | 100% (5/5) | 20% (1/5) |
| Second turn correct | 100% (8/8) | 100% (4/4) |
| Correct series found (recall) | 63% (15/24) | 96% (23/24) |
| Picks that were correct (precision, judged) | 83% (19/23) | 100% (29/29) |
| Samples placed in the right arm (recall) | 0% (0/1479) | 99% (1651/1675) |
| Series with both arms exactly right | 0% (0/15) | 96% (22/23) |
| Recommended series that fail GEO eligibility | 3 | 0 |
| Fabricated accessions | 0 | 0 |
| Input tokens per run (mean) | 292708 | 80992 |
| Seconds per run (mean) | 122 | 42 |

## Per case

| Case | Expected | Baseline | Cell Ledger |
| --- | --- | --- | --- |
| `colorectal_methylation` | decline | pass · decline | pass · decline |
| `hcc_tumor_vs_adjacent` | ask | pass · ask | pass · ask |
| `hepatoblastoma_vs_nontumor_liver` | proceed | **fail** · ask ✗, series 4/6, exact arms 0/4 | pass · proceed, series 6/6, exact arms 6/6 |
| `kras_inhibitor_pancreatic_cells` | proceed | **fail** · ask ✗, series 0/2, 1 wrong | pass · proceed, series 2/2, exact arms 2/2 |
| `kras_inhibitor_pdac_organoids` | no_results | pass · ask | pass · ask |
| `kras_inhibitor_resistant_pancreatic_cells` | proceed | **fail** · ask ✗, series 1/1, exact arms 0/1 | pass · proceed, series 1/1, exact arms 1/1 |
| `liver_cancer_broad` | ask | pass · ask, series 4/6, exact arms 0/4 | pass · ask, series 6/6, exact arms 6/6 |
| `lung_cancer_broad` | ask | **fail** · ask, 1 wrong | pass · ask |
| `mouse_nash_liver` | decline | pass · decline | pass · decline |
| `pancreatic_cancer_broad` | ask | **fail** · ask, series 1/2, exact arms 0/1, 1 wrong | pass · ask, series 2/2, exact arms 1/2 |
| `pdac_organoids_drug_vs_untreated` | proceed | **fail** · ask ✗, series 1/2, exact arms 0/1, 1 wrong | pass · proceed, series 2/2, exact arms 2/2 |
| `pediatric_crohn_ileum_vs_control` | proceed | **fail** · ask ✗, series 4/5, exact arms 0/4 | **fail** · ask ✗, series 4/5, exact arms 4/4 |

## What to know when presenting it

- **GEO blocked the baseline.** Its own notes say GEO sample pages answered with a reCAPTCHA,
  so it could find series through web search but never read sample records, and named no
  GSMs. That is a real limit of general-purpose tools and the access advantage of a harness
  that uses NCBI's E-utilities and file server directly; it is not the baseline declining to try.
- **The baseline asked on every case that should have proceeded**, often about things the
  prompt settled. Those cases script a reply that restates the prompt, so it still got a
  second turn to answer. Every question either system asked is listed verbatim in `results.md`.
- **Cell Ledger's one failure** (pediatric Crohn's) was asking whether colon-only Crohn's
  belongs in the arm, the same question the baseline asked, so the case's "proceed"
  expectation is debatable; and its GEO queries never returned GSE137344.
- **The answer key is a draft.** Claude wrote it from the GEO records, as rules over verbatim
  sample fields; the cases are `status: draft` with no named reviewer, which is why the report
  says "comparison ready: false". Seven series found in this run (three HCC, four lung cancer)
  have no verdict and count neither way.
- **One repeat.** Most cases have one or two correct series, so single runs are noisy.
- The cases were chosen to probe what a GEO-connected specialist can do that web search
  cannot (sample-level subsets, count availability, titles that misdescribe their samples).

## Re-scoring

```sh
uv run python -m evals.run score evals/results/final-2026-11-07 --cases evals/results/final-2026-11-07/cases --out /tmp/rescore --no-queue
```

reproduces `results.json` exactly (rows may come out in a different order). The GEO responses
the run saw are in `data/evals/geo-cache/all12-r2` (not committed).
