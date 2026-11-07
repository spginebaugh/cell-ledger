# Discovery eval results

Generated 2026-11-07T15:13:28+00:00 · suite `5c2b23011a22` · 12 cases scored

Comparison ready: **False**
Draft (unreviewed) cases scored: colorectal_methylation, hcc_tumor_vs_adjacent, hepatoblastoma_vs_nontumor_liver, kras_inhibitor_pancreatic_cells, kras_inhibitor_pdac_organoids, kras_inhibitor_resistant_pancreatic_cells, liver_cancer_broad, lung_cancer_broad, mouse_nash_liver, pancreatic_cancer_broad, pdac_organoids_drug_vs_untreated, pediatric_crohn_ileum_vs_control

Recall and precision count only pool entries with a human verdict. Unjudged candidates are in the review queue. Sample precision and recall compare each arm's samples with the reviewer's, on returned positives whose arms were reviewed. Draft cases are scored but the comparison is not ready until every scored case is reviewed.

| Metric | baseline | specialist |
| --- | --- | --- |
| Cases (run / scheduled) | 12 / 12 | 12 / 12 |
| Runs (errors) | 12 (0) | 12 (0) |
| Passed | 42% (5/12) | 92% (11/12) |
| Action accuracy | 58% (7/12) | 92% (11/12) |
| Should-ask asked | 100% (4/4) | 100% (4/4) |
| False asks | 100% (5/5) | 20% (1/5) |
| Clarification targets hit | 100% (5/5) | 100% (5/5) |
| Second turn correct | 100% (8/8) | 100% (4/4) |
| Recall (macro over cases) | 0.59 [0.00 to 1.00] | 0.97 [0.80 to 1.00] |
| Recall (pooled) | 62% (15/24) | 96% (23/24) |
| Precision (macro, judged) | 0.67 [0.00 to 1.00] | 1.00 |
| Precision (pooled, judged) | 83% (19/23) | 100% (29/29) |
| Sample precision (pooled) | n/a | 100% (1651/1651) |
| Sample recall (pooled) | 0% (0/1479) | 99% (1651/1675) |
| Sample subsets exactly right | 0% (0/15) | 96% (22/23) |
| Candidates / unjudged / wrong | 24 / 1 / 4 | 35 / 6 / 0 |
| Fabricated accessions | 0 | 0 |
| Ineligible accessions returned | 3 | 0 |
| Invented but dropped by code | 0 | 0 |
| GEO queries / run | 0.0 | 11.8 [0.0 to 24.0] |
| Web searches / run | 15.1 [0.0 to 29.0] | 0.0 |
| Web fetches / run | 13.4 [0.0 to 36.0] | 0.0 |
| Input tokens / run | 292708 [7953 to 928246] | 80992 [4631 to 166448] |
| Output tokens / run | 7854 [278 to 16255] | 3508 [282 to 5522] |
| Seconds / run | 122 [4 to 280] | 42 [4 to 76] |

## Why positives were missed

| System | never_returned | rejected | ignored | not_named |
| --- | --- | --- | --- | --- |
| baseline | 0 | 0 | 0 | 9 |
| specialist | 1 | 0 | 0 | 0 |

never_returned: no GEO query returned it (a search problem). rejected / ignored: GEO returned it and the agent set it aside or left it out (a judgment problem). not_named: the baseline has no search trace; it simply did not name it.

## Questions asked

Each system's clarifying questions on its first turn, verbatim. Asking is scored yes or no against the expected action; whether a question was worth asking is for the reader.

- **colorectal_methylation** · baseline r1 (expected decline)
  - Do you want differential DNA methylation itself, or the expression of genes (possibly methylation-silenced ones) in colorectal tumor vs. normal colon?
- **hcc_tumor_vs_adjacent** · baseline r1
  - Should the analysis be limited to one underlying liver disease (etiology)?
  - Do you need strictly paired tumor/adjacent samples from the same patients?
  - What counts as the control tissue?
  - Which 10 or fewer series should be used, or should the largest paired cohorts be prioritized?
- **hcc_tumor_vs_adjacent** · specialist r1
  - Should the analysis be limited to one HCC cause or patient population, or should it pool all of them?
  - Should tumors from patients with venous invasion (PVTT), recurrence or immunotherapy be included, or only standard resected primary tumors?
- **hepatoblastoma_vs_nontumor_liver** · baseline r1 (expected proceed)
  - Should the control arm be only non-tumour liver adjacent to the tumour from the same children, or can it also be normal liver from other donors (possibly adults)?
  - Should tumours taken after neoadjuvant chemotherapy count, or only treatment-naive tumours?
