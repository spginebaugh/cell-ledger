# Development

## Setup

```sh
mise install              # toolchains (plus the Supabase CLI and Docker)
mise run setup            # uv sync, bun install, Playwright Chromium
mise run supabase:start   # local Postgres + Storage; applies supabase/migrations, creates the bucket
test -e .env || cp .env.example .env  # preserve an existing .env; fill required settings
```

The API refuses to start without `CELL_LEDGER_DATABASE_URL` and the Supabase Storage
settings: there is no files-only or memory-only mode, locally or deployed.

## Every task

| Task                 | What it does                                                |
| -------------------- | ----------------------------------------------------------- |
| `mise run dev`       | API on :8000 and Vite on :5173 (Vite proxies `/api`)        |
| `mise run supabase:start` / `:stop` / `:reset` | local Supabase stack (Studio on :57323); `reset` re-applies migrations |
| `mise run db:migration -- <name>` | new SQL migration in `supabase/migrations`      |
| `mise run test`      | pytest + vitest; the API tests run against the local stack  |
| `mise run e2e`       | Playwright; boots api and web itself                        |
| `mise run eval -- --system both` | discovery evals vs a web-search baseline (evals/README.md); `eval:score`, `eval:queue` |
| `mise run lint`      | ruff, pyright, Biome, tsc                                   |
| `mise run fmt`       | auto-fix formatting everywhere                              |
| `mise run gen:api`   | export OpenAPI schema and regenerate `apps/web/src/api/generated` |
| `mise run data:fetch`| download every example and query-set GEO dataset into `data/geo` |
| `mise run analyze -- GSE82227` | run the pipeline on one dataset (see docs/pipeline.md) |
| `mise run compare -- hcc_tumor_vs_adjacent` | run every member of a query set, then compare them (docs/pipeline.md) |
| `mise run validate:published` | rerun the published-DE validation behind the Evals page (docs/validation/README.md) |
| `mise run serve`     | production-shaped server on :8000: API + built UI, one origin, no reload |
| `mise run docker:run`| run the exact Fly image locally with `.env` and `./data` mounted |
| `mise run deploy`    | lint, test, build image, `supabase db push`, `fly deploy --ha=false` (docs/deploy.md) |

Run `mise run gen:api` after changing any FastAPI route or pydantic model so the
frontend types stay in sync. The generated client is committed.

## API flow

The user does two things: ask, then tick the datasets to download. Everything after that
runs on its own (`apps/api/src/cell_ledger_api/pipeline.py`).

1. **Discover** (`POST /api/sessions/{id}/discover`, SSE): Claude searches GEO (and the web via
   Exa when configured) and returns candidate series with reasons, or clarifying questions (with
   options) the user answers before choosing; the answers go back in the request's `answers`
   field. Only accessions GEO confirmed in that run can be reported, and the result carries a
   trace of every query and what it returned.
2. **Collect** (`POST .../datasets`): counts and metadata are downloaded, checked and mirrored
   to Storage. This is the last click.
3. **Design** (automatic, per ready dataset): Claude labels every sample from its GEO record
   and chooses the one contrast that answers the question as discovery restated it; the
   `SampleSheet` validator rejects any label without a verbatim quote. A contrast with
   problems (too few samples per arm, labels contradicting the arms) sets the dataset aside
   with the reason; every choice Claude made is recorded on the dataset row (`proposal`).
4. **Run** (automatic, when a design passes): the pipeline runs as a subprocess; `listRuns`
   shows step-by-step progress; `GET .../runs/{gse}/{contrast}` returns the report, the design
   and signed URLs for every file (including `volcano.json.gz` and `heatmap.json.gz`, the
   browser-side DE table and clustered expression heatmap).
5. **Compare** (automatic, once every run is done and two or more completed): pooled effects
   across the session's runs, one comparison per session.

The API still accepts `POST .../runs` and `POST .../comparisons` directly (the tests use
them), but the UI has no manual path: without `CELL_LEDGER_ANTHROPIC_API_KEY` discovery
answers 503, designs fail with that reason, and the home page says so.

## Standalone preparation CLI

The retained topic-to-bundle CLI is separate from the automatic browser workflow.
It prepares per-study bundles and an opt-in script; it does not implicitly execute DE.

```sh
mise exec -- cell-ledger "IFN-gamma stimulated human macrophages" --out ./data/runs/ifng --ask
```

Use a new output directory for each standalone CLI run. CLI `--ask` pauses for exact group labels;
`--auto` records uncertainty and continues. To supply known source labels directly:

```sh
mise exec -- cell-ledger "your topic" --case "treated" --control "untreated" --out ./data/runs/example
```

Without a model, searches use the topic verbatim, results retain GEO order, and group
labels require explicit source values. Optional model-assisted query expansion, ranking and
evidence-backed labeling are enabled by `CELL_LEDGER_MODEL` and `CELL_LEDGER_ANTHROPIC_API_KEY`.
`CELL_LEDGER_NCBI_API_KEY` is optional. The CLI also accepts `ANTHROPIC_API_KEY` and
`NCBI_API_KEY`; prefixed names take precedence. `--offline` uses cached source and model
responses; misses are reported explicitly.

Each output contains `manifest.json`, `shortlist.md`, `questions.md`, `contrasts.json`,
`run_deseq.py`, and separate `datasets/GSE.../` folders. Gene symbols are annotations;
original gene IDs remain the matrix keys. Unknown-unit matrices are exploration-only.
Review the questions before explicitly running `uv run python <output>/run_deseq.py`.

```python
from cell_ledger.bundle import load_bundle

counts, samples, genes, study = load_bundle("data/runs/example/datasets/<GSE>")
# counts is samples × genes, aligned exactly to samples and genes.
```
