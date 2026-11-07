import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { renderWithQuery } from "./test/render";

vi.mock("./api/generated", () => ({
  getHealth: vi.fn(async () => ({
    data: { status: "ok", api_version: "0.1.0", core_version: "0.1.0" },
    error: undefined,
  })),
}));

describe("App", () => {
  it("shows the API health once loaded", async () => {
    renderWithQuery(<App />);
    expect(await screen.findByText(/API ok/)).toBeInTheDocument();
  });
});
