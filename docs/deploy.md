# Deploying cell-ledger

One Docker image runs everywhere: FastAPI serves `/api` and the built React app from the
same origin, with a single uvicorn worker. Locally that image is `mise run docker:run`;
on Fly.io it is one machine with a persistent volume at `/data`. Supabase Storage mirrors
session files in both places. There is no separate "local mode": the only differences
between a laptop and Fly are the values of `CELL_LEDGER_*` variables.

```
browser ── https ──> Fly proxy ──> uvicorn :8000 ─┬─ /api/*   FastAPI
                                                  └─ /*       apps/web/dist (SPA fallback)
                                        /data (Fly volume)   sessions/, geo/ cache, runs/
                                        Supabase Storage     <session>/geo/<GSE>/<file>, signed URLs
                                        NCBI GEO             E-utilities + FTP, rate-limited
```

## Why these choices

- **One machine, one worker.** `SessionService` keeps a download semaphore and an
  annotation lock in-process, and reads session state from local disk. A second
  replica or worker would not see the first one's sessions. `mise run deploy` passes
  `--ha=false` so Fly never adds a standby machine. Scale by resizing the VM.
- **Never scale to zero.** `auto_stop_machines = "off"`. Collects and pipeline runs are
  background work that outlives the request that started it, and the expired-session
  sweep only runs at boot.
- **Long work is a background task, state is on disk.** `POST .../datasets` and
  `POST .../runs` return 202 immediately. Collect runs as an asyncio task in the API;
  each pipeline run is a `cell-ledger run` subprocess, so scanpy and pydeseq2 memory is
  freed when it exits and a crash cannot take the server down. Progress is whatever is on
  the volume: `session.json` lists pending GSEs, `collected.json` and `report.json` /
  `failed.json` per dataset or contrast. The UI polls `listDatasets` and `listRuns`. At
  boot anything still marked in flight is recorded as interrupted. No queue, no job
  table; one machine does not need them.
- **Memory sizing.** `CELL_LEDGER_MAX_CONCURRENT_RUNS` caps pipeline subprocesses; each
  fit wants a few GB. 2 on the 8 GB box, 4 on 16 GB (`shared-cpu-8x`). Uploads to
  Supabase stream from disk, so a 150 MB run folder never sits in API memory.
- **Volume for `/data`.** The GEO cache and the shared annotation table survive deploys,
  which keeps us under NCBI's rate limit. Sessions older than
  `CELL_LEDGER_SESSION_TTL_HOURS` are deleted at startup, locally and in Supabase.
- **Supabase only for files.** Large downloads go to the browser through short-lived
  signed URLs instead of streaming through the API box. The bucket must be private.

## First-time setup

1. Supabase: create a project, then a **private** Storage bucket named `sessions`.
   Copy the project URL and the **secret** key (`sb_secret_...`).
2. NCBI: get an E-utilities API key (10 req/s instead of 3).
3. Fly:

   ```sh
   fly auth login
   fly launch --no-deploy --copy-config --name cell-ledger --region ord   # pick a free name/region
   fly volumes create cell_ledger_data --region ord --size 20 --yes
   fly secrets set \
     CELL_LEDGER_NCBI_API_KEY=... \
     CELL_LEDGER_SUPABASE_URL=https://<ref>.supabase.co \
     CELL_LEDGER_SUPABASE_SECRET_KEY=sb_secret_...
   mise run deploy
   fly open /api/health
   ```

   If `fly launch` rewrote `fly.toml`, check `git diff fly.toml` and keep our
   `[[mounts]]`, `[http_service]` and `[[vm]]` blocks. Change `app` and
   `primary_region` if you picked different ones.

## Every deploy

```sh
mise run lint && mise run test
mise run docker:run        # smoke-test the real image on :8000 with your .env
mise run deploy
mise run deploy:logs
```

Deploys build the Dockerfile on Fly's builders and restart the one machine. In-flight
requests get `kill_timeout` (60 s) to finish.

## Configuration

Non-secret values live in `fly.toml` `[env]` and mirror `.env.example`. Secrets are set
with `fly secrets set` and never committed.

| Variable | Fly | Local `.env` |
| --- | --- | --- |
| `CELL_LEDGER_DATA_DIR` | `/data` (volume) | `data` |
| `CELL_LEDGER_WEB_DIST` | `/app/web` | unset for `mise run dev`; `mise run serve` sets it |
| `CELL_LEDGER_CORS_ORIGINS` | `[]` | default `["http://localhost:5173"]` for the Vite dev server |
| `CELL_LEDGER_NCBI_API_KEY` | secret | same key |
| `CELL_LEDGER_SUPABASE_URL` / `_SECRET_KEY` / `_BUCKET` | secret / secret / `sessions` | same project and bucket, so local behaviour matches |
| `CELL_LEDGER_SESSION_TTL_HOURS` | 24 | 24 |
| `CELL_LEDGER_MAX_CONCURRENT_RUNS` / `_RUN_N_CPUS` | 2 / 2 | unset (defaults: 2 / all cores) |
| `CELL_LEDGER_RUN_TIMEOUT_MINUTES` | 30 | 30 |

Set the Supabase variables locally as well. Without them the API skips the mirror and
signed URLs return 404, which is not how the deployed app behaves.

## Operating

- `fly status`, `fly logs`, `fly ssh console` then `ls /data/sessions`.
- Disk: `fly volumes list`; grow with `fly volumes extend <id> --size 40`.
- Bigger box: edit `[[vm]]` in `fly.toml`, raise `CELL_LEDGER_MAX_CONCURRENT_RUNS` and
  `CELL_LEDGER_RUN_N_CPUS` to match, and redeploy. pydeseq2 is CPU-bound, so more vCPUs
  shorten each run directly.
- A deploy restarts the machine: in-flight collects and runs are marked interrupted and
  the UI shows them as failed. Do not deploy while someone is mid-run.
- Rollback: `fly releases` then `fly deploy --image <previous image ref> --ha=false`.
