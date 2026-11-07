# Deploying cell-ledger

One Docker image runs everywhere: FastAPI serves `/api` and the built React app from the
same origin, with a single uvicorn worker. State lives in Supabase: **Postgres** is the
only record of sessions, datasets and runs, and **Storage** is the only durable copy of
their files. The machine running the API is disposable compute with a local file cache.
Locally the image is `mise run docker:run` against the local Supabase stack; on Fly.io it
is one machine against the cloud project. The only differences are `CELL_LEDGER_*` values.

```
browser ── https ──> Fly proxy ──> uvicorn :8000 ─┬─ /api/*   FastAPI
                                                  └─ /*       apps/web/dist (SPA fallback)
                                        Supabase Postgres    sessions, datasets, runs, run_contrasts
                                        Supabase Storage     <session>/geo/<GSE>/<file>, signed URLs
                                        /data (Fly volume)   cache: GEO downloads, annotation, run outputs
                                        NCBI GEO             E-utilities + FTP, rate-limited
```

## Why these choices

- **Postgres is the source of truth.** Every state transition is a row update
  (`apps/api/src/cell_ledger_api/db.py` holds all the SQL). Status endpoints read rows;
  nothing is derived from what happens to be on disk. Studio (`mise run supabase:status`
  prints the URL) shows exactly what the API sees.
- **Storage holds the files, disk is a cache.** Every collected dataset folder and finished
  contrast folder is mirrored to the private `sessions` bucket. If a run needs counts this
  machine does not have, it pulls them back from Storage first. Wiping `/data` loses nothing.
  Downloads go to the browser through short-lived signed URLs, never through the API box.
- **Long work is a background task.** `POST .../datasets` and `POST .../runs` return 202 and
  insert `pending` / `running` rows. Collect runs as an asyncio task; each pipeline run is a
  `cell-ledger run` subprocess, so scanpy and pydeseq2 memory is freed when it exits and a
  crash cannot take the server down. The UI polls `listDatasets` and `listRuns`.
- **Restarts resume instead of fail.** At boot, every `pending` dataset and `running` run is
  claimed and re-dispatched, with `attempts` bumped. After `CELL_LEDGER_MAX_ATTEMPTS` (2)
  the row is failed with "interrupted by server restart", so a job that crashes the machine
  cannot restart it forever. A deploy mid-run therefore costs time, not the run.
- **One machine, one worker, still.** The download semaphore, the run semaphore and the
  annotation lock are in-process, and the boot-time claim assumes nothing else is running.
  `mise run deploy` passes `--ha=false`. Scale by resizing the VM. Postgres makes a
  multi-machine future possible, but that needs a claim-with-lease job scheme first.
- **Never scale to zero.** `auto_stop_machines = "off"`. Background work outlives the
  request that started it.
- **Memory sizing.** `CELL_LEDGER_MAX_CONCURRENT_RUNS` caps pipeline subprocesses; each fit
  wants a few GB. 2 on the 8 GB box, 4 on 16 GB (`shared-cpu-8x`). Uploads stream from disk.
- **Expiry.** Sessions older than `CELL_LEDGER_SESSION_TTL_HOURS` are deleted (Storage
  objects, then rows, then the cache folder) at boot and every
  `CELL_LEDGER_SWEEP_INTERVAL_MINUTES`. The GEO cache and annotation table on the volume
  survive deploys and keep us under NCBI's rate limit.
- **Storage object limit.** Supabase's free plan caps objects at 50 MB and
  `supabase/config.toml` sets the local bucket to the same, so an oversized counts file
  fails the same way in both places (the dataset stays usable on that machine; `upload_error`
  says why). Raise both together on a paid plan.

## Local development

```sh
mise run supabase:start   # Postgres :57322, Storage/API :57321, Studio :57323 (Docker)
cp .env.example .env      # already points at the local stack; add your NCBI key
mise run dev              # API :8000 + Vite :5173
mise run test             # pytest runs the API suite against the local stack
```

`supabase start` applies `supabase/migrations/*.sql` and creates the `sessions` bucket from
`config.toml`, so the local database and bucket are the cloud project's. The local Storage
secret key is the Supabase CLI's fixed demo `service_role` JWT (in `.env.example`); it only
works against a local stack. Schema changes: `mise run db:migration -- <name>`, edit the new
file, `mise run supabase:reset` to re-apply from scratch locally, `mise run db:push` to the
cloud (the deploy task does this).

To run the production image locally: `mise run docker:run`. It rewrites `127.0.0.1` in your
`.env` to `host.docker.internal` so the container reaches the local stack.

