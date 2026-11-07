# ADR 001: SampleSheet and Contrast are the upstream/downstream contract

Status: proposed, Nov 6 2026. Owners: downstream (Scott); upstream team please review.

## Context

Upstream (GEO search, fetch, LLM harmonization) and downstream (QC, differential
expression, report) are being built in parallel. Downstream needs to know exactly
what it will receive. The original `Sample` model had no group label, no evidence,
and no notion of which samples a comparison uses.

## Decision

Per GEO series, upstream hands downstream three things:

1. **The NCBI raw counts file** (`<GSE>_raw_counts_GRCh38.p13_NCBI.tsv.gz`, Entrez
   GeneID rows, GSM columns) plus the shared `Human.GRCh38.p13.annot.tsv.gz`.
   Fetch from `ftp.ncbi.nlm.nih.gov/geo/rnaseq_counts/`; the `/geo/download/`
   endpoint returns an empty 200 on HEAD and cannot be used as an existence check.
   Only raw counts are stored. Normalized values are derived downstream (pydeseq2
   size factors, log-CPM, VST); TPM is not used in v1.
2. **A `SampleSheet`** (`cell_ledger.samplesheet`). New fields on `Sample`:
   `group` (case / control / other / unknown, relative to the research question),
   `treatment`, `dose`, `time_point`, `cell_line`, `genotype`, `sex`, `age`,
   `donor`, `batch`, `replicate`, `source_name`, and the trust fields `evidence`,
   `confidence`, `needs_review`. `raw` keeps the GEO characteristics verbatim.
   - `evidence` strings must be substrings of `title`, `source_name`, or a
     `"key: value"` line in `raw`. The model rejects anything else, so an LLM
     cannot emit a label without a real citation.
   - `confidence < 0.7` forces `needs_review = true`.
3. **One or more `Contrast`s**: explicit `case_gsms` and `control_gsms`, human
   labels, optional `blocking` field (pairing variable, recorded but not modelled
   in v1), `restricted_to` (sub-factor the contrast was limited to, e.g. one time
   point), `confidence`, `status`, `rationale`. `Contrast.problems(sheet)` returns
   the reasons a contrast is not DE-ready (arm/label disagreement, unknown GSMs,
   fewer than 3 per group, blocked, restriction violated). Empty list = run it.

Downstream fits `~ group` on exactly the GSMs in the contrast. It reconciles the
counts columns against the sheet and reports GSMs that NCBI did not quantify
instead of assuming alignment (3 of the 10 example series have such gaps).

## Ground truth

`scripts/fetch_geo_examples.py` downloads ten two-group human bulk RNA-seq series
into `data/geo/` (gitignored). `scripts/build_example_samplesheets.py` applies
hand-written rules (one SOFT field per series, values matched verbatim) to produce
`packages/core/tests/fixtures/geo_examples/<GSE>.json`, each holding a sheet and a
confirmed contrast. These are the test fixtures for downstream and the gold labels
for scoring the harmonizer.

## Consequences

- The harmonizer prompt must output this schema and cite evidence; the validator
  is already in the model.
- Multi-factor designs are expressed by `restricted_to` plus `group`, not by a
  formula. If v2 adds pipelines with settings, the contrast is where the agent's
  choice is recorded.
- The `UsabilityVerdict.Blocker` enum will need `too_few_replicates_for_de` and
  `no_contrast` entries so the UI can show "QC-ready, not DE-ready".
