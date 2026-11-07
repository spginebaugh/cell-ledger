## Spec: GEO-to-Python research data specialist

**Build an agent that turns a research question into validated, documented RNA-seq datasets that a Python pipeline can actually consume.** Its specialty is selecting appropriate samples, interpreting experimental metadata, and proving that expression values match their annotations.

For the hackathon, use **GEO as the sole data repository, an existing LLM, deterministic validation, and one fixed downstream workflow.**

### 1. User and task

**User:** A computational biologist preparing a reanalysis of public human bulk RNA-seq studies.

**Example request:** “Find human lung bulk RNA-seq studies comparing pulmonary fibrosis with controls, and prepare the data for Python analysis.”

**Output:** Up to three relevant study bundles, each containing an expression matrix, sample metadata, experimental design, provenance, and validation results. Run the supported Python workflow on eligible bundles. Explain exclusions and unresolved questions.

**Success:** The researcher can load and use the data without manually repairing sample identities, reconstructing groups, or guessing what the expression values represent.

### 2. Scope


| Area                | Hackathon scope                                                                                                                                  |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| Repository          | NIH/NCBI GEO; linked SRA/BioSample records only when needed for metadata                                                                         |
| Assay               | Human, bulk, gene-level RNA-seq                                                                                                                  |
| Expression data     | Already-computed matrices; prioritize NCBI-generated gene counts                                                                                 |
| Metadata            | Study description, sample annotations, experimental design, and processing information                                                           |
| Downstream workflow | Python loading and expression-level QC; conditional differential expression                                                                      |
| Exclusions          | FASTQ/BAM processing, microarrays, single-cell/single-nucleus, spatial data, derived pseudobulk, controlled-access data, and cross-study pooling |
| Stretch feature     | Import simple author-supplied CSV/TSV matrices with documented units and explicit sample mappings                                                |