- **kras_inhibitor_pancreatic_cells** · baseline r1 (expected proceed)
  - Should RAS(ON) multi-selective tri-complex inhibitors (RMC-6236/daraxonrasib, RMC-7977) count as a 'direct KRAS inhibitor', or only KRAS-selective drugs (MRTX1133, sotorasib, adagrasib, BI-2865-type pan-KRAS)?
  - Should the case arm be limited to one KRAS allele and drug, or pool all direct KRAS inhibitors across cell lines?
  - Which treatment duration should be used when a series has more than one time point?
- **kras_inhibitor_pdac_organoids** · baseline r1 (expected no_results)
  - Which class of KRAS inhibitor should count as the treatment?
  - Should only short-term treatment of drug-naive organoids count, or also organoids made resistant by long-term exposure?
  - If too few organoid series exist, can other model types be used as a fallback?
- **kras_inhibitor_pdac_organoids** · specialist r1 (expected no_results)
  - I found no GEO series with raw counts that profiles patient-derived pancreatic cancer organoids treated with a KRAS inhibitor versus vehicle. Would you accept pancreatic cancer cell lines grown in 2D instead?
- **kras_inhibitor_resistant_pancreatic_cells** · baseline r1 (expected proceed)
  - Which drug classes count as a 'KRAS inhibitor' for the resistant arm?
  - Should each resistant line be compared only with its own parental line (one analysis per cell line), or should several cell lines be pooled into one resistant-vs-parental contrast?
- **liver_cancer_broad** · baseline r1
  - Which type of liver cancer do you mean?
  - Which two groups should be compared?
  - If you mean HCC tissue, should the samples be limited to one cause of disease?
  - Is there a specific gene or pathway you want to look at?
- **liver_cancer_broad** · specialist r1
  - Which type of liver cancer do you mean?
  - What should the two groups be?
  - Do you have a preference for patient population (adult vs pediatric, or ethnicity/etiology)?
- **lung_cancer_broad** · baseline r1
  - Which two groups do you want to compare?
  - Which lung cancer type?
  - What kind of sample material?
  - For tumor vs. normal, do the samples need to be paired (tumor and normal from the same patient)?
  - Is there a specific gene or pathway you want to look at?
- **lung_cancer_broad** · specialist r1
  - Which lung cancer type do you mean?
  - What should the comparison be?
  - Is there a gene, drug or pathway you are interested in?
- **pancreatic_cancer_broad** · baseline r1
  - Which two groups do you want to compare?
  - Which type of sample should both arms be?
  - Should this be limited to pancreatic ductal adenocarcinoma, or include other pancreatic tumors?
  - If the controls are 'normal' tissue, which kind?
  - Do you have specific genes or pathways of interest?
- **pancreatic_cancer_broad** · specialist r1
  - What comparison do you want to make?
  - Which tumor type do you mean?
  - Which kind of samples do you want?
  - Do you have a particular gene, drug or pathway in mind?
- **pdac_organoids_drug_vs_untreated** · baseline r1 (expected proceed)
  - Which drug or drug class do you mean? 'A drug' could match many separate GEO series, each testing a different compound, and pooling them would mix unrelated biology.
  - What counts as the untreated control?
  - Should the organoids come only from primary PDAC tissue (surgical resection or EUS-FNA biopsy), or are these also acceptable: PDX-derived organoids, organoids from metastases or ascites, organoids grown with fibroblasts or immune cells, and other pancreatic tumour types (e.g. neuroendocrine)?
  - If one series includes several doses or time points, should all treated samples be pooled into one case arm, or should you pick one dose/time (e.g. the longest exposure or the IC50 dose)?
- **pediatric_crohn_ileum_vs_control** · baseline r1 (expected proceed)
  - Should the Crohn's arm include only children whose ileum is involved, or every child with Crohn's who had an ileal biopsy, including those with colon-only disease?
  - The RISK series probably share patients. Should we use one series (for example GSE57945) or several together with batch correction and duplicate patients removed?
- **pediatric_crohn_ileum_vs_control** · specialist r1 (expected proceed)
  - Should the Crohn's arm include all pediatric CD patients, or only those with ileal involvement (iCD), leaving out colon-only CD (cCD)?

## Every run

