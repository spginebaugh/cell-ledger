# Discovery evals

These evals answer one question: **does the discovery agent find the right GEO series, ask
when it should, and never invent an accession, and how does plain Claude with web search do
on the same cases?** Only the discover step is measured. Sample labelling and contrast
design are covered by the pipeline tests, not here.

```sh
mise run eval:validate                  # check the case files
mise run eval -- --system both          # every case through specialist and baseline
mise run eval -- --case hcc_tumor_vs_adjacent --repeats 3 --system specialist
mise run eval:score -- data/evals/runs/<run_id>
mise run eval:queue                     # candidates waiting for a human verdict
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
| `answers` | ask cases: the scripted answers for the second turn |
| `expected_action_after_answers` | second turn's expected action; `proceed` when unset |
| `pool` | GSE → `relevant`, `eligible`, `rationale`, `evidence`, `reviewed_by`, `source`. A `null` verdict means not judged yet. |
| `status` | `draft` until a named reviewer has judged every pool entry; then `reviewed` |

Positives are pool entries that are both relevant and eligible. Eligible means human bulk
RNA-seq with NCBI raw counts, which the GEO client can check; relevance needs a person.

## What a run records

`evals/run.py run` builds the real `Agent` from `apps/api` (no FastAPI, no database) and
asks it each case. If it asks clarifying questions and the case scripts answers, a second
turn sends them exactly as the UI does. The baseline is the same model with Anthropic's web
search tool, the same question, the same eligibility requirement in plain words and the same
output schema, and nothing else.

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
  clarification targets hit; second-turn action after the scripted answers.
- **Recall**: positives among the candidates. **Precision**: among candidates with a
  verdict, how many are positives. A candidate without a verdict is *unjudged*: it goes to
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
   `reviewed_by`. Re-scoring removes it from the queue.
3. When every entry in a case is judged, set `status` to `reviewed` and `reviewed_by`.

Never copy an agent's answer into the pool as gold without checking the GEO record. The
specialist's own trace tells you which accessions it saw; `review_drafts/pancreatic-pilot/`
is an example of the evidence a verdict should rest on.

## Changing the agent

`Agent.fingerprint()` hashes the discover prompt, the tool definitions, the model and the
effort; every record carries it, so two runs with different fingerprints are a prompt or
tool change and two with the same fingerprint are noise. Run the suite with `--repeats 3`
before and after a change, on the same `--geo-cache`, and compare `results.md`.
