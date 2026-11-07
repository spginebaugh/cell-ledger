# cell-ledger

An AI specialist that helps biologists find and use public human bulk
RNA-seq data from NIH GEO. Ask a question such as *"is gene X higher in cell
type Y in disease Z?"* and the agent searches GEO, triages which datasets are
actually usable (raw counts, readable formats, clear sample labels), harmonizes
their metadata into one sample sheet, runs a reproducible downstream analysis
and returns a report.

## Layout

```
mise.toml            toolchain pins (python 3.13, uv, bun, node) and every task
pyproject.toml       uv workspace root + shared ruff / pytest / pyright config
package.json         bun workspace root + Biome
apps/api/            FastAPI service and agent runtime        (cell_ledger_api)
  sessions.py        sessions and GEO collection; runs.py pipeline subprocesses with live progress
  compare.py         cross-dataset comparisons over a session's runs
  agent/             Claude: discover datasets for a question (tools.py: its GEO tools),
                     design a contrast (design.py); llm.py holds what both share
apps/web/            React + Vite + TanStack Router/Query + Tailwind, d3 charts, vitest, Playwright
packages/core/       pure-Python pipeline library, no web deps (cell_ledger)
  geo/               GEO search and metadata retrieval
  triage/            usability checks
  samplesheet/       harmonized SampleSheet model: the backend/frontend contract
  analysis/          the standard two-group pipeline (QC, pydeseq2, GSEA, gene lookup)
  compare/           cross-dataset comparison over finished runs (gate, meta-analysis, pathways)
  report/            AnalysisReport model, markdown renderer, figures
  cli.py             `cell-ledger run <GSE>` / `run-all` / `run-set <query set>` / `compare`
evals/               discovery evals: cases, specialist and baseline runners, scorer (evals/README.md)
scripts/             dev scripts: fetch example GEO datasets, build gold sample sheets
docs/                specs and ADRs (adr-001: SampleSheet/Contrast contract), deploy.md
supabase/            local stack config + SQL migrations: Postgres is the source of truth for
                     sessions/datasets/runs, Storage holds their files (docs/deploy.md)
Dockerfile, fly.toml one container (API + built UI) on one Fly machine; /data is a cache volume
data/                gitignored local cache: GEO downloads, annotation table, run outputs
```

## Setup

```sh
mise install              # toolchains (plus the Supabase CLI and Docker)
mise run setup            # uv sync, bun install, Playwright Chromium
mise run supabase:start   # local Postgres + Storage; applies supabase/migrations, creates the bucket
cp .env.example .env      # already points at the local stack; add your NCBI key
```

The API refuses to start without `CELL_LEDGER_DATABASE_URL` and the Supabase Storage
settings: there is no files-only or memory-only mode, locally or deployed.

## Everyday tasks

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
| `mise run serve`     | production-shaped server on :8000: API + built UI, one origin, no reload |
| `mise run docker:run`| run the exact Fly image locally with `.env` and `./data` mounted |
| `mise run deploy`    | lint, test, build image, `supabase db push`, `fly deploy --ha=false` (docs/deploy.md) |

Run `mise run gen:api` after changing any FastAPI route or pydantic model so the
frontend types stay in sync. The generated client is committed.

## How a question becomes a result

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
   and signed URLs for every file (including `volcano.json.gz`, the browser-side DE table).
5. **Compare** (automatic, once every run is done and two or more completed): pooled effects
   across the session's runs, one comparison per session.

The API still accepts `POST .../runs` and `POST .../comparisons` directly (the tests use
them), but the UI has no manual path: without `CELL_LEDGER_ANTHROPIC_API_KEY` discovery
answers 503, designs fail with that reason, and the home page says so.

## Conventions

- Analysis steps are pure functions over a count matrix / AnnData plus a
  `SampleSheet`, and record their parameters for reproducibility.
- `packages/core` never imports FastAPI; the agent's tools are thin wrappers
  over core functions so the pipeline runs from a CLI or a test fixture.
- Tests that need GEO data use small fixtures in `packages/core/tests/fixtures`,
  never the network. `fixtures/geo_examples/` holds hand-curated sample sheets and
  contrasts for ten two-group series plus the members of two multi-dataset query sets
  (`fixtures/query_sets/`); `uv run python scripts/fetch_geo_examples.py` downloads
  their counts into `data/geo/` for local integration tests.