| Case | System | Rep | Action (expected → got) | 2nd turn | Recall | Precision | Samples (P / R / exact) | Unjudged | Fabricated | Misses | Error |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| colorectal_methylation | baseline | 1 | decline → decline |  | n/a | n/a | n/a / n/a / n/a | — | — | — |  |
| colorectal_methylation | specialist | 1 | decline → decline |  | n/a | n/a | n/a / n/a / n/a | — | — | — |  |
| hcc_tumor_vs_adjacent | baseline | 1 | ask → ask |  | n/a | 100% (4/4) | n/a / n/a / n/a | — | — | — |  |
| hcc_tumor_vs_adjacent | specialist | 1 | ask → ask |  | n/a | 100% (6/6) | n/a / n/a / n/a | GSE56545, GSE176271, GSE101432 | — | — |  |
| hepatoblastoma_vs_nontumor_liver | baseline | 1 | proceed → ask ✗ | ok | 67% (4/6) | 100% (4/4) | n/a / 0% (0/158) / 0% (0/4) | — | — | GSE199888 (not_named), GSE81928 (not_named) |  |
| hepatoblastoma_vs_nontumor_liver | specialist | 1 | proceed → proceed |  | 100% (6/6) | 100% (6/6) | 100% (209/209) / 100% (209/209) / 100% (6/6) | — | — | — |  |
| kras_inhibitor_pancreatic_cells | baseline | 1 | proceed → ask ✗ | ok | 0% (0/2) | 0% (0/1) | n/a / n/a / n/a | — | — | GSE201412 (not_named), GSE228010 (not_named) |  |
| kras_inhibitor_pancreatic_cells | specialist | 1 | proceed → proceed |  | 100% (2/2) | 100% (2/2) | 100% (30/30) / 100% (30/30) / 100% (2/2) | — | — | — |  |
| kras_inhibitor_pdac_organoids | baseline | 1 | no_results → ask | ok | n/a | n/a | n/a / n/a / n/a | — | — | — |  |
| kras_inhibitor_pdac_organoids | specialist | 1 | no_results → ask | ok | n/a | n/a | n/a / n/a / n/a | — | — | — |  |
| kras_inhibitor_resistant_pancreatic_cells | baseline | 1 | proceed → ask ✗ | ok | 100% (1/1) | 100% (1/1) | n/a / 0% (0/12) / 0% (0/1) | — | — | — |  |
| kras_inhibitor_resistant_pancreatic_cells | specialist | 1 | proceed → proceed |  | 100% (1/1) | 100% (1/1) | 100% (12/12) / 100% (12/12) / 100% (1/1) | — | — | — |  |
| liver_cancer_broad | baseline | 1 | ask → ask | ok | 67% (4/6) | 100% (4/4) | n/a / 0% (0/158) / 0% (0/4) | — | — | GSE199888 (not_named), GSE81928 (not_named) |  |
| liver_cancer_broad | specialist | 1 | ask → ask | ok | 100% (6/6) | 100% (6/6) | 100% (209/209) / 100% (209/209) / 100% (6/6) | — | — | — |  |
| lung_cancer_broad | baseline | 1 | ask → ask |  | n/a | 0% (0/1) | n/a / n/a / n/a | GSE81089 | — | — |  |
| lung_cancer_broad | specialist | 1 | ask → ask |  | n/a | n/a | n/a / n/a / n/a | GSE140343, GSE268175, GSE159857 | — | — |  |
| mouse_nash_liver | baseline | 1 | decline → decline |  | n/a | n/a | n/a / n/a / n/a | — | — | — |  |
| mouse_nash_liver | specialist | 1 | decline → decline |  | n/a | n/a | n/a / n/a / n/a | — | — | — |  |
| pancreatic_cancer_broad | baseline | 1 | ask → ask | ok | 50% (1/2) | 50% (1/2) | n/a / 0% (0/16) / 0% (0/1) | — | — | GSE225011 (not_named) |  |
| pancreatic_cancer_broad | specialist | 1 | ask → ask | ok | 100% (2/2) | 100% (2/2) | 100% (24/24) / 50% (24/48) / 50% (1/2) | — | — | — |  |
| pdac_organoids_drug_vs_untreated | baseline | 1 | proceed → ask ✗ | ok | 50% (1/2) | 50% (1/2) | n/a / 0% (0/16) / 0% (0/1) | — | — | GSE225011 (not_named) |  |
| pdac_organoids_drug_vs_untreated | specialist | 1 | proceed → proceed |  | 100% (2/2) | 100% (2/2) | 100% (48/48) / 100% (48/48) / 100% (2/2) | — | — | — |  |
| pediatric_crohn_ileum_vs_control | baseline | 1 | proceed → ask ✗ | ok | 80% (4/5) | 100% (4/4) | n/a / 0% (0/1119) / 0% (0/4) | — | — | GSE137344 (not_named) |  |
| pediatric_crohn_ileum_vs_control | specialist | 1 | proceed → ask ✗ | ok | 80% (4/5) | 100% (4/4) | 100% (1119/1119) / 100% (1119/1119) / 100% (4/4) | — | — | GSE137344 (never_returned) |  |
