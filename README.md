# cell-ledger

An AI specialist that helps biologists find and use public bulk and single-cell
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
apps/web/            React + Vite + TanStack Query, vitest, Playwright
packages/core/       pure-Python pipeline library, no web deps (cell_ledger)
  geo/               GEO search and metadata retrieval
  triage/            usability checks
  samplesheet/       harmonized SampleSheet model: the backend/frontend contract
  analysis/          the standard two-group pipeline (QC, pydeseq2, GSEA, gene lookup)
  compare/           cross-dataset comparison over finished runs (gate, meta-analysis, pathways)
  report/            AnalysisReport model, markdown renderer, figures
  cli.py             `cell-ledger run <GSE>` / `run-all` / `run-set <query set>` / `compare`
scripts/             dev scripts: fetch example GEO datasets, build gold sample sheets
docs/                specs and ADRs (adr-001: SampleSheet/Contrast contract), deploy.md
Dockerfile, fly.toml one container (API + built UI) on one Fly machine with a /data volume
data/                gitignored GEO cache and run outputs
```

## Setup

```sh
mise install     # toolchains
mise run setup   # uv sync, bun install, Playwright Chromium
```

## Everyday tasks

| Task                 | What it does                                                |
| -------------------- | ----------------------------------------------------------- |
| `mise run dev`       | API on :8000 and Vite on :5173 (Vite proxies `/api`)        |
| `mise run test`      | pytest + vitest                                             |
| `mise run e2e`       | Playwright; boots api and web itself                        |
| `mise run lint`      | ruff, pyright, Biome, tsc                                   |
| `mise run fmt`       | auto-fix formatting everywhere                              |
| `mise run gen:api`   | export OpenAPI schema and regenerate `apps/web/src/api/generated` |
| `mise run data:fetch`| download every example and query-set GEO dataset into `data/geo` |
| `mise run analyze -- GSE82227` | run the pipeline on one dataset (see docs/pipeline.md) |
| `mise run compare -- hcc_tumor_vs_adjacent` | run every member of a query set, then compare them (docs/pipeline.md) |
| `mise run serve`     | production-shaped server on :8000: API + built UI, one origin, no reload |
| `mise run docker:run`| run the exact Fly image locally with `.env` and `./data` mounted |
| `mise run deploy`    | `fly deploy --ha=false`; first-time setup in docs/deploy.md |

Run `mise run gen:api` after changing any FastAPI route or pydantic model so the
frontend types stay in sync. The generated client is committed.

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
