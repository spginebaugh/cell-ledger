# Kirsten's eval review checkpoint

Updated 2026-11-07. Draft development examples, not a finished benchmark. No commit authorized.

## Recorded

- Six original candidates: user-approved exclusions, with evidence retained.
- All seven reviewed accessions rerun through published GeoClient at commit 4a7d8ae5128bff85fffd11101796c25dc438da31. Six excluded; GSE273398 returned.
- GSE273398: user-approved human, bulk RNA-seq, NCBI raw-count availability, pancreatic-cancer relevance, and acceptable search result.
- GSE273398: user-approved PATU8988 cell-line model for its six samples.
- GSE273398 controls: GSM8427623, GSM8427624, GSM8427625 approved.
- GSE273398 CLIC1-knockdown group: GSM8427626, GSM8427627, GSM8427628 approved.

## Next decisions, one at a time

- [x] GSE262627: approve the study-level finding that it contains both cell-line and patient-derived organoid experiments. Source overall_design explicitly describes four cell lines and six organoids; sample-level review is partial: 40 approved organoids, 28 awaiting Scott, 0 unclassified source records.
- [x] Inspect all 68 sample records and preserve their model/time labels: 40 organoids approved; 28 cell-line conflicts recorded for Scott. Final resolution of those conflicts remains open.
- [x] Review human, bulk, NCBI header coverage and pancreatic-cancer relevance for the organoid subset. Counts cover 35 of 40; stage-specific candidate/subset expectations now approved below.
- [x] GSE273398: user approved CLIC1-knockdown group GSM8427626, GSM8427627, GSM8427628. Control and knockdown groups now recorded; no downstream analysis approval.
- [x] Define approved broad pancreatic-cancer and organoid-only expectations, with search and inspection stages separate.
- [ ] Define a separate cell-line-only prompt case in future work; not needed for this draft checkpoint.
- [x] Record source-defined PDO equivalence and knockdown/knockout non-equivalence. Runnable scoring and additional ambiguous terminology cases remain future work.

## Recommended first commit checkpoint: reviewed pilot draft

This can be a draft checkpoint; completing every eval is not necessary.

- [x] Complete the mixed-model study-level decision above; sample-level review remains pending.
- [x] Prepare versionable review copies at evals/review_drafts/pancreatic-pilot/ with source excerpts, audit history and hashes. Original data/evals working files remain ignored; copies are currently untracked, not committed.
- [x] Preserve pending scientific judgments and mark the package as a development review draft, not frozen gold.
- [x] Proposed checkpoint contains only evals/review_drafts/pancreatic-pilot/ and this checklist. Its validator uses the Python standard library; unrelated toolkit/product/dependency changes remain outside this scope.
- [x] Validate and inspect the proposed added-file scope: standalone draft validation passed; existing evaluator test suite passed. Evidence and annotations are versionable. See evals/review_drafts/pancreatic-pilot/VALIDATION.md. No staging or commit performed.
- [ ] Commit only after explicit user permission. Nothing is staged or committed by this checklist.

## Later work still outstanding

- Integrate reviewed annotations into the runnable eval format (candidate assessment.json files are review notes, not by themselves a complete runnable benchmark).
- Implement and test model-type separation and terminology edge cases in scoring; current evidence does not establish those tests exist.
- Add sufficient qualifying examples and a separate held-out set.
- Freeze complete questions and answer keys before scoring model outputs.
- Run matched app/baseline evaluation and inspect failures; no scientific performance score established yet.
- Scott owns downstream scientific confirmation and model credentials/setup. Mandee owns search/API implementation; use versioned response evidence.

Evidence locations: data/evals/pancreatic-pilot/private/, data/evals/qualifying-candidates/, data/evals/mandee-recheck/.

## Consolidated Scott question: GSE262627 model conflict

- [ ] Please confirm whether these 28 reported cell-line samples are cell-line experiments and whether the organoid growth protocol is shared study documentation. All have the same verified conflict. Keep final model assignments pending; this list is local and has not been sent. Earlier individual entries for GSM8172683–GSM8172685 have been consolidated here; historical decisions remain in decisions.jsonl.

| Sample | Reported cell line | Reported time |
|---|---|---|
| GSM8172683 | ASPC1 | 0h |
| GSM8172684 | ASPC1 | 4h |
| GSM8172685 | ASPC1 | 8h |
| GSM8172686 | ASPC1 | 12h |
| GSM8172687 | ASPC1 | 16h |
| GSM8172688 | ASPC1 | 20h |
| GSM8172689 | ASPC1 | 24h |
| GSM8172690 | CAPAN1 | 0h |
| GSM8172691 | CAPAN1 | 4h |
| GSM8172692 | CAPAN1 | 8h |
| GSM8172693 | CAPAN1 | 12h |
| GSM8172694 | CAPAN1 | 16h |
| GSM8172695 | CAPAN1 | 20h |
| GSM8172696 | CAPAN1 | 24h |
| GSM8172697 | PANC1 | 0h |
| GSM8172698 | PANC1 | 4h |
| GSM8172699 | PANC1 | 8h |
| GSM8172700 | PANC1 | 12h |
| GSM8172701 | PANC1 | 16h |
| GSM8172702 | PANC1 | 20h |
| GSM8172703 | PANC1 | 24h |
| GSM8172704 | MIAPACA2 | 0h |
| GSM8172705 | MIAPACA2 | 4h |
| GSM8172706 | MIAPACA2 | 8h |
| GSM8172707 | MIAPACA2 | 12h |
| GSM8172708 | MIAPACA2 | 16h |
| GSM8172709 | MIAPACA2 | 20h |
| GSM8172710 | MIAPACA2 | 24h |

