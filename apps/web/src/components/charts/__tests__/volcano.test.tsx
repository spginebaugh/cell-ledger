import { fireEvent, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fromRaw } from "@/lib/volcano";
import { Volcano } from "../volcano";

const table = fromRaw({
  n: 3,
  alpha: 0.05,
  lfc_threshold: 1,
  gene_id: ["10", "20", "30"],
  symbol: ["AAA", "BBB", null],
  base_mean: [10, 20, 30],
  log2fc: [3, -3, 0.5],
  padj: [1e-8, 1e-6, 0.5],
});

describe("Volcano click selection", () => {
  const W = 600;
  const H = 420;
  beforeEach(() => {
    // jsdom has no layout: give the chart a width and a stable origin.
    vi.stubGlobal(
      "ResizeObserver",
      class {
        observe() {}
        disconnect() {}
      },
    );
    Object.defineProperty(HTMLElement.prototype, "clientWidth", {
      configurable: true,
      get: () => W,
    });
    HTMLElement.prototype.getBoundingClientRect = () =>
      ({ left: 0, top: 0, width: W, height: H, right: W, bottom: H, x: 0, y: 0 }) as DOMRect;
    HTMLCanvasElement.prototype.getContext = (() => null) as never;
  });
  afterEach(() => vi.unstubAllGlobals());

  it("reports the symbol and GeneID of the point under a click, and ignores unlabelled genes", () => {
    const onSelect = vi.fn();
    const { getByRole } = render(
      <Volcano
        table={table}
        alpha={0.05}
        lfc={1}
        highlight={new Set()}
        focus={null}
        onSelect={onSelect}
      />,
    );
    const canvas = getByRole("img");
    // Sweep a coarse grid; the hit radius is 8px so a 6px step cannot miss a point.
    for (let x = 0; x <= W; x += 6)
      for (let y = 0; y <= H; y += 6) fireEvent.click(canvas, { clientX: x, clientY: y });
    const picked = new Map(onSelect.mock.calls.map(([s, id]) => [s, id]));
    expect(picked).toEqual(
      new Map([
        ["AAA", "10"],
        ["BBB", "20"],
      ]),
    );
  });
});
