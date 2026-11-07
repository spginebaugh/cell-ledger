-- The pipeline runs itself: once a dataset is ready the API designs its contrast, starts the
-- run and, when every run in the session is done, the comparison. The design step's outcome
-- lives on the dataset row (cell_ledger_api.designs.DesignProposal), so a reload and a
-- restart both know where each dataset stands. 'designing' is a claim: one job owns the row.
alter table public.datasets
  add column design_status text not null default 'pending'
    check (design_status in ('pending', 'designing', 'designed', 'skipped', 'failed')),
  add column proposal     jsonb,   -- what Claude decided, with every caveat attached
  add column design_error text;    -- why it was skipped (not runnable) or failed (no design)

-- Datasets from before this migration must not be designed again at the next boot: one with
-- a run keeps that run's design as its (unreviewed) proposal; a ready one without a run was
-- never taken further by its user and is set aside rather than billed to Claude now.
update public.datasets d
   set design_status = 'designed',
       proposal = jsonb_build_object('design', r.design, 'notes',
                                     'designed by hand before the pipeline ran automatically')
  from public.runs r
 where r.session_id = d.session_id and r.gse = d.gse;
update public.datasets
   set design_status = 'skipped',
       design_error = 'collected before designs ran automatically; ask the question again'
 where status = 'ready' and design_status = 'pending';
