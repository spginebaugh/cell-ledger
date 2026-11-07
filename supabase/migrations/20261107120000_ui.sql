-- Live progress, per-session UI state and cross-dataset comparisons.

-- Step-level progress of a running contrast (cell_ledger_api.runs.RunProgress), written as
-- the API tails the pipeline subprocess. Null before the first step and after a failure.
alter table public.run_contrasts add column progress jsonb;

-- What the user asked and what the UI has worked out so far (discovery results, proposed
-- designs). Owned by the browser through PATCH /sessions/{id}; the API never interprets it.
alter table public.sessions add column question text;
alter table public.sessions add column state jsonb;

-- One cross-dataset comparison per (session, name): a QuerySet over finished runs in the
-- session and the ComparisonReport it produced. Files mirror to
-- <session>/comparisons/<name>/<file> in Storage.
create table public.comparisons (
  session_id    text not null references public.sessions (id) on delete cascade,
  name          text not null check (name ~ '^[a-z0-9]+(_[a-z0-9]+)*$'),
  status        text not null
                check (status in ('running', 'complete', 'insufficient', 'failed')),
  request       jsonb not null,             -- cell_ledger.compare.QuerySet (+ params)
  report        jsonb,                      -- cell_ledger.compare.ComparisonReport
  started_at    timestamptz not null default now(),
  finished_at   timestamptz,
  error         text,
  uploaded      boolean not null default false,
  upload_error  text,
  files         text[] not null default '{}',
  primary key (session_id, name)
);
alter table public.comparisons enable row level security;
