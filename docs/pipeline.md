# The standard two-group pipeline

One fixed sequence of deterministic steps over NCBI-generated raw counts. The agent
chooses the dataset, the contrast and a handful of parameters; it never writes code.

```
uv run cell-ledger run GSE82227 --genes CXCL9,CXCL10      # one dataset
uv run cell-ledger run-all                                 # every design in the fixtures dir
mise run analyze -- GSE233547 --no-enrichment              # same, via mise
```

Inputs: `data/geo/<GSE>/<GSE>_raw_counts_GRCh38.p13_NCBI.tsv.gz`, the shared
annotation table, and a design file (`samplesheet` + `contrasts` + optional
`markers`; see `packages/core/tests/fixtures/geo_examples/`). Output goes to
`data/runs/<GSE>/<contrast>/`.

## Steps (`cell_ledger.analysis.pipeline.run_pipeline`)

| # | Step | What it does | Where it can stop |
| --- | --- | --- | --- |
| 1 | contract check | `Contrast.problems(sheet)`: arms vs labels, unknown GSMs, < 3 per group, restriction, status still `proposed` | `status = blocked` |
| 1b | qualifications | `Contrast.qualifications(sheet)`: status `uncertain`, contrast or mean sample confidence < 0.7, samples flagged `needs_review` | never; listed under "Read with caution" |
| 2 | load + reconcile | integer-only counts; columns matched to GSMs by id; only contrast GSMs that are in both counts and sheet are kept | `qc_only` if < 3 per arm have counts |
| 3 | QC | library size, detected genes, mito/ribo %, within- vs between-arm correlation, PCA, sex check (XIST vs RPS4Y1) | never; flags only |
| 4 | gene filter | >= 10 counts in >= (smallest arm) samples | `qc_only` if nothing survives |
| 5 | DESeq2 | pydeseq2, control as reference, Wald test, LFC shrinkage. Design is `~block + arm` when the contrast sets `blocking` and >= 3 blocks have both arms (unpaired samples are dropped and listed); otherwise `~arm`, and a declared-but-unusable pairing becomes a qualification. Several samples from one block in one arm (four plaques from a patient) are summed into one observation before the fit, as DESeq2's `collapseReplicates` does, and reported as a qualification; donor repeats within an arm without a declared blocking are reported as unmodelled dependence. The report records every GSM that was fitted (`gsms_fitted`) and the collapse map | |
| 6 | GSEA | gseapy prerank on the Wald statistic, MSigDB Hallmark (bundled GMT) | skipped with a warning on error |
| 7 | gene lookup | per-gene verdict: up / down / no_evidence / not_tested / not_found; marker-panel score | |
| 8 | figures | library sizes, PCA, volcano, genes of interest, enrichment | |
| 9 | write | TSV/CSV tables, `volcano.json.gz` and `heatmap.json.gz` for the UI, `report.json`, `report.md` | |

Every step appends a `StepRecord` (parameters, seconds, warnings) to the report. With
`--progress`, the CLI also prints one `CL_PROGRESS {json}` line per step start and finish on
stdout; the API tails these to show a live stepper.

The run writes into a temporary sibling directory and swaps it into place at the end,
so an output folder never mixes artifacts from two runs. It refuses to replace a
non-empty directory that holds no `report.json`. Any exception is caught: the report
is still written with `status = blocked`, `error` set, and the traceback in `error.txt`.

## Status

- **complete**: DE ran. Significance does not imply the result is meaningful; read the QC flags.
- **qc_only**: contract was fine but NCBI did not quantify enough samples. QC and tables are written, no DE.
- **blocked**: the contrast itself fails the contract, or the pipeline hit an error (`blockers` and `error` say why). QC still runs when possible.

A `complete` report can also carry `qualifications`. The result stands, but the labels
behind it are uncertain (contrast marked uncertain, low confidence, samples needing
review, or a declared pairing that could not be modelled). Proposed contrasts never run:
an LLM proposal has to be confirmed against the sheet first.

## QC flags

Per sample: `very_low_library_size` (< 100k), `low_library_size` (< 1M), `high_mito_fraction`
(> 20 %), `low_within_arm_correlation` (< 0.8), `closer_to_other_arm`, `sex_mismatch`.
Per dataset: `low_median_library_size`, `possible_group_swap` (>= 25 % of samples closer to
the other arm and arms not separated on PC1), `sex_mismatches`, `arms_not_separated_on_pc1`.

On the ten example datasets this surfaced: two GSE79544 samples labelled male with
thousands of XIST reads and no RPS4Y1 (a metadata error in GEO), six GSE233547 samples
NCBI never quantified, and a responder/non-responder set (GSE111414) where nothing
separates the arms and DE finds zero genes, which is the honest answer.

