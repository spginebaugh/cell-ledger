import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { renderWithQuery } from "./test/render";

vi.mock("./api/generated", () => ({
  getHealth: vi.fn(async () => ({
    data: { status: "ok", api_version: "0.1.0", core_version: "0.1.0" },
    error: undefined,
  })),
}));

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("App", () => {
  it("shows the API health once loaded", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () => new Response(JSON.stringify({ enabled: false, runs: [], unreadable_count: 0 })),
      ),
    );
    renderWithQuery(<App />);
    expect(await screen.findByText(/API ok/)).toBeInTheDocument();
  });
});

it("browses remote runs without a remembered ID and resets sample evidence on selection", async () => {
  const ids = ["a".repeat(32), "b".repeat(32)];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const id = url.includes(ids[1]) ? ids[1] : ids[0];
      const body =
        url === "/api/runs"
          ? {
              enabled: true,
              unreadable_count: 0,
              runs: ids.map((id, i) => ({
                id,
                topic: `Topic ${i + 1}`,
                status: "complete",
                started_at: "2026-11-07",
                dataset_count: 1,
              })),
            }
          : url.includes("/samples/")
            ? [
                {
                  gsm: id === ids[0] ? "FIRST_SAMPLE" : "SECOND_SAMPLE",
                  evidence: "{}",
                  group: "case",
                },
              ]
            : {
                id,
                status: "complete",
                manifest: {
                  datasets: [
                    {
                      gse: "GSE1",
                      title: "Shared study",
                      status: "needs_review",
                      reasons: [],
                      samples: 1,
                    },
                  ],
                },
                events: [],
                questions: "",
              };
      return new Response(JSON.stringify(body));
    }),
  );
  renderWithQuery(<App />);
  const buttons = await screen.findAllByRole("button", { name: "Open run" });
  fireEvent.click(buttons[0]);
  const summary = await screen.findByText("Inspect samples and evidence");
  fireEvent.click(summary);
  expect(await screen.findByText("FIRST_SAMPLE")).toBeInTheDocument();
  fireEvent.click(await screen.findByRole("button", { name: "Open run" }));
  await waitFor(() => expect(localStorage.getItem("cell-ledger-run")).toBe(ids[1]));
  const nextSummary = await screen.findByText("Inspect samples and evidence");
  fireEvent.click(nextSummary);
  expect(await screen.findByText("SECOND_SAMPLE")).toBeInTheDocument();
  expect(screen.queryByText("FIRST_SAMPLE")).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Download run bundle" })).toHaveAttribute(
    "href",
    `/api/runs/${ids[1]}/bundle`,
  );
  fireEvent.change(screen.getByLabelText("Search saved runs"), { target: { value: "Topic 1" } });
  expect(screen.queryByText("Topic 2")).not.toBeInTheDocument();
});
