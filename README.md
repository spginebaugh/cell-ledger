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
  bulk.py, bundle.py  standalone preparation validation and export
  pipeline.py        standalone topic-to-bundle preparation
  interpretation.py  structured interpretation with source evidence
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
test -e .env || cp .env.example .env  # preserve an existing .env; fill required settings
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
   and signed URLs for every file (including `volcano.json.gz` and `heatmap.json.gz`, the
   browser-side DE table and clustered expression heatmap).
5. **Compare** (automatic, once every run is done and two or more completed): pooled effects
   across the session's runs, one comparison per session.

On a run page, clicking a point on the volcano plot opens a gene panel (`?gene=SYMBOL`, also
at `/gene/SYMBOL` on its own). It is independent of the dataset: the browser fetches public
annotation directly from mygene.info, the Human Protein Atlas, UniProt, GTEx, AlphaFold DB and
STRING, and draws the subcellular location on the HPA cell and tissue expression on the
Expression Atlas body (both vendored under `apps/web/public/gene/`, CC BY 4.0).

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

## Local validation history and preserved work

Main was updated from `357998e` to `0341240` on November 7, 2026. The incoming browser
replaces the earlier preparation-only `/api/runs` and Saved runs interface with the
automatic session workflow described above. Earlier saved preparation bundles and
research outputs remain local; this pull did not migrate them or verify that the new
interface can reopen them. Documentation, roadmap and course edits remain uncommitted.

The original integrity report records **289 passed / 71 skipped** at dirty `7cb4817`;
the same counts passed on the isolated final staged snapshot. At committed `357998e`,
configured compatibility checks then passed **30 tests** (all 29 previously skipped
plus one already-enabled test), and the real-data rerun passed **42 tests**, both with
zero skips or failures. All **360 unique Python cases** have therefore passed across
separate runs; there was no single new 360-pass full-suite invocation. Web tests (4),
earlier browser flows (3), production build, lint, formatting and type checks passed.

Historical reports retain their original revision and scope. Matched benchmarks,
independent biological/cross-study validation, production deployment and remaining
recovery edge cases are still pending. The successful GSE82227 marker regression is
separate from the GSE307006 research analysis. These results belong to 357998e and earlier snapshots, not the newly pulled revision.

The separately authorized GSE307006 paired analysis remains local research with its
recorded limitations, not automatic app behavior or an independent benchmark. See
[implementation history](docs/IMPLEMENTATION.md), [evaluation evidence](evals/RESULTS.md)
and [decision history](docs/decision_log.md). Those local records may still describe
the earlier revision; this pull does not relabel their evidence as current.

## Standalone preparation CLI

The retained topic-to-bundle CLI is separate from the new automatic browser workflow.
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
labels require explicit source values. This mode does not perform semantic relevance
ranking. Optional model-assisted query expansion, ranking and evidence-backed labeling
are enabled by `CELL_LEDGER_MODEL` and `CELL_LEDGER_ANTHROPIC_API_KEY` in `.env` or the environment.
Use an actual model ID available to your account. `CELL_LEDGER_NCBI_API_KEY` is optional.
The standalone preparation CLI also accepts `ANTHROPIC_API_KEY` and `NCBI_API_KEY`;
prefixed names take precedence when both are set. The new API requires its documented prefixed settings.
`--offline` uses cached source and model responses; misses are reported explicitly.

Each output contains `manifest.json`, `shortlist.md`, `questions.md`, `contrasts.json`,
`run_deseq.py`, and separate `datasets/GSE.../` folders. Gene symbols are annotations;
original gene IDs remain the matrix keys. Unknown-unit matrices are exploration-only.
Review the questions before explicitly running `uv run python <output>/run_deseq.py`.

```python
from cell_ledger.bundle import load_bundle

counts, samples, genes, study = load_bundle("data/runs/example/datasets/<GSE>")
# counts is samples × genes, aligned exactly to samples and genes.
```
