# Cell-Ledger — Hackathon Spec

Nov 6, 2026 · @Scott

## The specialist in one line

Cell-Ledger turns a research topic ("IFN-γ response in human macrophages") into an analysis-ready bundle of public bulk transcriptomic datasets from NCBI GEO: harmonized sample groups, provenance for every field, and a pre-filled pydeseq2 pipeline, in under 10 minutes, with no FASTQ processing.

**User:** a computational or wet-lab biologist checking a hypothesis or starting a meta-analysis across public data. Today this costs 1–3 days per topic: hand-searching GEO, decoding free-text sample characteristics, and working out which supplementary file is actually the count matrix.

**Success:** the biologist runs DESeq2 on Cell-Ledger's output without opening GEO; every case/control label traces to a verbatim source string; and when the data are ambiguous or missing, Cell-Ledger asks or declines instead of guessing.

**Why a specialist wins:** general-purpose models invent GSE accessions, mislabel groups from inconsistent metadata, and feed TPM into DESeq2. Cell-Ledger can only report accessions it has fetched, labels groups with evidence attached, and runs deterministic QC on every matrix before handing it over.

## Input → output contract

One command in, one project folder out. The folder is the product; the chat is just how you steer it.

```
cell-ledger "IFN-gamma stimulated human macrophages" --organism human --max-datasets 5 --out ./ifng_mac
```

Optional flags: `--min-per-group 3`, `--since 2018`, `--tissue`, `--require-control`, `--ask` (stop and ask on every ambiguity) vs `--auto` (decide, flag, keep going).

```
ifng_mac/
  manifest.json        topic, expanded queries, every GSE considered + verdict + reason, timestamps, versions
  shortlist.md         ranked datasets: fit flags, evidence, what to check by hand
  contrasts.json       proposed case-vs-control contrasts per dataset, with confidence
  run_deseq.py         pydeseq2 + gseapy template, pre-filled from contrasts.json
  questions.md         everything Cell-Ledger could not decide (empty = nothing pending)
  datasets/GSE12345/
    counts.tsv         genes x samples, integer raw counts (absent + flagged if only normalized data exist)
    tpm.tsv            when available
    samples.csv        one row per GSM: harmonized fields + verbatim evidence + confidence
    genes.tsv          gene ID, symbol, biotype, chromosome
    provenance.json    URLs, md5, download time, which file was chosen and why, QC results
    dataset.h5ad       AnnData: X=counts, obs=samples, var=genes, uns=provenance
```

Harmonized sample schema (`samples.csv`, also `obs` in the h5ad):

| Field | Values | Filled by |
| --- | --- | --- |
| gsm, title, platform | as in GEO | parser |
| group | case / control / other / unknown | LLM, relative to the topic |
| condition | short normalized label, e.g. `IFNG_24h` | LLM |
| treatment, dose, time\_point | normalized strings or empty | LLM |
| tissue, cell\_type, cell\_line, genotype, sex, age | normalized strings or empty | LLM |
| replicate | int or empty | LLM |
| evidence | verbatim `characteristics_ch1` lines used | copied, never paraphrased |
| confidence | 0–1 | LLM |
| needs\_review | true when confidence < 0.7 or fields conflict | rule |

Every LLM-filled field must cite an `evidence` string that actually appears in the GEO record; the assembler rejects rows where it does not.

## Scope for 24 hours

Narrow enough to finish, wide enough to matter: bulk human RNA-seq from GEO with a precomputed count matrix.