## Current sample-review progress

- [x] All 40 organoid sample model labels approved: two individually and 38 under the user-authorized evidence rule. Identifiers and time labels preserved literally.
- [ ] Scott: the 28 cell-line/model conflicts above remain unresolved. No additional organoid sample-model question is needed.
- [x] User approved PDO6/ZT24 and PDO15/ZT0 as absent from saved series sample records. No samples or values filled in; cause remains unknown. Evidence: data/evals/qualifying-candidates/GSE262627/organoid_time_inventory.json.
- [x] User approved the human requirement for all 40 organoid samples; evidence in organoid_human_check.json.
- [x] User approved bulk RNA-seq for all 40 organoid samples; source protocol questions for Scott remain open.
- [x] User approved partial NCBI raw-count coverage: 35 of 40 organoid IDs occur in the header. Five uncovered sample records and labels preserved unchanged; not classified as absent from GEO. Evidence: organoid_count_coverage.json and ncbi_raw_counts.header.tsv.
- [x] User approved the 35 NCBI count-covered organoid samples as relevant to the broad pancreatic cancer question. No sample labels or coverage decisions changed.
- [x] User approved separate stage expectations: search may return GSE262627 as a candidate; after inspection, identify the 35 count-covered organoid samples, disclose the five uncovered samples, and preserve unresolved model distinctions. Do not require sample-level explanations in Mandee's search response. No downstream readiness approval.
- [x] Returned to GSE273398; user approved CLIC1-knockdown group GSM8427626–GSM8427628.
- [x] User approved GSE273398 as non-matching for organoid-only final selection, while retaining broad pancreatic-cancer acceptance. This does not prohibit initial candidate retrieval.
- [x] User approved organoid-only selection of GSE262627 through its 35 count-covered organoid sample IDs. Disclose five uncovered organoids and keep 28 unresolved cell-line records outside selection. No downstream approval.
- [ ] Do not equate ZT labels with cell-line hour labels without protocol evidence; ask Scott if such alignment is needed for a comparison. No time conversion approved.
- [ ] If downstream analysis requires complete time series, ask Scott how to handle the user-approved record absences PDO6/ZT24 and PDO15/ZT0; do not assume interpolation or exclusion. This is conditional on the analysis scope, not a blocker for model labels.

## Queue freshness check

Checked 2026-11-07 against current annotations and local docs/core/API code, plus GitHub main revision 4a7d8ae5128bff85fffd11101796c25dc438da31 (unchanged from the search recheck). No sample-specific resolution found in the inspected local code or docs; the unchanged published revision supplies no new resolution. Merged pipeline functionality does not resolve source-metadata conflicts. No independent Scott response was available in this check. Duplicate queue entries removed; all 40 approved organoid samples removed from pending model decisions. The 28 source conflicts remain unchanged after applying the organoid rule. No messages sent and no commit made.

GSE273398 knockdown-group labels and GSE262627 stage-specific candidate/subset expectations are approved. Model-specific prompt cases, scoring edge cases, scientific questions, and commit preparation remain open in the sections above. Refresh this queue whenever new approved annotations or relevant repository evidence arrives; do not close scientific questions based only on implementation status.

## Additional source questions for Scott (local; not sent)

- [ ] GSE262627 organoid processing descriptions say “Homo Sapiens genome assembly GRCh38 (mm10)” and separately “Assembly: hg38.” Please resolve the inconsistent reference label before relying on author processing. This does not by itself overturn the explicit human organism labels or establish a problem with NCBI-generated counts. Evidence: all 40 organoid sample data_processing fields; organoid_bulk_check.json.
- [ ] The shared extraction protocol says collection occurred “24 h after the synchronization,” while sample-specific times span ZT0–ZT24. Please clarify how the protocol timing relates to each sample's ZT label before aligning time points or selecting a downstream time comparison. Preserve original labels meanwhile. This extends the existing time-alignment question; it is not a new model-classification conflict.

## Approved count-table coverage finding

Header inspection found five organoid sample IDs absent from the NCBI table. No reason inferred; source annotations preserved. This differs from the two absent time-point records already approved.

| Sample | Model | Time |
|---|---|---|
| GSM8172719 | PDO10 | ZT8 |
| GSM8172723 | PDO10 | ZT24 |
| GSM8172724 | PDO15 | ZT4 |
| GSM8172725 | PDO15 | ZT8 |
| GSM8172728 | PDO15 | ZT20 |

- [ ] Scott, if proceeding to downstream analysis: confirm whether the available 35-sample organoid subset supports the intended comparison given these omissions and the existing timing questions. Do not treat the original 40 as fully count-covered. Local question, not sent; partial coverage and stage-specific subset expectations approved by user; analysis suitability remains undecided.

## Agreed pilot decisions completed

- [x] User approved conditional terminology equivalence: PDO means patient-derived organoid when explicitly defined by the source. Preserve distinct model identifiers such as PDO6 and PDO10.
- [x] User approved keeping knockdown and knockout distinct; preserve source labels and flag ambiguity.

All three agreed pilot decisions are complete. The eval-only review draft is prepared; see evals/review_drafts/pancreatic-pilot/README.md. Scott scientific questions and later benchmark tasks remain open. Commit still requires explicit permission.
