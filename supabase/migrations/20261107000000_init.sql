-- cell-ledger schema. Postgres is the single source of truth for sessions, collected
-- datasets and pipeline runs; Supabase Storage holds the files; the API machine's disk is a
-- cache. Rows mirror the pydantic models in apps/api/src/cell_ledger_api/{sessions,runs}.py.

create table public.sessions (
  id          text primary key check (id ~ '^[0-9a-f]{32}$'),
  created_at  timestamptz not null default now()
);
create index sessions_created_at on public.sessions (created_at);

-- One GEO series collected into a session. 'pending' rows are owned by an in-flight
-- download; a restarted server re-dispatches them (see SessionService.recover).
create table public.datasets (
  session_id    text not null references public.sessions (id) on delete cascade,
  gse           text not null check (gse ~ '^GSE[0-9]+$'),
  status        text not null check (status in ('pending', 'ready', 'excluded', 'failed')),
  attempts      integer not null default 0,
  record        jsonb,                      -- cell_ledger.geo.DatasetRecord
  error         text,
  uploaded      boolean not null default false,
  upload_error  text,
  files         text[] not null default '{}',
  requested_at  timestamptz not null default now(),
  finished_at   timestamptz,
  primary key (session_id, gse)
);
create index datasets_pending on public.datasets (session_id) where status = 'pending';

-- One pipeline submission per (session, GSE): the design file and the process lifecycle.
create table public.runs (
  session_id   text not null,
  gse          text not null,
  status       text not null check (status in ('running', 'finished')),
  attempts     integer not null default 0,
  design       jsonb not null,              -- cell_ledger_api.runs.RunRequest
  started_at   timestamptz not null default now(),
  finished_at  timestamptz,
  error        text,                        -- process-level failure (crash, timeout)
  primary key (session_id, gse),
  foreign key (session_id, gse) references public.datasets (session_id, gse) on delete cascade
);
create index runs_running on public.runs (session_id) where status = 'running';

-- Per-contrast verdicts from the latest run of that contrast.
create table public.run_contrasts (
  session_id    text not null,
  gse           text not null,
  contrast      text not null check (contrast ~ '^[A-Za-z0-9._-]+$'),
  status        text not null
                check (status in ('running', 'complete', 'qc_only', 'blocked', 'failed')),
  started_at    timestamptz not null default now(),
  finished_at   timestamptz,
  error         text,
  report        jsonb,                      -- cell_ledger.report.AnalysisReport
  uploaded      boolean not null default false,
  upload_error  text,
  files         text[] not null default '{}',
  primary key (session_id, gse, contrast),
  foreign key (session_id, gse) references public.runs (session_id, gse) on delete cascade
);

-- The API connects as postgres and bypasses RLS. Nothing else may read these tables through
-- the Data API, so enable RLS with no policies.
alter table public.sessions      enable row level security;
alter table public.datasets      enable row level security;
alter table public.runs          enable row level security;
alter table public.run_contrasts enable row level security;