| In | Out (say so when asked) |
| --- | --- |
| NCBI GEO Series (GSE) only | SRA runs, FASTQ, BAM, any alignment or quantification |
| Human only (NCBI counts are complete for human; mouse is not) | Other organisms |
| Bulk RNA-seq with NCBI-generated counts (primary path) | Single-cell, spatial, ChIP/ATAC, proteomics |
| Bulk RNA-seq with a submitter count/TPM table in `suppl/` (fallback path) | Author matrices in Excel-only or per-sample-file form (flag, don't parse) |
| RNA-seq only: GEO type "expression profiling by high throughput sequencing" | Microarray (series matrix / GPL probes), GDC/TCGA, dbGaP, controlled access |
| Case/control and treatment/time designs | Multi-factor designs beyond one contrast (export, don't propose contrasts) |
| Output: AnnData + CSV/TSV + pydeseq2 and gseapy template | Running the DE analysis as part of the agent (template only) |
| `--max-datasets` ≤ 10 per run, 1–3 runs per topic in the demo | Cross-study batch correction or meta-analysis statistics |

If the judges' topic needs something in the right column, the correct behaviour is to say which row blocks it and what the user could do instead, not to attempt it.

## Architecture

A thin tool-calling agent over five deterministic tools. The LLM decides and labels; Python fetches, parses, checks and writes. Nothing the LLM says reaches the output folder without passing through code that verifies it against the GEO record.

**Pipeline (one run):**

1. **Expand** — LLM turns the topic into 3–6 GEO queries (synonyms, gene aliases, cell-type names, MeSH-style terms) plus hard filters (organism, RNA-seq, min samples).
2. **Search** — `search_geo()` runs E-utilities `esearch` + `esummary` on `db=gds`, union of results, deduplicated. Returns accession, title, summary, n\_samples, taxon, date, whether NCBI counts exist.
3. **Rank** — LLM scores each candidate 0–1 for topic fit from title + summary + overall design, with a one-line reason. Deterministic fit flags added: has NCBI counts, n ≥ min per group, has a plausible control, not single-cell.
4. **Fetch** — for the top N: `get_series_metadata()` (GEOparse → per-GSM characteristics, titles, supplementary file list) and `fetch_expression()` (NCBI counts matrix + annotation; fallback: best submitter matrix in `suppl/`). Everything cached on disk by accession.
5. **Harmonize** — LLM maps each GSM's free-text characteristics into the sample schema, with verbatim evidence and confidence. Runs per dataset with the topic in context so `group` is case/control *relative to the question*.
6. **QC** — deterministic checks on matrix and labels (see Trust). Failures either downgrade the dataset, set `needs_review`, or write to `questions.md`.
7. **Assemble** — builds the AnnData, `samples.csv`, `contrasts.json`, `run_deseq.py`, `shortlist.md`, `manifest.json`.

**Tools (Python functions with Pydantic I/O):**

| Tool | Deterministic? | Does |
| --- | --- | --- |
| `search_geo(query, organism, min_samples, since)` | yes | E-utilities search + summary, rate-limited, cached |
| `get_series_metadata(gse)` | yes | GEOparse SOFT parse → sample table + supp file list |
| `fetch_expression(gse, source)` | yes | download, parse, detect value type, align columns to GSMs |
| `harmonize_samples(gse, topic, sample_table)` | LLM + validator | schema extraction with evidence; validator rejects uncited values |
| `qc_dataset(gse)` | yes | matrix + label checks, returns flags |
| `assemble(project)` | yes | writes the output folder |

**Where the LLM is allowed to act:** query expansion, relevance scoring, metadata harmonization, contrast proposal, and deciding when to ask. **Where it is not:** choosing which file to download when a rule applies (NCBI counts always win), parsing numbers, deciding a matrix is "probably counts", or writing any accession it did not receive from `search_geo`.

**Stack:** Python 3.13, `biopython` (E-utilities) or plain `requests`, `GEOparse`, `pandas`, `anndata`, `pydeseq2`, `gseapy`, `pydantic`, one LLM provider SDK, a `click` CLI. SQLite or a folder of JSON for the cache. No framework beyond a 60-line tool loop.

## Data sources and access

Everything comes from NCBI GEO over plain HTTPS; no accounts, no FASTQ, no SRA toolkit.

**Search** — E-utilities, `db=gds`. Example term: `("interferon gamma"[All Fields] OR IFNG[All Fields]) AND macrophage[All Fields] AND "Homo sapiens"[Organism] AND "expression profiling by high throughput sequencing"[DataSet Type] AND GSE[ETYP]`. Add `"rnaseq counts"[Filter]` to restrict to series that already have NCBI-generated counts. `esummary` returns accession, title, summary, `n_samples`, taxon, `PDAT`, and the supplementary-file list. Limits: 3 requests/s without an API key, 10 with (`NCBI_API_KEY` env var). Get a key at hour 0.

**Per-series metadata** — `GEOparse.get_GEO("GSE...")` downloads the SOFT family file and gives `gse.phenotype_data` (one row per GSM: title, source, `characteristics_ch1.*` columns, platform, library strategy) and the supplementary file list. Keep the raw characteristics strings; they are the evidence.

**Expression, primary path: NCBI-generated counts** — uniform HISAT2 + featureCounts pipeline run by GEO on human bulk RNA-seq. Per series:

- Raw counts: `https://www.ncbi.nlm.nih.gov/geo/download/?type=rnaseq_counts&acc=GSE164073&format=file&file=GSE164073_raw_counts_GRCh38.p13_NCBI.tsv.gz`
- TPM: same URL with `GSE164073_norm_counts_TPM_GRCh38.p13_NCBI.tsv.gz`
- Annotation (one file for all human series): `https://www.ncbi.nlm.nih.gov/geo/download/?format=file&type=rnaseq_counts&file=Human.GRCh38.p13.annot.tsv.gz`

First column is Entrez GeneID, remaining columns are GSM IDs, so column-to-sample alignment is exact. Availability check: HTTP HEAD on the raw-counts URL (200 = exists). Known caveats to carry into `provenance.json`: counts differ from the paper's own numbers; single-cell and runs under 50% alignment are skipped; multiple SRA runs per GSM are summed.

**Expression, fallback path: submitter files** — `https://ftp.ncbi.nlm.nih.gov/geo/series/GSE164nnn/GSE164073/suppl/`. Pick the file by rules, not by LLM: prefer names matching `count|raw` over `tpm|fpkm|norm|rpkm`; one tabular file (`.tsv/.csv/.txt`, gz ok) with ≥ 1000 rows and columns that map to GSMs or sample titles. Then detect value type: all non-negative integers → counts; max < 30 with fractional values → log-scale; column sums near 1e6 → TPM/CPM. Anything else is `unknown` and the dataset is marked `needs_review`, never silently used as counts.

**Sources:** [NCBI-generated RNA-seq count data](https://ncbi.nlm.nih.gov/geo/info/rnaseqcounts.html) · [GEOquery RNA-seq vignette](https://bioc.r-universe.dev/GEOquery/doc/rnaseq.qmd) (R reference for the same files).

## Trust: provenance, QC, and asking for help

The judges' question is whether they would trust it. The answer is built from three mechanisms, all deterministic, all visible in the output folder.

**Provenance (every claim has a receipt):**

- Accessions: only values returned by `search_geo`. The assembler refuses any GSE/GSM not present in the cache. Hallucinated accessions are structurally impossible.
- Sample labels: every harmonized field carries the verbatim characteristics string it came from. A validator checks the evidence string is a substring of the real GEO record; rows that fail are dropped to `unknown` and logged.
- Files: URL, md5, download timestamp, file size, which selection rule fired and why, in `provenance.json`.
- Decisions: every dataset considered and rejected appears in `manifest.json` with the reason (low relevance, no matrix, single-cell, too few samples).

**QC checks (run on every dataset, results stored with the data):**

| Check | Pass | Fail action |
| --- | --- | --- |
| Matrix columns match GSMs in metadata | 100% match | downgrade to `needs_review`; unmatched columns dropped and listed |
| Value type | non-negative integers | if TPM/log/unknown: no `counts.tsv`, no contrast, flag |
| Library size | median ≥ 1M counts, no sample < 100k | flag low samples in `samples.csv` |
| Group sizes | ≥ 3 case and ≥ 3 control (or `--min-per-group`) | no contrast proposed, question written |
| Library strategy | all GSMs `RNA-Seq`, not single-cell | drop other-assay GSMs; skip dataset if single-cell |
| Harmonization confidence | mean ≥ 0.7, no `unknown` group in proposed contrast | dataset kept but contrast marked `uncertain` |
| Duplicate / mislabeled samples | no two columns identical; replicate correlation > 0.8 within group | flag outliers by GSM |
| Sanity DE (optional, if time) | top-DE genes for proposed contrast are not all mitochondrial/ribosomal | flag possible group swap |

**When it asks instead of guessing (writes to `questions.md`, or stops in `--ask` mode):**

- Search returns 0 usable datasets → says so, shows the queries it tried, suggests broadening (organism, synonyms, drop the control requirement). Never fills the shortlist with weaker matches without saying they are weaker.
- Two readings of "control" are plausible (time 0 vs vehicle vs untreated healthy) → lists them with the GSMs in each and asks which the user means.
- The topic implies a contrast the design cannot support (e.g. "vs healthy" but all samples are disease) → says the dataset is relevant but cannot answer that question.
- A dataset has only normalized or author-processed values → offers it as "exploration only" and explains why it is not DESeq2 input.
- Topic is outside scope (non-human, single-cell, microarray, non-GEO) → names the scope row and stops.

**Hard refusals:** never fabricate an accession, a sample count, or a p-value; never report a result from `run_deseq.py` it has not executed; never merge datasets into one matrix.

## Evals

Five evals, each answering a question the biologist actually has. Build them before the agent is finished; they are the product spec in executable form.

**Baseline:** the same frontier model with web search and no custom tools, given the same topic and asked for the same output folder (it will produce a list of GSEs and sample labels in text). A second baseline, for the harmonization eval only: the same model zero-shot on raw characteristics, no schema, no evidence requirement. Same topics, same scoring script, both runs logged.

| # | Question | Ground truth | Metric | Target |
| --- | --- | --- | --- | --- |
| 1 | Does it find the right datasets? | 10 topics taken from published RNA-seq meta-analyses that list the GSEs they used (sepsis blood, IPF lung, LPS macrophage, SARS-CoV-2 airway, NASH liver, etc.) | Recall@10 of the paper's GSE set among those eligible (human, NCBI counts); precision by blind 3-person vote on the top 5 | recall ≥ 0.6, precision ≥ 0.8, baseline hallucinated-accession rate reported |
| 2 | Are the sample labels right? | 300 GSMs across 15 series, hand-labeled by the team in hours 2–6 (group, treatment, time\_point, tissue) | Per-field accuracy; case/control F1; % of outputs with valid evidence string | group F1 ≥ 0.9; evidence validity 100% (by construction); baseline F1 reported |
| 3 | Does the output run? | Every dataset the agent emits | % of `dataset.h5ad` that load; % of `run_deseq.py` that finish without edits; % of value-type calls correct on 20 hand-checked matrices (10 counts, 5 TPM, 5 log) | ≥ 95% run; value-type accuracy 100% |
| 4 | Does it reproduce known biology? | 5 datasets with textbook contrasts (LPS vs untreated macrophage → TNF, IL6, IL1B, CXCL10 up; IFN-γ → CXCL9/10/11, IDO1, GBP1; hypoxia → VEGFA, CA9, PGK1; etc.) | Run the agent's own `run_deseq.py` on its own groupings; fraction of marker genes in top 200 by padj with correct sign | ≥ 80% markers recovered; a group swap scores 0 and is the failure to show the judges |
| 5 | Does it know when to stop? | 20 hand-built cases: 8 should-ask (ambiguous control, 0 results, out of scope, normalized-only matrix, time course without baseline), 12 should-proceed | Ask rate on should-ask; false-ask rate on should-proceed; no fabricated accession in any run | should-ask ≥ 7/8; false-ask ≤ 2/12; fabrications = 0 |

**Why these beat a general AI, in one sentence each (for the demo):** 1 — it cannot invent accessions; 2 — it labels with evidence and a schema instead of prose; 3 — it produces files that load, not instructions; 4 — the whole chain is checked against biology the judges already know; 5 — it has an explicit, tested ask-for-help policy.

**Eval harness:** `evals/run.py` takes a topic list and a mode (`specialist` | `baseline`), writes one JSON per run, and `evals/score.py` prints the table above. Runs are cached by accession so the full suite re-runs in minutes.

## Optional: a fine-tuned harmonizer

The agent is the deliverable; a small fine-tuned model is a stretch that strengthens the "specialist" story if the core is done by hour 12. Do not start it before then.

**Task:** `harmonize_samples` only — raw `characteristics_ch1` lines + series title → schema JSON with evidence. It is narrow, high-volume, and the place where general models are weakest, so it is the right thing to specialize.

**Training data (no manual labeling needed):** sample 5,000–10,000 GSMs from human RNA-seq series, label them with the frontier model using the production prompt, keep only rows that pass the evidence validator, split by series (never by sample). Hold out the 300 hand-labeled GSMs from eval 2 as the test set.

**Model:** a 1–4B instruction model, LoRA, 1–2 hours on one GPU. Decode with constrained JSON.

**Go/no-go at hour 12:** go only if evals 1–3 pass on the agent and someone is free. **Claim to make if it works:** the small model matches the frontier model on eval 2 at a fraction of the cost and runs locally, so the whole pipeline can run on a laptop without sending metadata to an API. **If it does not beat the zero-shot baseline, say so in the demo** — a negative result reported honestly is on-theme.

## 24-hour plan

Three workstreams that can run in parallel from hour 1: **Core** (tools + agent), **Evals** (ground truth + harness), **Demo** (CLI polish, README, judges' script). One person owns each; swap at hour 12.

- [ ] **H0–1 — Decisions.** Get an NCBI API key. Pick the LLM. Pin the sample schema (copy from Input → output). Freeze the 10 eval topics and 5 marker-gene contrasts.
- [ ] **H1–4 — Fetch layer.** `search_geo`, `get_series_metadata`, `fetch_expression` with cache. Checkpoint: one command pulls counts + metadata for a known GSE into the output layout.
- [ ] **H1–6 — Ground truth (Evals).** Collect GSE lists from the 10 meta-analysis papers. Hand-label 300 GSMs. Hand-check 20 matrices for value type.
- [ ] **H4–8 — Harmonize + QC.** Schema prompt, evidence validator, value-type detector, QC table. Checkpoint: eval 2 and 3 run end to end on 3 datasets.
- [ ] **H8–12 — Agent loop.** Query expansion, ranking, contrast proposal, `run_deseq.py` template, `questions.md`. Checkpoint: full run on one topic in under 10 minutes.
- [ ] **H12 — Gate.** Evals 1–3 on all topics, specialist and baseline. Decide fine-tune go/no-go. Reassign owners.
- [ ] **H12–16 — Trust behaviours.** Ask-for-help cases, scope refusals, eval 5. Eval 4 (marker recovery) on the 5 contrasts.
- [ ] **H16–20 — Harden.** Run every eval topic cold (cache cleared). Fix the top 3 failure modes. Pre-warm cache for demo topics; leave the judges' topic live.
- [ ] **H20–23 — Demo.** README, 5-slide deck: user, output folder, eval table vs baseline, one failure caught, one question asked. Rehearse the unseen-topic flow twice.
- [ ] **H23–24 — Freeze.** Tag the repo. No code changes after this.

## Risks

| Risk | Likelihood | Mitigation |
| --- | --- | --- |
| NCBI rate limits or outage during the live demo | medium | API key; disk cache of every request; demo topics pre-warmed; a `--offline` flag that runs the cached topics if GEO is down |
| E-utilities search misses relevant series because GEO summaries use different words | high | LLM query expansion to 3–6 queries; union results; report the queries so the user can add terms |
| Harmonization labels a treated sample as control | medium, high cost | evidence requirement; confidence threshold; replicate-correlation check; eval 4 catches group swaps |
| Submitter-file fallback parses garbage | high | strict value-type rules; `unknown` never becomes `counts.tsv`; `needs_review` on every fallback dataset |
| Scope creep (mouse, single-cell, microarray) | high in a hackathon | scope table is frozen at hour 0; refusals are a feature, tested in eval 5 |
| Ground truth takes longer than expected | medium | start it at hour 1 in parallel; 300 GSMs across 15 series is a 3-hour job for one person |
| Fine-tune eats the night | medium | hour-12 gate; it is optional and the demo works without it |
| Judges' topic has zero human bulk RNA-seq in GEO | low | the agent says so, shows its queries, and suggests nearest topics; that is the trust behaviour, not a failure |

## Judges' unseen-challenge demo

The demo is a live run on their topic, narrated against the eval table. Eight minutes.

1. **The user and the pain** (30 s). One biologist, one topic, "this takes a day by hand and a general model makes up accessions."
2. **Live run on the judges' topic** (3 min). Type the command. While it runs, show `manifest.json` filling: queries tried, candidates scored with reasons, datasets rejected and why. Open `shortlist.md`.
3. **Open one dataset** (1.5 min). `samples.csv` with evidence strings next to labels; `provenance.json` with the file rule that fired; QC flags. Open `contrasts.json`, then `run_deseq.py` and run it. Show the top genes.
4. **The eval table** (1.5 min). Specialist vs baseline on all five evals. Point at the baseline's hallucinated-accession rate and the marker-recovery number.
5. **Where it stops** (1 min). Run one should-ask case: ambiguous control. Show `questions.md`. Run one out-of-scope case: say the scope row.
6. **What it cannot do** (30 s). Say it plainly: human only, single-cell, no cross-study meta-analysis, counts differ from papers.

If the judges' topic hits a limit live, do not route around it. Show the question it asks, answer it as the user would, and continue.
