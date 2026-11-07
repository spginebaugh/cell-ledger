import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import type { SavedRunLibrary as Library } from "./api/generated";

export function SavedRuns({
  selectedId,
  refreshKey,
  disabled,
  onOpen,
}: {
  selectedId: string;
  disabled: boolean;
  refreshKey: string;
  onOpen: (id: string) => void;
}) {
  const [search, setSearch] = useState("");
  const query = useQuery({
    queryKey: ["saved-runs", refreshKey],
    queryFn: async ({ signal }): Promise<Library> => {
      const response = await fetch("/api/runs", { signal });
      if (!response.ok) throw new Error("Could not load saved runs. Try refreshing the library.");
      return response.json();
    },
    retry: false,
  });
  const library = query.data;
  const loading = query.isFetching;
  const error = query.error?.message;

  const matches = (library?.runs ?? []).filter((run) =>
    `${run.topic} ${run.id}`.toLowerCase().includes(search.toLowerCase()),
  );
  return (
    <section aria-labelledby="saved-runs-heading">
      <div className="section-heading">
        <h2 id="saved-runs-heading">Saved runs</h2>
        <button type="button" disabled={loading} onClick={() => void query.refetch()}>
          {loading ? "Loading saved runs…" : "Refresh library"}
        </button>
      </div>
      <p>Reopen preparation outputs saved in Supabase, even when their local files are gone.</p>
      {disabled && <p>Finish the current preparation before opening another run.</p>}
      {error && <p role="alert">{error}</p>}
      {library && !library.enabled && <p>Connect Supabase to use the saved-run library.</p>}
      {library?.enabled && (
        <>
          <label htmlFor="saved-run-search">Search saved runs</label>
          <input
            id="saved-run-search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Topic or run ID"
          />
          {(library.unreadable_count ?? 0) > 0 && (
            <p role="status">{library.unreadable_count} saved run(s) could not be read.</p>
          )}
          {!loading && matches.length === 0 && (
            <p>
              {library.runs.length === 0
                ? "No saved runs yet. Finished uploads will appear here."
                : "No saved runs match your search."}
            </p>
          )}
          <ul className="saved-run-list">
            {matches.map((run) => (
              <li key={run.id}>
                <h3>{run.topic}</h3>
                <p>
                  {run.started_at && Number.isFinite(Date.parse(run.started_at))
                    ? new Date(run.started_at).toLocaleString()
                    : "Date unavailable"}
                  {" · "}
                  {run.status.replaceAll("_", " ")}
                  {" · "}
                  {run.dataset_count} prepared datasets
                </p>
                <small>Run {run.id}</small>
                <button
                  type="button"
                  disabled={disabled}
                  aria-pressed={selectedId === run.id}
                  onClick={() => onOpen(run.id)}
                >
                  {selectedId === run.id ? "Viewing run" : "Open run"}
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