## Output folder

```
counts.tsv               reconciled raw counts, genes x used samples
samples.csv              sample sheet + QC columns + PCA coordinates
normalized_counts.tsv    DESeq2 size-factor normalized counts
de_results.tsv           gene_id, symbol, base_mean, log2fc (shrunk), lfc_se, stat, pvalue, padj,
                         log2fc_unshrunk, lfc_se_unshrunk (inputs for cross-dataset meta-analysis)
enrichment.tsv           full gseapy table
gene_lookup.csv          verdict table for genes of interest + markers; verdicts: up, down, no_evidence,
                         untestable (reason: independent_filtering or outlier_or_all_zero), not_tested, not_found
volcano.json.gz          gene_id / symbol / base_mean / log2fc / padj as gzipped column arrays: what the
                         web UI draws (the full-precision table is de_results.tsv)
heatmap.json.gz          the 50 most significant genes (half per direction, with the fold-change floor when
                         enough pass it) z-scored over the fitted samples, plus a row and column order from
                         average-linkage clustering on correlation distance: the UI's expression heatmap.
                         Clustering never sees the arms; the UI draws the arm bar on top afterwards
report.json              AnalysisReport, canonical (the only source the LLM may quote numbers from);
                         carries a fingerprint of inputs, design, parameters and code version
error.txt                traceback, only when the run stopped on an exception
report.md                human-readable rendering of report.json
figures/*.png
```

## Parameters (`PipelineParams`)

`min_per_group=3`, `min_count=10`, `alpha=0.05`, `lfc_threshold=1.0`, `lfc_shrink=True`,
`run_enrichment=True`, `gene_sets="msigdb_hallmark_2020"` (or a GMT path), `permutation_num=1000`,
`genes_of_interest=[]`, `markers=[]`, `marker_top_n=200`, `top_n_genes=50`, `figures=True`, `n_cpus=None`.

## Not in v1

Covariates beyond one blocking factor, multi-level factors, repeated measures within a
block (restrict to one time point instead), pooling counts across datasets, TPM, single-cell.

Cross-dataset comparison is a separate layer, below.

# Cross-dataset comparison

When several runs answer the same question (one query set), `cell_ledger.compare` reads their
finished run directories and writes one `ComparisonReport`. It consumes `report.json`,
`de_results.tsv` and `enrichment.tsv` only; counts are never read and nothing is refit on
merged samples.

```
uv run cell-ledger run-set hcc_tumor_vs_adjacent            # run every member, then compare
uv run cell-ledger run-set psoriasis_lesional_vs_control --skip-existing
uv run cell-ledger compare --out data/queries/x --name x --question "..." data/runs/GSE1/c ...
```

A query set (`packages/core/tests/fixtures/query_sets/<name>.json`, model `QuerySet`) names
the question, the case/control labels, the member runs (`gse`, `contrast`, optional
`stratum` slug), marker genes and genes of interest. The agent will write these; today they
are built by `scripts/build_example_samplesheets.py` from the `query_sets` tag on each rule.
Output goes to `data/queries/<name>/`.

`--skip-existing` reuses a member run only when its `report.json` is `complete` and its
`fingerprint` (sha256 over the counts file, the annotation file, the sample sheet, the
contrast, the parameters, the library versions and the analysis source code) matches what
the run would be given now.

## Steps (`cell_ledger.compare.run.run_comparison`)

