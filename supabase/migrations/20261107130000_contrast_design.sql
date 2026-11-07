-- Each contrast keeps the design that produced its report. runs.design is replaced by the next
-- run of the same GSE, which may relabel the samples or drop contrasts; their reports stay, so
-- showing them against the newer design mixed results with labels and evidence they were not
-- computed from. Existing rows take the design of their run.
alter table public.run_contrasts add column design jsonb;  -- cell_ledger_api.runs.RunRequest
update public.run_contrasts c
   set design = r.design
  from public.runs r
 where r.session_id = c.session_id and r.gse = c.gse;
