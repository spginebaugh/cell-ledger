# Discovery evals

These evals answer one question: **does the discovery agent find the right GEO series, pick
the right samples in each, ask when it should, and never invent an accession, and how does
plain Claude with web search and web fetch do on the same cases?** Only the discover step is
measured; the pipeline after it (design, DESeq2, comparison) is covered by its own tests.

Cases should be **narrow questions**: specific enough that a reviewer can check every
candidate series and write down the complete answer, including the samples in each arm. A
broad question belongs in a case only as a should-ask case.

```sh
mise run eval:validate                  # check the case files
mise run eval -- --system both          # every case through specialist and baseline
mise run eval -- --case hcc_tumor_vs_adjacent --repeats 3 --system specialist
mise run eval:score -- data/evals/runs/<run_id>
mise run eval:queue                     # candidates waiting for a human verdict
mise run eval:show -- GSE262627         # a series as the agent reads it, plus every GSM
```

Runs need `CELL_LEDGER_ANTHROPIC_API_KEY` in `.env`; `CELL_LEDGER_NCBI_API_KEY` and
`CELL_LEDGER_EXA_API_KEY` are optional (the specialist uses Exa when the key is present).
Validating, scoring and the queue need no credentials.

## What a case is

One JSON file per case in `cases/`, file name equal to the id (`evals/cases.py` is the
schema):

| Field | Meaning |
| --- | --- |
| `prompt` | the biologist's question, verbatim |
| `expected_action` | what the first turn should do: `proceed`, `ask`, `decline` (out of scope), `no_results` |
| `clarification_targets` | ask cases: one list of words per decision the questions must raise; any word matching any question text counts |
| `answers` | the scripted reply sent as a second turn whenever the system asks. On ask cases it is the user's choice; on other cases it restates what the prompt already settles, so a system that asks needlessly is marked for asking but still gets to answer. |
| `expected_action_after_answers` | second turn's expected action; `proceed` when unset |
| `also_acceptable` | other first-turn actions that are also right (e.g. `ask` on a no-results case) |
| `pool` | GSE → `relevant`, `eligible`, `rationale`, `evidence`, `reviewed_by`, `source`. A `null` verdict means not judged yet. |
| `pool[gse].case_gsms`, `control_gsms` | positives only: every sample that belongs in each arm for this question, whether or not it has counts. Leave both out until the samples are reviewed. |
| `pool[gse].optional_gsms` | samples whose inclusion or exclusion is defensible either way (e.g. recurrences when the question says tumors); not scored |
| `pool[gse].samples_note` | why those samples and not the others (e.g. "organoids only; the 28 cell-line samples are out") |
| `status` | `draft` until a named reviewer has judged every pool entry; then `reviewed` |

Positives are pool entries that are both relevant and eligible. Eligible means human bulk
RNA-seq with NCBI raw counts and at least three samples with counts in each arm of the case's
comparison; a series that fits the question but cannot support the analysis is relevant and
not eligible, with the reason. Relevance needs a person.

## What a run records

`evals/run.py run` builds the real `Discoverer` from `apps/api` (no FastAPI, no database) and
asks it each case. If it asks clarifying questions and the case scripts answers, a second
turn sends them exactly as the UI does. The specialist reads sample records with
`inspect_series` and writes rules over their fields; code turns the rules into GSM lists.
The baseline is the same model with Anthropic's web search and web fetch tools (so it can
read GEO pages), the same question, the same requirements in plain words and the same output
schema, except that it lists its samples' GSMs directly. Nothing else.

Every run saves a `RunRecord` under `data/evals/runs/<run_id>/<system>/<case>/r<k>.json`:
both turns' raw outputs, the final candidates, the agent's trace (every GEO query and the
accessions it returned, every accession GEO confirmed, every one the model named that GEO
never confirmed), token counts and timing, and a post-run GEO check of the candidates.
Records are never edited; scoring reads them.

GEO and Exa responses are cached per run under `data/evals/geo-cache/<run_id>` so repeats of
a case within a run see the same GEO. Pass `--geo-cache <dir>` to reuse an earlier run's
cache and compare two prompts against the exact same search results.

## What gets scored

Per run, then per system (repeats of a case are averaged before cases are averaged):