## First-time cloud setup

1. Supabase: create a project. Then:

   ```sh
   supabase login
   supabase link --project-ref <ref>
   mise run db:push                      # applies supabase/migrations
   ```

   Create a **private** Storage bucket named `sessions` (Dashboard → Storage). Copy from
   the dashboard: the project URL, the **secret** key (`sb_secret_...`), and the **Session
   pooler** connection string (Connect → Session pooler; it works over IPv4, which Fly
   needs; the direct connection is IPv6-only).
2. NCBI: get an E-utilities API key (10 req/s instead of 3).
3. Fly:

   ```sh
   fly auth login
   fly launch --no-deploy --copy-config --name cell-ledger --region ord   # pick a free name/region
   fly volumes create cell_ledger_data --region ord --size 20 --yes
   fly secrets set \
     CELL_LEDGER_NCBI_API_KEY=... \
     CELL_LEDGER_DATABASE_URL='postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres' \
     CELL_LEDGER_SUPABASE_URL=https://<ref>.supabase.co \
     CELL_LEDGER_SUPABASE_SECRET_KEY=sb_secret_...
   mise run deploy
   fly open /api/health                  # {"status":"ok", ..., "database":"ok"}
   ```

   If `fly launch` rewrote `fly.toml`, check `git diff fly.toml` and keep our
   `[[mounts]]`, `[http_service]` and `[[vm]]` blocks. Change `app` and
   `primary_region` if you picked different ones.

## Every deploy

```sh
mise run deploy        # lint, test, docker:build, supabase db push, fly deploy --ha=false
mise run deploy:logs
```

The deploy task refuses to ship code that fails lint or tests, builds the image locally
first so a broken Dockerfile fails here, and pushes pending migrations before the new code
that expects them starts. Deploys build on Fly's builders and restart the one machine.
In-flight requests get `kill_timeout` (60 s); in-flight collects and runs are re-dispatched
by the new process.

## Configuration

Non-secret values live in `fly.toml` `[env]` and mirror `.env.example`. Secrets are set
with `fly secrets set` and never committed. The API refuses to start without the database
and storage settings.

| Variable | Fly | Local `.env` |
| --- | --- | --- |
| `CELL_LEDGER_DATABASE_URL` | secret (session pooler) | `postgresql://postgres:postgres@127.0.0.1:57322/postgres` |
| `CELL_LEDGER_SUPABASE_URL` / `_SECRET_KEY` | secret / secret | `http://127.0.0.1:57321` / demo service_role JWT |
| `CELL_LEDGER_SUPABASE_BUCKET` | `sessions` | `sessions` |
| `CELL_LEDGER_DATA_DIR` | `/data` (volume) | `data` |
| `CELL_LEDGER_WEB_DIST` | `/app/web` | unset for `mise run dev`; `mise run serve` sets it |
| `CELL_LEDGER_CORS_ORIGINS` | `[]` | default `["http://localhost:5173"]` for the Vite dev server |
| `CELL_LEDGER_NCBI_API_KEY` | secret | same key |
| `CELL_LEDGER_SESSION_TTL_HOURS` / `_SWEEP_INTERVAL_MINUTES` | 24 / 60 | 24 / 60 |
| `CELL_LEDGER_MAX_CONCURRENT_RUNS` / `_RUN_N_CPUS` | 2 / 2 | unset (defaults: 2 / all cores) |
| `CELL_LEDGER_RUN_TIMEOUT_MINUTES` | 30 | 30 |
| `CELL_LEDGER_MAX_ATTEMPTS` | 2 | 2 |

## Operating

- `fly status`, `fly logs`, `fly ssh console`. Rows: Supabase Studio, or
  `psql "$CELL_LEDGER_DATABASE_URL"`. Objects: Dashboard → Storage → `sessions`.
- `/api/health` returns 503 when Postgres is unreachable; Fly's check then restarts the
  machine, which is the right response to a dropped pool.
- Disk: `fly volumes list`; grow with `fly volumes extend <id> --size 40`. Or just wipe it:
  it is a cache.
- Bigger box: edit `[[vm]]` in `fly.toml`, raise `CELL_LEDGER_MAX_CONCURRENT_RUNS` and
  `CELL_LEDGER_RUN_N_CPUS` to match, and redeploy. pydeseq2 is CPU-bound, so more vCPUs
  shorten each run directly.
- Rollback: `fly releases` then `fly deploy --image <previous image ref> --ha=false`.
  Migrations are forward-only; write a new one to undo a schema change.