| # | Step | What it does | Where it can stop |
| --- | --- | --- | --- |
| 1 | load | each run directory separately; a missing or unreadable one is recorded as excluded (`missing`, `unreadable`) and the rest continue. Unshrunk log2FC and SE (`lfc_se_unshrunk`); for runs written before that column existed the SE is reconstructed exactly as `abs(log2fc_unshrunk / stat)` and the member says `reconstructed` | |
| 2 | hard gate | input or design problems only: not `complete`, no DE table, qualified runs if `--exclude-qualified`, and runs sharing fitted GSMs (one piece of evidence; the smaller goes, `shares_samples`) | `insufficient` if < 2 runs can be pooled |
| 3 | concordance | pairwise Spearman of Wald statistics over shared genes. A run with a stratum is judged against the other runs of its stratum, one without against every run; fewer than 2 reference runs means `concordance_unassessed`. Mean below `reversed_concordance` (-0.2): flag `labels_reversed`, left out of the default pool, a question is written to `questions.md`, and the synthesis with it included is reported under Sensitivity. Mean below `low_concordance` (0.2), judged without reversed runs: flag `low_concordance`, still pooled, synthesis without it reported under Sensitivity. **Nothing is excluded for disagreeing**; `--pool-flagged` pools reversed runs too | |
| 4 | genes | genes x datasets matrices over the default pool; per gene: DerSimonian-Laird random-effects pooled log2FC, Hartung-Knapp-Sidik-Jonkman t interval and p (`interval=hksj`; `normal` available), BH padj, tau2, I2, weighted Stouffer z on fitted sample counts. Agreement is counted **against the pooled direction**: `n_agree_pooled`, `replication` (significant in the pooled direction / `n_tested`), and `majority_disagrees_pooled` when most datasets point the other way. `n_tested` counts datasets that contribute an estimate (a padj missing through independent filtering still contributes; `n_with_padj` says how many could be significant). `robust` = pooled padj < alpha, sign agreement >= `sign_consistency` (2/3), replication >= `min_replication` (1/2), tested in >= the effective `min_studies`. Top tables list robust genes with abs(pooled log2FC) >= `lfc_threshold` ranked by pooled z | |
| 5 | strata | the same synthesis within each stratum with >= 2 pooled members, when there are >= 2 strata; stratum names are validated slugs and files are checked to land inside the output directory | |
| 6 | gene lookup | across-dataset verdict per query gene using the same effective minimum as the table: replicated_up / replicated_down (robust), pooled_up / pooled_down (pooled padj < alpha and consistent sign, but significant in under half), inconsistent, no_evidence, insufficient, not_found; per-dataset verdicts; **per-gene leave-one-out** (estimate, interval, verdict without each dataset, and `driven_by`: the datasets whose removal changes the verdict); marker panel score counts only replicated_* | |
| 7 | pathways | Hallmark NES per dataset, merged only across enrichment tables with the same library name and GMT checksum (others listed as left out); terms ranked by sign consistency | |
| 8 | pooled enrichment | GSEA preranked on the pooled z over pooled genes with a symbol, same library; the gene coverage is recorded | skipped with a warning on error |
| 9 | leave one out, sensitivity | robust genes retained and Spearman of pooled z when each pooled dataset is dropped; for every flagged dataset, the synthesis with its membership reversed (Jaccard of robust sets, Spearman of pooled z) | |
| 10 | write | `comparison.json` (canonical), `comparison.md`, `questions.md`, `gene_table.tsv`, `pooled_genes.json.gz` (for the UI), `members.tsv`, `excluded.tsv`, `concordance.tsv`, `pathway_table.tsv`, `pooled_enrichment.tsv`, `strata/*.tsv`, `figures/` | |

Shrunk log2FC is never pooled: shrinkage pulls each dataset toward zero by a dataset-specific
amount. With three datasets the HKSJ test has two degrees of freedom and is deliberately
conservative; the per-dataset replication counts carry the evidence there. Gene identity is
Entrez GeneID on the shared NCBI annotation, so no symbol mapping happens.

The random-effects estimate and the HKSJ interval are checked against
`statsmodels.stats.meta_analysis.combine_effects` and by simulation (null calibration, power,
missing genes) in `packages/core/tests/test_compare.py`.

`pooled_genes.json.gz` is the browser's copy of the gene table: every pooled gene with its
pooled log2FC, `-log10 padj`, agreement counts and robust flag, plus each included dataset's
own log2FC, SE and significance call (set-aside datasets last, marked `pooled: false`), as
gzipped column arrays. Values are quantised to what a plot can show (fold changes and SEs to
0.01, `-log10 padj` to 0.1, capped at 300); the full-precision numbers stay in
`gene_table.tsv`. The compare page draws the genome-wide agreement wall, the pooled volcano and
per-gene forest readouts from this one file. Seventeen datasets by 23,000 genes is about 1.2 MB.

## Figures

`concordance.png` (dataset x dataset Spearman of Wald statistics, flagged runs labelled),
`pathways.png` (terms x datasets NES, dot = FDR < 0.25), `forest.png` (per-dataset log2FC
with 95% CI and the pooled diamond for each gene of interest and marker).

## Parameters (`CompareParams`)

`alpha=0.05`, `min_studies=3`, `low_concordance=0.2`, `reversed_concordance=-0.2`,
`pool_flagged=False`, `include_qualified=True`, `sign_consistency=2/3`, `min_replication=0.5`,
`lfc_threshold=1.0`, `interval="hksj"`, `top_n=50`, `figures=True`, `pooled_enrichment=True`,
`gene_sets="msigdb_hallmark_2020"`, `permutation_num=1000`, `genes_of_interest=[]`, `markers=[]`.
