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
| 1 | contract check | `Contrast.problems(sheet)`: arms vs labels, unknown GSMs, < 3 per group, restriction | `status = blocked` |
| 2 | load + reconcile | integer-only counts; columns matched to GSMs by id; only contrast GSMs kept | `qc_only` if < 3 per arm have counts |
| 3 | QC | library size, detected genes, mito/ribo %, within- vs between-arm correlation, PCA, sex check (XIST vs RPS4Y1) | never; flags only |
| 4 | gene filter | >= 10 counts in >= (smallest arm) samples | |
| 5 | DESeq2 | pydeseq2, `~arm`, control as reference, Wald test, apeglm-style LFC shrinkage | |
| 6 | GSEA | gseapy prerank on the Wald statistic, MSigDB Hallmark (bundled GMT) | skipped with a warning on error |
| 7 | gene lookup | per-gene verdict: up / down / no_evidence / not_tested / not_found; marker-panel score | |
| 8 | figures | library sizes, PCA, volcano, genes of interest, enrichment | |
| 9 | write | `dataset.h5ad`, TSV/CSV tables, `report.json`, `report.md` | |

Every step appends a `StepRecord` (parameters, seconds, warnings) to the report.

## Status

- **complete**: DE ran. Significance does not imply the result is meaningful; read the QC flags.
- **qc_only**: contract was fine but NCBI did not quantify enough samples. QC and tables are written, no DE.
- **blocked**: the contrast itself fails the contract (`blockers` says why). QC still runs when possible.

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
de_results.tsv           gene_id, symbol, base_mean, log2fc (shrunk), log2fc_unshrunk, lfc_se, stat, pvalue, padj
enrichment.tsv           full gseapy table
gene_lookup.csv          verdict table for genes of interest + markers
dataset.h5ad             AnnData: layers counts / normed_counts / log2_normed, obs = samples, var = annotation, uns.report = report JSON
report.json              AnalysisReport (the only source the LLM may quote numbers from)
report.md                human-readable rendering of report.json
figures/*.png
```

## Parameters (`PipelineParams`)

`min_per_group=3`, `min_count=10`, `alpha=0.05`, `lfc_threshold=1.0`, `lfc_shrink=True`,
`run_enrichment=True`, `gene_sets="msigdb_hallmark_2020"` (or a GMT path), `permutation_num=1000`,
`genes_of_interest=[]`, `markers=[]`, `marker_top_n=200`, `top_n_genes=50`, `figures=True`, `n_cpus=None`.

## Not in v1

Paired designs (the `blocking` field is recorded, not modelled), covariates, multi-level
factors, cross-dataset pooling, TPM, single-cell.