- **Action**: first-turn action against `expected_action`; should-ask asked, false asks;
  clarification targets hit; second-turn action after the scripted answers. Every question a
  system asked is listed verbatim in the report.
- **Recall**: positives among the final turn's candidates. An ask case without scripted
  answers ends at the question, so listing series there is optional and recall is not scored. **Precision**: among candidates with a
  verdict, how many are positives.
- **Samples**: on returned positives whose arms were reviewed, each arm's samples against the
  reviewer's: sample precision, sample recall, and how many series got both arms exactly
  right. Swapped arms are wrong in both. A candidate without a verdict is *unjudged*: it goes to
  `review_queue.json` and counts for neither.
- **Misses**, by cause: `never_returned` (no GEO query returned it: a search problem),
  `rejected` or `ignored` (GEO returned it, the agent set it aside or left it out: a
  judgment problem), `not_named` (baseline).
- **Fabricated**: candidates GEO has no series for. **Ineligible**: in GEO but not human
  bulk RNA-seq with counts. Both are settled by GEO, so they are wrong without a human and
  are never queued. **Invented but dropped**: accessions the specialist's model named that
  the code removed before the user saw them.
- **Cost**: GEO queries, web searches, tokens and seconds per run.

`results.md` and `results.json` land in the run directory. The comparison is marked ready
only when both systems ran every case and every scored case is reviewed.

## Reviewing

1. `mise run eval:queue` lists candidates no case has a verdict for, with the title and the
   agent's reason.
2. Add each to its case's `pool` with `relevant`, `eligible`, `rationale`, `evidence` and
   `reviewed_by`. Re-scoring removes it from the queue. For a positive, run
   `mise run eval:show -- GSE…` and copy the samples of each arm into `case_gsms` and
   `control_gsms`.
3. When every entry in a case is judged, set `status` to `reviewed` and `reviewed_by`.

Never copy an agent's answer into the pool as gold without checking the GEO record. The
specialist's own trace tells you which accessions it saw; `review_drafts/pancreatic-pilot/`
is an example of the evidence a verdict should rest on.

## Changing the agent

`Discoverer.fingerprint()` (`cell_ledger_api/agent/discover.py`) hashes the discover prompt, the tool definitions, the model and the
effort; every record carries it, so two runs with different fingerprints are a prompt or
tool change and two with the same fingerprint are noise. Run the suite with `--repeats 3`
before and after a change, on the same `--geo-cache`, and compare `results.md`.

## The current suite

Narrow questions, chosen so a reviewer can check every candidate series. Several cases share
a pool, so the same series is a positive for one question and a negative for another.

| Case | Expected | What it tests |
| --- | --- | --- |
| `kras_inhibitor_pancreatic_cells` | proceed | pancreatic subsets of multi-tissue series; xenografts, SOS1/MEK inhibitors, too-few-per-arm and a count-table gap are traps |
| `kras_inhibitor_resistant_pancreatic_cells` | proceed | same pool, different winner; mouse lines mixed into a human series |
| `kras_inhibitor_pdac_organoids` | no_results (ask ok) | in scope, but no series exists; cell lines are not organoids |
| `pdac_organoids_drug_vs_untreated` | proceed | a title that promises organoids over cell-line samples; treated in the patient is not treated in culture |
| `hepatoblastoma_vs_nontumor_liver` | proceed | pediatric tissue, not HepG2-type lines or adult HCC |
| `liver_cancer_broad` | ask, then proceed | subtype question; the answer leads to the hepatoblastoma pool |
| `pancreatic_cancer_broad` | ask, then proceed | bare topic; the answer leads to the organoid drug pool |
| `hcc_tumor_vs_adjacent` | ask | more than ten series qualify; the analysis takes ten |
| `mouse_nash_liver` | decline | another organism |
| `pediatric_crohn_ileum_vs_control` | proceed | pediatric vs adult cohorts, UC mixed in, overlapping cohorts |
| `lung_cancer_broad` | ask | subtype question |
| `colorectal_methylation` | decline | not a gene expression question |

Entries drafted from the GEO records carry `source: "claude-draft 2026-11-07"` and an empty
`reviewed_by`; their sample arms were written as rules over verbatim field values (quoted in
`samples_note`) and applied by the same code as the agent's.