NCBI already provides precomputed raw-count matrices, normalized TPM/FPKM matrices, and gene annotations. Here, **“raw counts” means a processed gene-expression matrix, not sequencing reads**. Record whether values came from NCBI’s processing or the study authors; these can differ. [NCBI](https://www.ncbi.nlm.nih.gov/geo/info/rnaseqcounts.html?utm_source=chatgpt.com)

### 3. Workflow and implementation

Use a small, explicit Python workflow with an LLM for interpretation and fixed code for downloading, parsing, validation, and analysis. No fine-tuning is needed for the MVP.

1. **Interpret the request.** Extract topic, tissue/model, condition, comparator, and intended analysis into a validated schema. Expand topic synonyms. Ask a focused question only when an ambiguity materially changes the search.
2. **Discover candidates.** Search GEO through Entrez ESearch/ESummary, filtering for human sequencing studies and prioritizing `"rnaseq counts"[Filter]`. Inspect a bounded set—such as 20 candidates—and state the search limit. Download full GEO SOFT or MINiML records separately: Entrez supplies discovery metadata, not complete expression matrices. [NCBI](https://www.ncbi.nlm.nih.gov/geo/info/geo_paccess.html?utm_source=chatgpt.com)
3. **Assess eligibility and extract metadata.** The LLM interprets study descriptions and sample characteristics into structured fields. Every consequential interpretation must include a source accession, field, and supporting excerpt. Missing information remains null. Verify eligibility at the **sample level**, including within mixed-assay studies.
4. **Download and standardize.** Fixed code retrieves supported matrices and annotations, maps sample identifiers, preserves expression values, and writes the bundle. Discover available file links rather than assuming every study uses the same filename or reference version. Apply download limits, caching, checksums, and bounded retries.
5. **Validate and run.** Deterministic checks assign analysis capabilities. A prewritten pipeline consumes the bundle. The LLM selects supported parameters; it does not generate arbitrary analysis code.

The interface should show each candidate’s relevance, eligibility evidence, available matrix type, usable sample counts, and blocking issues.

### 4. Python handoff contract

Create **one independent bundle per study**, plus a catalog of accepted, excluded, and unresolved candidates.


| File                 | Required contents                                                                                                                                                             |
| -------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `expression.parquet` | Samples × genes matrix; original identifiers and values                                                                                                                       |
| `samples.tsv`        | One row per exported sample, aligned to the matrix; GSM/source identifiers, tissue, condition, treatment, time point, donor, batch, and replicate information where available |
| `genes.tsv`          | Original gene IDs, identifier namespace, and available annotation; gene symbols remain annotations                                                                            |
| `study.json`         | GSE accession, study summary, experimental design, processing description, expression units, selected comparison, and analysis capabilities                                   |
| `provenance.json`    | Source URLs, retrieval times, file checksums, metadata evidence, sample mappings, transformations, and software versions                                                      |
| `validation.json`    | Passed checks, warnings, exclusions, missing fields, and blocking reasons                                                                                                     |


Expose a simple `load_bundle(path)` function returning expression, sample metadata, gene metadata, and study information.

This orientation matches PyDESeq2’s input contract: samples × genes containing nonnegative integer counts, accompanied by sample metadata. [PyDESeq2 0.5.4 documentation](https://pydeseq2.readthedocs.io/en/stable/auto_examples/plot_minimal_pydeseq2_pipeline.html?utm_source=chatgpt.com)

### 5. Validation and analysis rules

**Import gates**

- Confirm human bulk RNA-seq and relevance to the requested tissue/model.
- Match matrix samples through exact identifiers or documented aliases. Never infer mappings from row order or name similarity.
- Check unique identifiers, dimensions, numeric values, missing values, and matrix-to-metadata correspondence. Report every exclusion.
- Establish expression units from source evidence. Integer-looking values alone do not prove that a matrix contains counts.
- Preserve original gene IDs and expression values. Do not silently merge duplicate symbols or convert normalized values into counts.
- Keep studies separate.

These checks are necessary even for NCBI-generated matrices: GEO explicitly warns about missing samples and studies containing assays or samples unsuitable for direct comparison. [NCBI](https://ncbi.nlm.nih.gov/geo/info/geo2r.html?utm_source=chatgpt.com)

**Analysis capabilities**

- **QC-ready:** A validated matrix with known units and sample identity. Run documented expression-level QC, including detected genes, count-library sizes where applicable, metadata completeness, and PCA using an appropriate transformation. Preserve the original matrix.
- **DE-ready:** Additionally requires documented unnormalized counts, explicit condition/reference labels, and a supported experimental design.
- **Needs review / unsupported:** Return the specific reason and the evidence or decision needed to proceed.

For the MVP, support **independent, two-group differential expression only**, with at least three biological replicates per group as a conservative product policy. Paired/repeated-measures designs, unresolved technical replicates, or known condition–batch confounding block automatic DE. Such studies can still be organized and exported.

TPM/FPKM must never enter the count-based DE path. A successful DE run demonstrates integration; it does not establish biological validity.

### 6. Evaluation: prove useful completion and trust

**Build the benchmark before tuning.** A manageable target is six development studies and twelve held-out studies across several topics, including approximately six usable cases and six excluded or blocked cases. Add a few topic-search tasks over a frozen, manually reviewed candidate pool. Keep related studies together when splitting.

Include human bulk positives and realistic traps: microarray, mouse, single-cell, mixed assays, normalized-only data, ambiguous sample mappings, and unsupported experimental designs. Record gold eligibility, units, sample mappings, condition labels, and expected outcomes with source evidence.

**Primary metric:** Fraction of answerable tasks producing a correct bundle that completes the promised Python workflow without manual repair. A runnable bundle with swapped labels fails.


| Measure                 | What to report                                                                                                 |
| ----------------------- | -------------------------------------------------------------------------------------------------------------- |
| Valid bundle completion | Passed answerable tasks / answerable tasks; target ≥80%                                                        |
| Critical errors         | Wrong assay/species, fabricated metadata, incorrect mappings or units, invalid replicate handling; target zero |
| Retrieval quality       | Relevant, eligible precision among the top three recommendations                                               |
| Metadata quality        | Accuracy and completeness of required fields; all exported sample mappings must be correct                     |
| Uncertainty handling    | Correct blocks/clarifications **and** unnecessary abstentions                                                  |
| Practical effort        | Wall time, model cost, and human corrections per task                                                          |


Use independent gold annotations for scoring, not just the specialist’s own validators. Add small integrity tests: shuffle metadata rows, duplicate an identifier, remove a sample, and provide integer-looking normalized values.

**Baseline:** A general-purpose coding agent with the same underlying model where feasible, task, output schema, source access, Python execution, and time/cost budget. Give both systems the same cached source responses for reproducible evaluation; demonstrate live retrieval separately. Keep gold annotations hidden.

Report actual numerators, denominators, and failures. These targets are goals, not claimed results, and the benchmark does not establish recall across all GEO.

### 7. Twenty-four-hour build plan


| Hours | Deliverable                                                                          |
| ----- | ------------------------------------------------------------------------------------ |
| 0–3   | Verify live download routes; choose demo studies; freeze bundle schema and benchmark |
| 3–8   | GEO discovery, metadata retrieval, standard matrix download, first working bundle    |
| 8–13  | LLM extraction with evidence, sample mapping, eligibility and integrity checks       |
| 13–17 | Python loader, QC workflow, conditional DE, minimal interface                        |
| 17–20 | Development-case testing and fixes                                                   |
| 20–24 | Freeze implementation; run held-out comparison; prepare live judge demonstration     |


**Judge demonstration:** Accept an unseen topic, show why a study qualifies, inspect its sample-to-metadata mapping, and run the Python workflow. Also demonstrate a blocked case with a precise explanation. The evidence should show both that the specialist completes useful work and that it recognizes when the available data cannot support the requested analysis.