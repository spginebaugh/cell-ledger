import { fireEvent, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { SavedRuns } from "./SavedRuns";
import { renderWithQuery } from "./test/render";

afterEach(() => vi.unstubAllGlobals());

it("shows an outage and refreshes to an empty library", async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce(new Response("", { status: 503 }))
    .mockResolvedValueOnce(
      new Response(JSON.stringify({ enabled: true, runs: [], unreadable_count: 0 })),
    );
  vi.stubGlobal("fetch", fetcher);
  renderWithQuery(<SavedRuns selectedId="" disabled={false} refreshKey="" onOpen={vi.fn()} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Could not load saved runs");
  fireEvent.click(screen.getByRole("button", { name: "Refresh library" }));
  expect(await screen.findByText(/No saved runs yet/)).toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it("explains when Supabase is not configured", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () => new Response(JSON.stringify({ enabled: false, runs: [], unreadable_count: 0 })),
    ),
  );
  renderWithQuery(<SavedRuns selectedId="" disabled={false} refreshKey="" onOpen={vi.fn()} />);
  expect(await screen.findByText(/Connect Supabase/)).toBeInTheDocument();
});
