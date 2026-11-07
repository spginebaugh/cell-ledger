import { useEffect, useRef } from "react";
import { cssVar } from "@/lib/theme";

/**
 * A B-DNA double helix built out of wire, turning slowly behind the start page.
 *
 * The molecule is geometry, not a surface. Each sugar-phosphate backbone is a bundle of
 * hairline wires braided loosely around the backbone path, tied by rings and chords, with
 * beads where the wires are sampled. The base pairs are circuit traces: groups of parallel
 * lines running strand to strand with 45° jogs and via pads, some dead-ending part way across
 * the way traces on a board do. Around all of that a plexus of points hugs the molecule, each
 * joined to its nearest neighbours and wired into the beads, with hubs that gather a burst of
 * spokes, long tangents flying off into space, and hexagon and pentagon rings lying in the
 * groove plane like the bases they stand for. A second, smaller molecule hangs out of focus far
 * behind, and a field of free points drifts around the near one, joined wherever two come close.
 *
 * Every vertex is placed in the molecule's own frame as (rise, angle offset from its strand,
 * distance from the axis), so turning the helix is advancing one phase and nothing is rebuilt
 * per frame. The axis is pitched toward the viewer: the far end shrinks away behind the
 * headline and the near end swells past the bottom edge. Depth of field comes from five stacked
 * canvases, each a depth slice with its own CSS blur, sharp where the molecule crosses the focal
 * plane and soft either side, like a macro photograph. Lines and dots are batched per slice into
 * paths keyed by quantised shade, so several thousand segments cost a few dozen stroke calls a
 * frame. Beads, pads and plexus points flash at random like lightning, a fast attack with a
 * flicker and a decay, and a strike often crawls to a neighbour a moment later. With
 * prefers-reduced-motion everything draws once and holds still.
 */
export function HelixBackdrop() {
  const host = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = host.current;
    if (!el) return;
    const canvases = Array.from(el.querySelectorAll("canvas"));
    const ctxs: CanvasRenderingContext2D[] = [];
    for (const c of canvases) {
      const ctx = c.getContext("2d");
      if (ctx) ctxs.push(ctx);
    }
    if (ctxs.length !== SLICES.length) return;

    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
    const darkQuery = window.matchMedia("(prefers-color-scheme: dark)");

    let width = 0;
    let height = 0;
    let dpr = 1;
    let raf = 0;
    let last = 0;
    let now = 0;
    let phase = 0.6;
    let palette = readPalette(darkQuery);
    let scene: Scene | null = null;

    function resize() {
      width = window.innerWidth;
      height = window.innerHeight;
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      for (let i = 0; i < canvases.length; i++) {
        const c = canvases[i];
        const { blur, scale } = SLICES[i];
        // A blurred slice is a smaller canvas scaled up on the compositor and blurred at its
        // own size, so the blur runs over a fraction of the pixels.
        c.width = Math.round(width * dpr * scale);
        c.height = Math.round(height * dpr * scale);
        c.style.width = `${width * scale}px`;
        c.style.height = `${height * scale}px`;
        c.style.transform = scale === 1 ? "" : `scale(${1 / scale})`;
        c.style.filter = blur ? `blur(${blur * scale}px)` : "";
      }
      scene = buildScene(width, height);
      draw();
    }

    function draw() {
      if (scene) render(scene, ctxs, dpr, palette, phase, now, reduced.matches);
    }

    function frame(t: number) {
      now = t;
      if (last && scene) {
        const dt = Math.min(0.1, (t - last) / 1000);
        phase += dt * 0.28; // the turn
        drift(scene.field, dt); // the field: its own clock
        // Strikes arrive at random, a couple a second.
        if (Math.random() < dt * (width < 768 ? 0.8 : 1.6)) spawn(scene, now);
      }
      last = t;
      draw();
      raf = requestAnimationFrame(frame);
    }
    function start() {
      stop();
      if (reduced.matches || document.hidden) {
        draw();
        return;
      }
      last = 0;
      raf = requestAnimationFrame(frame);
    }
    function stop() {
      if (raf) cancelAnimationFrame(raf);
      raf = 0;
    }

    const onTheme = () => {
      palette = readPalette(darkQuery);
      draw();
    };
    const observer = new MutationObserver(onTheme);
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme"],
    });
    darkQuery.addEventListener("change", onTheme);
    reduced.addEventListener("change", start);
    document.addEventListener("visibilitychange", start);
    window.addEventListener("resize", resize);

    resize();
    start();
    return () => {
      stop();
      observer.disconnect();
      darkQuery.removeEventListener("change", onTheme);
      reduced.removeEventListener("change", start);
      document.removeEventListener("visibilitychange", start);
      window.removeEventListener("resize", resize);
    };
  }, []);

  return (
    <div
      ref={host}
      aria-hidden="true"
      className="pointer-events-none fixed inset-0 -z-10 overflow-hidden"
    >
      {SLICES.map((s) => (
        <canvas key={s.name} className="absolute top-0 left-0 block origin-top-left" />
      ))}
    </div>
  );
}

const TAU = Math.PI * 2;

/**
 * Depth slices, far to near: each is a canvas carrying its own blur. A blurred slice is drawn
 * at a fraction of the resolution, which the blur hides and which keeps compositing cheap.
 */
const SLICES = [
  { name: "far", blur: 2.8, scale: 0.5 },
  { name: "behind", blur: 1.3, scale: 0.75 },
  { name: "focus", blur: 0, scale: 1 },
  { name: "ahead", blur: 1.1, scale: 0.75 },
  { name: "near", blur: 2.6, scale: 0.5 },
];

type RGB = [number, number, number];
type Strand = 0 | 1;
type Flash = { start: number; dur: number };
type Palette = ReturnType<typeof readPalette>;

/** A vertex pinned to the molecule: rise along the axis, angle offset from its strand's winding, distance from the axis. */
type Pin = { t: number; a: number; r: number };
/** A line between two pins, coloured by a strand; `d` is its length in the molecule's frame when a style needs it. */
type Seg = { a: number; b: number; s: Strand; d?: number };
type NodeKind = "bead" | "pad" | "mesh";
/** A pane between three plexus points that are joined in a ring. */
type Tri = { a: number; b: number; c: number; s: Strand };
type MolNode = {
  pin: number;
  s: Strand;
  size: number;
  kind: NodeKind;
  big: boolean;
  nbrs: number[];
};

type MolConfig = {
  radius: number;
  pitch: number;
  tube: number;
  tStart: number;
  tEnd: number;
  step: number;
  groove: number;
  wires: number;
  density: number;
  /** Multiplier on every alpha. */
  gain: number;
  phase0: number;
  /** Where the axis midpoint sits, in the tilted screen frame. */
  dx: number;
  dy: number;
  /** Added to every depth: pushes the whole molecule out of focus. */
  depthBias: number;
  bloom: boolean;
};

type Molecule = {
  cfg: MolConfig;
  pins: Pin[];
  wires: Seg[];
  ties: Seg[];
  traces: Seg[];
  mesh: Seg[];
  meshMax: number;
  strays: Seg[];
  rings: Seg[];
  faces: Tri[];
  bloom: Seg[];
  nodes: MolNode[];
  /** Node indices of beads the free field may wire into. */
  beadSample: number[];
  // Per-frame scratch: screen position and scale, depth, facing, end fade, strike intensity,
  // and the position in the molecule's frame.
  X: Float32Array;
  Y: Float32Array;
  S: Float32Array;
  Z: Float32Array;
  N: Float32Array;
  F: Float32Array;
  I: Float32Array;
  LX: Float32Array;
  LY: Float32Array;
  LZ: Float32Array;
  flashes: Map<number, Flash>;
};

type FieldPoint = { x: number; y: number; z: number; vx: number; vy: number; vz: number };
type Field = {
  pts: FieldPoint[];
  hx: number;
  hy: number;
  hz: number;
  yMid: number;
  linkDist: number;
  reach: number;
  tStart: number;
  tEnd: number;
  X: Float32Array;
  Y: Float32Array;
  S: Float32Array;
  Z: Float32Array;
  N: Float32Array;
  F: Float32Array;
  I: Float32Array;
  flashes: Map<number, Flash>;
};

type View = {
  width: number;
  height: number;
  /** Screen centre of the tilted frame. */
  cx: number;
  cy: number;
  /** Roll of the frame on screen. */
  tilt: number;
  /** The axis is pitched toward the viewer by this much. */
  pitchAngle: number;
  focal: number;
  /** Depth thresholds between slices, far to near. */
  slice: number[];
  /** Culling radius², in the tilted frame. */
  bound2: number;
  strength: number;
};

type Scene = { view: View; mols: Molecule[]; field: Field };

// ------------------------------------------------------------------------------------ building

function buildScene(width: number, height: number): Scene {
  const narrow = width < 768;
  const R = Math.max(44, Math.min(width, height) * (narrow ? 0.13 : 0.17));
  const view: View = {
    width,
    height,
    // The focal band sits in the open space below and to the right of the question panel.
    cx: narrow ? width * 0.95 : width * 0.8,
    cy: narrow ? height * 0.5 : height * 0.71,
    tilt: narrow ? -0.3 : -0.55,
    pitchAngle: 0.45,
    focal: R * 7,
    slice: [2 * R, 0.8 * R, -0.8 * R, -1.8 * R],
    bound2: (Math.hypot(width, height) * 0.5 + 80) ** 2,
    strength: narrow ? 0.55 : 1,
  };
  const main: MolConfig = {
    radius: R,
    pitch: R * 3.4, // rise per full turn (B-DNA: pitch ≈ 3.4 nm, radius ≈ 1 nm)
    tube: Math.max(2.2, R * 0.075),
    // The far end is longer than the near one: it shrinks away, the near end swells off-screen.
    tStart: -height * 1.1,
    tEnd: height * 0.75,
    step: narrow ? 9 : 7,
    groove: 2.2, // radians between the backbones: a major and a minor groove
    wires: narrow ? 4 : 7,
    density: narrow ? 0.45 : 1,
    gain: 1,
    phase0: 0,
    dx: 0,
    dy: 0,
    depthBias: 0,
    bloom: true,
  };
  const mols = [buildMolecule(main, mulberry(7))];
  if (!narrow) {
    const r = R * 0.5;
    // Bottom left of the page, well out of focus.
    const ghost = toFrame(view, width * 0.23, height * 0.8);
    mols.push(
      buildMolecule(
        {
          radius: r,
          pitch: r * 3.4,
          tube: Math.max(1.6, r * 0.075),
          tStart: -height * 0.4,
          tEnd: height * 0.4,
          step: 9,
          groove: 2.2,
          wires: 4,
          density: 0.4,
          gain: 0.4,
          phase0: 2.3,
          dx: ghost.x,
          dy: ghost.y,
          depthBias: R * 2.6,
          bloom: false,
        },
        mulberry(11),
      ),
    );
  }
  return { view, mols, field: seedField(main, narrow ? 60 : 210) };
}

/** A screen position taken into the tilted frame centred on the near molecule. */
function toFrame(v: View, sx: number, sy: number) {
  const dx = sx - v.cx;
  const dy = sy - v.cy;
  const c = Math.cos(-v.tilt);
  const s = Math.sin(-v.tilt);
  return { x: dx * c - dy * s, y: dx * s + dy * c };
}

/** A small deterministic generator, so the structure is the same on every build. */
function mulberry(seed: number) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function buildMolecule(cfg: MolConfig, rnd: () => number): Molecule {
  const { radius: R, tube, pitch, groove: g } = cfg;
  const pins: Pin[] = [];
  const wind = (t: number) => (t / pitch) * TAU;
  const pin = (t: number, a: number, r: number) => pins.push({ t, a, r }) - 1;
  /** A pin from a point in the molecule's frame at phase 0. */
  const pinAt = (x: number, y: number, z: number) =>
    pin(y, Math.atan2(z, x) - wind(y), Math.hypot(x, z));
  const cart = (i: number) => {
    const p = pins[i];
    const th = wind(p.t) + p.a;
    return { x: Math.cos(th) * p.r, y: p.t, z: Math.sin(th) * p.r };
  };
  const dist = (i: number, j: number) => {
    const a = cart(i);
    const b = cart(j);
    return Math.hypot(b.x - a.x, b.y - a.y, b.z - a.z);
  };
  const strandAngle = [0, g];
  const wires: Seg[] = [];
  const ties: Seg[] = [];
  const traces: Seg[] = [];
  const mesh: Seg[] = [];
  const strays: Seg[] = [];
  const rings: Seg[] = [];
  const bloom: Seg[] = [];
  const nodes: MolNode[] = [];
  const addNode = (p: number, s: Strand, size: number, kind: NodeKind, big = false) =>
    nodes.push({ pin: p, s, size, kind, big, nbrs: [] }) - 1;
  const link = (i: number, j: number) => {
    nodes[i].nbrs.push(j);
    nodes[j].nbrs.push(i);
  };
  const samples = Math.floor((cfg.tEnd - cfg.tStart) / cfg.step) + 1;

  // ------------------------------------------------------------------ the backbone bundles
  // Each strand is W wires wound loosely around the backbone path. A wire sits at an angle on
  // the bundle's cross-section that drifts slowly along the rise, so the wires braid over one
  // another; rings and chords tie the bundle together now and then, and beads of three sizes
  // sit where the wires are sampled.
  const W = cfg.wires;
  for (const s of [0, 1] as const) {
    const a0 = strandAngle[s];
    let prevC = -1;
    for (let k = 0; k < samples; k += 2) {
      const p = pin(cfg.tStart + k * cfg.step, a0, R);
      if (prevC >= 0) bloom.push({ a: prevC, b: p, s });
      prevC = p;
    }
    const ringPins: number[][] = Array.from({ length: samples }, () => []);
    for (let w = 0; w < W; w++) {
      const alpha0 = (TAU * w) / W + (rnd() - 0.5) * 0.5;
      const spread = tube * (1.2 + rnd() * 0.9);
      const wob = 0.35 + rnd() * 0.5;
      const wobF = pitch * (0.3 + rnd() * 0.3);
      const ph = rnd() * TAU;
      let prev = -1;
      let lastBead = -1;
      for (let k = 0; k < samples; k++) {
        const t = cfg.tStart + k * cfg.step;
        const al = alpha0 + wob * Math.sin(t / wobF + ph);
        const p = pin(t, a0 + (Math.cos(al) * spread) / R, R + Math.sin(al) * spread);
        ringPins[k][w] = p;
        if (prev >= 0) wires.push({ a: prev, b: p, s });
        prev = p;
        if (k % 3 === 0 && rnd() < 0.55) {
          const u = rnd();
          const n = addNode(p, s, u < 0.7 ? 0.7 : u < 0.92 ? 1.3 : 2.6, "bead");
          if (lastBead >= 0) link(lastBead, n);
          lastBead = n;
        }
      }
    }
    for (let k = 0; k < samples; k++) {
      const ring = ringPins[k];
      if (k % 4 === 0) {
        for (let w = 0; w < W; w++)
          if (rnd() < 0.6) ties.push({ a: ring[w], b: ring[(w + 1) % W], s });
      }
      if (k % 6 === 3) {
        const w = Math.floor(rnd() * W);
        ties.push({ a: ring[w], b: ring[(w + (W >> 1)) % W], s });
      }
      if (k % 5 === 1 && k + 1 < samples) {
        const w = Math.floor(rnd() * W);
        ties.push({ a: ring[w], b: ringPins[k + 1][(w + 1) % W], s });
      }
    }
  }

  // --------------------------------------------------------------- base pairs as traces
  // Twelve rungs per turn. Each is a group of parallel traces across the groove in the plane
  // of the chord between the strands and the axis. A trace runs straight, jogs at 45° by one
  // or two track widths, and runs on; most start and end on a backbone, some dead-end at a
  // pad part way across, and corners now and then carry a pad too.
  const L = 2 * R * Math.sin(g / 2);
  const chord = (u: number, v: number, t: number) => {
    const x = 1 - u + u * Math.cos(g);
    const z = u * Math.sin(g);
    return pin(t + v, Math.atan2(z, x), R * Math.hypot(x, z));
  };
  const rungGap = pitch / 12;
  const rungs = Math.floor((cfg.tEnd - cfg.tStart) / rungGap);
  for (let n = 0; n < rungs; n++) {
    const t = cfg.tStart + (n + 0.5) * rungGap;
    const K = 2 + Math.floor(rnd() * 5);
    const gap = tube * 0.7;
    const rungPads: number[] = [];
    for (let k = 0; k < K; k++) {
      let v = (k - (K - 1) / 2) * gap;
      const fromA = rnd() < 0.85;
      const toB = rnd() < 0.85;
      let u = fromA ? 0 : 0.12 + rnd() * 0.2;
      const pts: [number, number][] = [[u, v]];
      const jogs = 1 + Math.floor(rnd() * 2);
      for (let j = 0; j < jogs; j++) {
        const uj = 0.2 + (j + rnd() * 0.8) * (0.6 / jogs);
        if (uj <= u) continue;
        pts.push([uj, v]);
        const dv = (rnd() < 0.5 ? -1 : 1) * gap * (rnd() < 0.7 ? 1 : 2);
        v += dv;
        u = uj + Math.abs(dv) / L;
        pts.push([u, v]);
      }
      pts.push([toB ? 1 : Math.min(0.92, u + 0.08 + rnd() * 0.2), v]);
      let prev = -1;
      for (let i = 0; i < pts.length; i++) {
        const [pu, pv] = pts[i];
        const p = chord(pu, pv, t);
        const s: Strand = pu < 0.5 ? 0 : 1;
        if (prev >= 0) traces.push({ a: prev, b: p, s });
        const end = i === 0 || i === pts.length - 1;
        const dangling = (i === 0 && !fromA) || (i === pts.length - 1 && !toB);
        if (dangling || (!end && rnd() < 0.3)) {
          rungPads.push(addNode(p, s, dangling ? 2.2 : 1.2, "pad", dangling));
        }
        prev = p;
      }
    }
    for (let i = 1; i < rungPads.length; i++) link(rungPads[i - 1], rungPads[i]);
  }

  // --------------------------------------------------------------------------- the plexus
  // Points scattered around each strand: most just outside the bundle, some into the groove,
  // a few flung well out. Each joins its two or three nearest neighbours, most join the nearest
  // bead on a wire, and a handful become hubs that gather a burst of spokes.
  const M = Math.round(480 * cfg.density);
  const meshNodes: number[] = [];
  for (let i = 0; i < M; i++) {
    const s = (i & 1) as Strand;
    const t = cfg.tStart + rnd() * (cfg.tEnd - cfg.tStart);
    const gauss = rnd() + rnd() + rnd() - 1.5;
    const u = rnd();
    const dr =
      u < 0.22
        ? -tube * (1 + rnd() * 2.5)
        : u < 0.9
          ? tube * (1.2 + Math.abs(gauss) * 3.5)
          : tube * 4 + rnd() * R * 0.9;
    const p = pin(t, strandAngle[s] + (gauss * tube * 2.2) / R, R + dr);
    const sz = rnd();
    meshNodes.push(addNode(p, s, sz < 0.72 ? 0.8 : sz < 0.93 ? 1.5 : 3, "mesh", sz >= 0.93));
  }
  const meshMax = R * 1.3;
  const seen = new Set<string>();
  const join = (i: number, j: number) => {
    const key = i < j ? `${i}:${j}` : `${j}:${i}`;
    if (seen.has(key)) return;
    seen.add(key);
    const a = nodes[meshNodes[i]];
    const b = nodes[meshNodes[j]];
    mesh.push({ a: a.pin, b: b.pin, s: a.s, d: dist(a.pin, b.pin) });
    link(meshNodes[i], meshNodes[j]);
  };
  for (let i = 0; i < M; i++) {
    const near: { j: number; d: number }[] = [];
    for (let j = 0; j < M; j++) {
      if (j !== i) near.push({ j, d: dist(nodes[meshNodes[i]].pin, nodes[meshNodes[j]].pin) });
    }
    near.sort((a, b) => a.d - b.d);
    const hub = rnd() < 0.07;
    if (hub) {
      nodes[meshNodes[i]].size = 3;
      nodes[meshNodes[i]].big = true;
    }
    const k = hub ? 9 : 2 + Math.floor(rnd() * 2.6);
    const reach = hub ? meshMax * 1.4 : meshMax;
    for (let m = 0; m < k && m < near.length && near[m].d < reach; m++) join(i, near[m].j);
  }
  const beads = nodes.map((n, i) => (n.kind === "bead" ? i : -1)).filter((i) => i >= 0);
  for (const ni of meshNodes) {
    if (rnd() < 0.35) continue;
    let best = -1;
    let bd = tube * 7;
    for (const bi of beads) {
      const d = dist(nodes[ni].pin, nodes[bi].pin);
      if (d < bd) {
        bd = d;
        best = bi;
      }
    }
    if (best >= 0) {
      mesh.push({ a: nodes[ni].pin, b: nodes[best].pin, s: nodes[ni].s, d: bd });
      link(ni, best);
    }
  }

  // Faces: wherever three plexus points are joined in a ring, a faint pane between them, so
  // the mesh reads faceted.
  const faces: Tri[] = [];
  const adj: Set<number>[] = Array.from({ length: M }, () => new Set<number>());
  for (const key of seen) {
    const [i, j] = key.split(":").map(Number);
    adj[i].add(j);
    adj[j].add(i);
  }
  for (let i = 0; i < M; i++) {
    for (const j of adj[i]) {
      if (j <= i) continue;
      for (const k of adj[j]) {
        if (k <= j || !adj[i].has(k)) continue;
        const a = nodes[meshNodes[i]];
        faces.push({ a: a.pin, b: nodes[meshNodes[j]].pin, c: nodes[meshNodes[k]].pin, s: a.s });
      }
    }
  }

  // ------------------------------------------------------------------------ the sprays
  // Long tangents flying off the plexus, mostly outward with a lean along the surface, half of
  // them ending in a speck.
  for (const ni of meshNodes) {
    if (rnd() > 0.4) continue;
    const p0 = pins[nodes[ni].pin];
    const o = cart(nodes[ni].pin);
    const th = wind(p0.t) + p0.a;
    const w1 = 0.4 + rnd() * 0.8;
    const w2 = (rnd() - 0.5) * 1.4;
    const w3 = (rnd() - 0.5) * 1.6;
    const dir = {
      x: Math.cos(th) * w1 - Math.sin(th) * w2,
      y: w3,
      z: Math.sin(th) * w1 + Math.cos(th) * w2,
    };
    const m = Math.hypot(dir.x, dir.y, dir.z);
    const len = R * (0.5 + rnd() * 1.5);
    const e = pinAt(o.x + (dir.x / m) * len, o.y + (dir.y / m) * len, o.z + (dir.z / m) * len);
    strays.push({ a: nodes[ni].pin, b: e, s: nodes[ni].s });
    if (rnd() < 0.5) addNode(e, nodes[ni].s, 0.7, "mesh");
  }

  // ------------------------------------------------------------------------- ring motifs
  // Hexagons and pentagons lying in the groove plane, half of them fused in pairs on a shared
  // edge, the way a purine is a hexagon fused to a pentagon.
  const ringCount = Math.round(18 * cfg.density);
  for (let i = 0; i < ringCount; i++) {
    const t = cfg.tStart + rnd() * (cfg.tEnd - cfg.tStart);
    const u = 0.2 + rnd() * 0.6;
    const W0 = wind(t);
    const ax = Math.cos(W0);
    const az = Math.sin(W0);
    const bx = Math.cos(W0 + g);
    const bz = Math.sin(W0 + g);
    // Plane basis: e1 along the chord between the strands (in x, z), e2 along the axis.
    let ex = bx - ax;
    let ez = bz - az;
    const em = Math.hypot(ex, ez);
    ex /= em;
    ez /= em;
    const cx = R * ((1 - u) * ax + u * bx);
    const cz = R * ((1 - u) * az + u * bz);
    const s: Strand = u < 0.5 ? 0 : 1;
    const sides = rnd() < 0.3 ? 5 : 6;
    const rho = tube * (1.5 + rnd() * 1.6);
    const rot = rnd() * TAU;
    const ring = (px: number, pz: number, py: number, n: number, radius: number, rot0: number) => {
      const v: number[] = [];
      for (let k = 0; k < n; k++) {
        const ang = rot0 + (k / n) * TAU;
        const c = Math.cos(ang) * radius;
        const sn = Math.sin(ang) * radius;
        v.push(pinAt(px + c * ex, py + sn, pz + c * ez));
      }
      for (let k = 0; k < n; k++) {
        rings.push({ a: v[k], b: v[(k + 1) % n], s });
        if (rnd() < 0.5) addNode(v[k], s, 0.7, "mesh");
      }
    };
    ring(cx, cz, t, sides, rho, rot);
    if (rnd() < 0.5) {
      // The second ring shares edge 0–1: same side length, centres an apothem each away.
      const n2 = rnd() < 0.5 ? 5 : 6;
      const side = 2 * rho * Math.sin(Math.PI / sides);
      const rho2 = side / (2 * Math.sin(Math.PI / n2));
      const ap = rho * Math.cos(Math.PI / sides) + rho2 * Math.cos(Math.PI / n2);
      const dir = rot + Math.PI / sides;
      ring(
        cx + Math.cos(dir) * ap * ex,
        cz + Math.cos(dir) * ap * ez,
        t + Math.sin(dir) * ap,
        n2,
        rho2,
        dir + Math.PI - Math.PI / n2,
      );
    }
  }

  const n = pins.length;
  return {
    cfg,
    pins,
    wires,
    ties,
    traces,
    mesh,
    meshMax,
    strays,
    rings,
    faces,
    bloom,
    nodes,
    beadSample: beads.filter((_, i) => i % 2 === 0),
    X: new Float32Array(n),
    Y: new Float32Array(n),
    S: new Float32Array(n),
    Z: new Float32Array(n),
    N: new Float32Array(n),
    F: new Float32Array(n),
    I: new Float32Array(n),
    LX: new Float32Array(n),
    LY: new Float32Array(n),
    LZ: new Float32Array(n),
    flashes: new Map(),
  };
}

/** Free points drifting in a box around the near molecule, in its frame. */
function seedField(cfg: MolConfig, count: number): Field {
  const hx = cfg.radius * 4.5;
  const hz = cfg.radius * 2;
  const yMid = (cfg.tStart + cfg.tEnd) / 2;
  const hy = ((cfg.tEnd - cfg.tStart) / 2) * 0.9;
  const pts: FieldPoint[] = Array.from({ length: count }, () => ({
    x: (Math.random() * 2 - 1) * hx,
    y: yMid + (Math.random() * 2 - 1) * hy,
    z: (Math.random() * 2 - 1) * hz,
    vx: (Math.random() * 2 - 1) * 7,
    vy: (Math.random() * 2 - 1) * 9,
    vz: (Math.random() * 2 - 1) * 5,
  }));
  return {
    pts,
    hx,
    hy,
    hz,
    yMid,
    linkDist: cfg.radius * 1.9,
    reach: cfg.radius * 1.5,
    tStart: cfg.tStart,
    tEnd: cfg.tEnd,
    X: new Float32Array(count),
    Y: new Float32Array(count),
    S: new Float32Array(count),
    Z: new Float32Array(count),
    N: new Float32Array(count),
    F: new Float32Array(count),
    I: new Float32Array(count),
    flashes: new Map(),
  };
}

function drift(f: Field, dt: number) {
  for (const p of f.pts) {
    p.x += p.vx * dt;
    p.y += p.vy * dt;
    p.z += p.vz * dt;
    if (p.x < -f.hx || p.x > f.hx) p.vx = -p.vx;
    if (p.y < f.yMid - f.hy || p.y > f.yMid + f.hy) p.vy = -p.vy;
    if (p.z < -f.hz || p.z > f.hz) p.vz = -p.vz;
  }
}

// ----------------------------------------------------------------------------------- lightning

function spawn(scene: Scene, now: number) {
  const dur = 900 + Math.random() * 900;
  const r = Math.random();
  if (r < 0.3 && scene.field.pts.length) {
    strikeField(scene.field, Math.floor(Math.random() * scene.field.pts.length), now, dur, 3);
    return;
  }
  const m = r < 0.85 || scene.mols.length < 2 ? scene.mols[0] : scene.mols[1];
  if (m.nodes.length) strikeNode(m, Math.floor(Math.random() * m.nodes.length), now, dur, 3);
}

/** Strike a node now, and often a neighbour a third of a second or more later. */
function strikeNode(m: Molecule, ni: number, at: number, dur: number, hops: number) {
  m.flashes.set(ni, { start: at, dur });
  if (hops <= 0 || Math.random() > 0.75) return;
  const nb = m.nodes[ni].nbrs;
  if (!nb.length) return;
  const next = nb[Math.floor(Math.random() * nb.length)];
  strikeNode(m, next, at + 320 + Math.random() * 380, dur * 0.9, hops - 1);
}

function strikeField(f: Field, i: number, at: number, dur: number, hops: number) {
  f.flashes.set(i, { start: at, dur });
  if (hops <= 0 || Math.random() > 0.75) return;
  const p = f.pts[i];
  let best = -1;
  let bestD = f.linkDist;
  for (let j = 0; j < f.pts.length; j++) {
    if (j === i) continue;
    const q = f.pts[j];
    const d = Math.hypot(q.x - p.x, q.y - p.y, q.z - p.z);
    if (d < bestD) {
      bestD = d;
      best = j;
    }
  }
  if (best >= 0) strikeField(f, best, at + 320 + Math.random() * 380, dur * 0.9, hops - 1);
}

/** 0 before it lands, −1 once spent; otherwise up to 1 at the peak with a flicker on the way down. */
function envelope(f: Flash, now: number): number {
  const age = now - f.start;
  if (age < 0) return 0;
  if (age > f.dur) return -1;
  const u = age / f.dur;
  const env = u < 0.12 ? u / 0.12 : 1 - (u - 0.12) / 0.88;
  return env * (0.78 + 0.22 * Math.sin(age * 0.035) * Math.sin(age * 0.009));
}

// ----------------------------------------------------------------------------------- rendering

/** One depth slice's worth of marks, batched by style into a few paths. */
class Slice {
  private strokes = new Map<string, { path: Path2D; style: string; width: number }>();
  private fills = new Map<string, { path: Path2D; style: string }>();
  private panes = new Map<string, { path: Path2D; style: string }>();
  /** Marks drawn one by one on top: the ones that are lit. */
  hot: ((ctx: CanvasRenderingContext2D) => void)[] = [];

  line(key: string, ax: number, ay: number, bx: number, by: number, style: () => [string, number]) {
    const e = this.stroke(key, style);
    e.path.moveTo(ax, ay);
    e.path.lineTo(bx, by);
  }
  circle(key: string, x: number, y: number, r: number, style: () => [string, number]) {
    const e = this.stroke(key, style);
    e.path.moveTo(x + r, y);
    e.path.arc(x, y, r, 0, TAU);
  }
  dot(key: string, x: number, y: number, r: number, style: () => string) {
    const e = this.fill(this.fills, key, style);
    e.path.moveTo(x + r, y);
    e.path.arc(x, y, r, 0, TAU);
  }
  /** A filled triangle, drawn under everything else in the slice. */
  pane(
    key: string,
    ax: number,
    ay: number,
    bx: number,
    by: number,
    cx: number,
    cy: number,
    style: () => string,
  ) {
    const e = this.fill(this.panes, key, style);
    e.path.moveTo(ax, ay);
    e.path.lineTo(bx, by);
    e.path.lineTo(cx, cy);
    e.path.closePath();
  }
  private fill(
    into: Map<string, { path: Path2D; style: string }>,
    key: string,
    style: () => string,
  ) {
    let e = into.get(key);
    if (!e) {
      e = { path: new Path2D(), style: style() };
      into.set(key, e);
    }
    return e;
  }
  private stroke(key: string, style: () => [string, number]) {
    let e = this.strokes.get(key);
    if (!e) {
      const [st, w] = style();
      e = { path: new Path2D(), style: st, width: w };
      this.strokes.set(key, e);
    }
    return e;
  }
  flush(ctx: CanvasRenderingContext2D) {
    for (const e of this.panes.values()) {
      ctx.fillStyle = e.style;
      ctx.fill(e.path);
    }
    for (const e of this.strokes.values()) {
      ctx.strokeStyle = e.style;
      ctx.lineWidth = e.width;
      ctx.stroke(e.path);
    }
    for (const e of this.fills.values()) {
      ctx.fillStyle = e.style;
      ctx.fill(e.path);
    }
    for (const h of this.hot) h(ctx);
  }
}

function sliceOf(z: number, v: View): number {
  const t = v.slice;
  return z > t[0] ? 0 : z > t[1] ? 1 : z > t[2] ? 2 : z > t[3] ? 3 : 4;
}

function render(
  scene: Scene,
  ctxs: CanvasRenderingContext2D[],
  dpr: number,
  pal: Palette,
  phase: number,
  now: number,
  still: boolean,
) {
  const v = scene.view;
  const slices = SLICES.map(() => new Slice());
  for (const m of scene.mols) {
    place(m, v, phase);
    drawMolecule(m, v, pal, slices, still, now);
  }
  drawField(scene, pal, slices, still, now);

  for (let i = 0; i < ctxs.length; i++) {
    const ctx = ctxs[i];
    const k = dpr * SLICES[i].scale;
    ctx.setTransform(k, 0, 0, k, 0, 0);
    ctx.clearRect(0, 0, v.width, v.height);
    ctx.translate(v.cx, v.cy);
    ctx.rotate(v.tilt);
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    if (i === 0) {
      // A soft pool of light behind the molecule.
      const pool = ctx.createRadialGradient(0, 0, 0, 0, 0, Math.max(v.width, v.height) * 0.42);
      pool.addColorStop(0, rgba(pal.glow, (pal.dark ? 0.1 : 0.07) * v.strength * pal.gain));
      pool.addColorStop(1, rgba(pal.glow, 0));
      ctx.fillStyle = pool;
      ctx.fillRect(-v.width * 1.5, -v.height * 1.5, v.width * 3, v.height * 3);
    }
    slices[i].flush(ctx);
  }
}

/** Turn, pitch and project every pin of a molecule into the tilted screen frame. */
function place(m: Molecule, v: View, phase: number) {
  const { pins, cfg } = m;
  const cph = Math.cos(v.pitchAngle);
  const sph = Math.sin(v.pitchAngle);
  const k = TAU / cfg.pitch;
  const ph = phase + cfg.phase0;
  const fadeLen = (cfg.tEnd - cfg.tStart) * 0.2;
  for (let i = 0; i < pins.length; i++) {
    const p = pins[i];
    const th = p.t * k + ph + p.a;
    const x = Math.cos(th) * p.r;
    const z = Math.sin(th) * p.r;
    const y = p.t;
    const yp = y * cph + z * sph;
    const zp = -y * sph + z * cph + cfg.depthBias;
    const s = v.focal / (v.focal + zp);
    m.LX[i] = x;
    m.LY[i] = y;
    m.LZ[i] = z;
    m.X[i] = x * s + cfg.dx;
    m.Y[i] = yp * s + cfg.dy;
    m.S[i] = s;
    m.Z[i] = zp;
    m.N[i] = Math.max(0, Math.min(1, (1 - z / cfg.radius) / 2)); // 1 facing the viewer
    const e = Math.max(0, Math.min(1, (p.t - cfg.tStart) / fadeLen, (cfg.tEnd - p.t) / fadeLen));
    m.F[i] = e * e * (3 - 2 * e);
  }
}

type SegStyle = {
  colour: (s: Strand, n: number) => RGB;
  alpha: (n: number, e: Seg) => number;
  width: (n: number, scale: number) => number;
};

function drawMolecule(
  m: Molecule,
  v: View,
  pal: Palette,
  slices: Slice[],
  still: boolean,
  now: number,
) {
  const { cfg } = m;
  const gain = cfg.gain * v.strength * pal.gain;
  const ramps = [pal.rampA, pal.rampB];
  const bases = [pal.baseA, pal.baseB];
  const webs = [tone(pal, pal.rampA, 0.8), tone(pal, pal.rampB, 0.8)];

  m.I.fill(0);
  if (still) {
    for (let i = 0; i < m.nodes.length; i += 29) m.I[m.nodes[i].pin] = 0.6;
  } else {
    for (const [ni, f] of m.flashes) {
      const I = envelope(f, now);
      if (I < 0) m.flashes.delete(ni);
      else if (I > 0) {
        const p = m.nodes[ni].pin;
        if (I > m.I[p]) m.I[p] = I;
      }
    }
  }

  const segs = (list: Seg[], tag: string, st: SegStyle) => {
    for (const e of list) {
      const ax = m.X[e.a];
      const ay = m.Y[e.a];
      const bx = m.X[e.b];
      const by = m.Y[e.b];
      if (ax * ax + ay * ay > v.bound2 && bx * bx + by * by > v.bound2) continue;
      const f = (m.F[e.a] + m.F[e.b]) * 0.5;
      if (f < 0.03) continue;
      const n = (m.N[e.a] + m.N[e.b]) * 0.5;
      const sc = (m.S[e.a] + m.S[e.b]) * 0.5;
      const slice = slices[sliceOf((m.Z[e.a] + m.Z[e.b]) * 0.5, v)];
      const I = Math.max(m.I[e.a], m.I[e.b]);
      const qn = Math.round(n * 3) / 3;
      const a = st.alpha(qn, e) * f * gain;
      const w = st.width(qn, sc);
      if (I > 0.02) {
        slice.hot.push((ctx) => {
          ctx.strokeStyle = rgba(
            mix(st.colour(e.s, qn), pal.highlight, I),
            Math.min(1, a + 0.75 * I * f * gain),
          );
          ctx.lineWidth = w + 1.2 * I;
          ctx.beginPath();
          ctx.moveTo(ax, ay);
          ctx.lineTo(bx, by);
          ctx.stroke();
        });
        continue;
      }
      const qa = Math.round(a * 25) / 25;
      if (qa <= 0) continue;
      const qw = Math.round(w * 4) / 4;
      slice.line(`${tag}${e.s}|${qn}|${qa}|${qw}`, ax, ay, bx, by, () => [
        rgba(st.colour(e.s, qn), qa),
        qw,
      ]);
    }
  };

  if (cfg.bloom) {
    // A faint glow along each backbone, so the bundle reads as one luminous strand.
    segs(m.bloom, "B", {
      colour: (s, n) => ramp(ramps[s], 0.4 + 0.4 * n),
      alpha: (n) => 0.02 + 0.03 * n,
      width: (_n, sc) => cfg.tube * 3 * sc,
    });
  }
  for (const t of m.faces) {
    const ax = m.X[t.a];
    const ay = m.Y[t.a];
    const bx = m.X[t.b];
    const by = m.Y[t.b];
    const cx = m.X[t.c];
    const cy = m.Y[t.c];
    if (
      ax * ax + ay * ay > v.bound2 &&
      bx * bx + by * by > v.bound2 &&
      cx * cx + cy * cy > v.bound2
    ) {
      continue;
    }
    const f = (m.F[t.a] + m.F[t.b] + m.F[t.c]) / 3;
    if (f < 0.03) continue;
    const qn = Math.round(((m.N[t.a] + m.N[t.b] + m.N[t.c]) / 3) * 3) / 3;
    const a = (pal.dark ? 0.035 : 0.05) * (0.4 + 0.6 * qn) * f * gain;
    const qa = Math.round(a * 50) / 50;
    if (qa <= 0) continue;
    const slice = slices[sliceOf((m.Z[t.a] + m.Z[t.b] + m.Z[t.c]) / 3, v)];
    slice.pane(`A${t.s}|${qa}`, ax, ay, bx, by, cx, cy, () => rgba(webs[t.s], qa));
  }
  segs(m.mesh, "M", {
    colour: (s) => webs[s],
    alpha: (n, e) => (0.16 + 0.4 * Math.max(0, 1 - (e.d ?? 0) / m.meshMax)) * (0.35 + 0.65 * n),
    width: () => 0.6,
  });
  segs(m.strays, "S", {
    colour: (s) => tone(pal, ramps[s], 0.62),
    alpha: (n) => 0.09 * (0.4 + 0.6 * n),
    width: () => 0.5,
  });
  segs(m.rings, "R", {
    colour: (s) => mix(webs[s], webs[1 - s], 0.35),
    alpha: (n) => 0.16 * (0.3 + 0.7 * n),
    width: () => 0.6,
  });
  segs(m.ties, "T", {
    colour: (s, n) => tone(pal, ramps[s], 0.5 + 0.4 * n),
    alpha: (n) => 0.14 + 0.36 * n,
    width: () => 0.5,
  });
  segs(m.traces, "C", {
    colour: (s, n) => shade(bases[s], 0.3 + 0.7 * n),
    alpha: (n) => 0.32 + 0.55 * n,
    width: (n) => 0.6 + 0.4 * n,
  });
  segs(m.wires, "W", {
    colour: (s, n) => tone(pal, ramps[s], 0.45 + 0.5 * n),
    alpha: (n) => 0.22 + 0.62 * n,
    width: (n) => 0.55 + 0.45 * n,
  });

  for (const nd of m.nodes) {
    const p = nd.pin;
    const x = m.X[p];
    const y = m.Y[p];
    if (x * x + y * y > v.bound2) continue;
    const f = m.F[p];
    if (f < 0.03) continue;
    const sc = m.S[p];
    const I = m.I[p];
    const slice = slices[sliceOf(m.Z[p], v)];
    const qn = Math.round(m.N[p] * 3) / 3;
    if (nd.kind === "pad") {
      // A via: a ring with a bright centre.
      const r = (1.5 + (nd.big ? 1.5 : 0) + 0.6 * qn) * sc;
      const a = (0.4 + 0.45 * qn) * f * gain;
      if (I > 0.02) {
        slice.hot.push((ctx) =>
          flare(ctx, x, y, r, tone(pal, ramps[nd.s], 0.9), a, I, f * gain, pal),
        );
        continue;
      }
      const qa = Math.round(a * 25) / 25;
      if (qa <= 0) continue;
      slice.circle(`V${nd.s}|${qn}|${qa}`, x, y, r, () => [
        rgba(tone(pal, ramps[nd.s], 0.9), qa),
        0.7,
      ]);
      slice.dot(`v|${qa}`, x, y, 0.8 * sc, () => rgba(pal.highlight, qa));
      continue;
    }
    const r = nd.size * (0.7 + 0.5 * qn) * sc;
    const a = (0.45 + 0.5 * qn) * f * gain;
    if (I > 0.02) {
      slice.hot.push((ctx) =>
        flare(ctx, x, y, r, tone(pal, ramps[nd.s], 0.9), a, I, f * gain, pal),
      );
      continue;
    }
    const qa = Math.round(a * 25) / 25;
    if (qa <= 0) continue;
    if (nd.big) {
      // A hub or a large bead catches the light: a bright point in a soft halo.
      const qh = Math.round(qa * 0.2 * 25) / 25;
      if (qh > 0) slice.dot(`h|${qh}`, x, y, r * 2.2, () => rgba(pal.highlight, qh));
      slice.dot(`H${nd.s}|${qa}`, x, y, r, () => rgba(tone(pal, ramps[nd.s], 1), qa));
    } else {
      slice.dot(`D${nd.s}|${qn}|${qa}`, x, y, r, () =>
        rgba(tone(pal, ramps[nd.s], 0.85 + 0.15 * qn), qa),
      );
    }
  }
}

/** A lit node: a burst of light around a bright core. */
function flare(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  r: number,
  colour: RGB,
  alpha: number,
  I: number,
  fade: number,
  pal: Palette,
) {
  ctx.fillStyle = rgba(pal.highlight, 0.22 * I * fade);
  ctx.beginPath();
  ctx.arc(x, y, r * 4 + 26 * I, 0, TAU);
  ctx.fill();
  ctx.fillStyle = rgba(pal.highlight, 0.5 * I * fade);
  ctx.beginPath();
  ctx.arc(x, y, r * 2 + 6 * I, 0, TAU);
  ctx.fill();
  ctx.fillStyle = rgba(mix(colour, pal.highlight, I), Math.min(1, alpha + I));
  ctx.beginPath();
  ctx.arc(x, y, r + 2.4 * I, 0, TAU);
  ctx.fill();
}

function drawField(scene: Scene, pal: Palette, slices: Slice[], still: boolean, now: number) {
  const { field: fd, view: v } = scene;
  const main = scene.mols[0];
  const gain = v.strength * pal.gain;
  const cph = Math.cos(v.pitchAngle);
  const sph = Math.sin(v.pitchAngle);
  const fadeLen = (fd.tEnd - fd.tStart) * 0.2;
  const n = fd.pts.length;
  for (let i = 0; i < n; i++) {
    const p = fd.pts[i];
    const yp = p.y * cph + p.z * sph;
    const zp = -p.y * sph + p.z * cph;
    const s = v.focal / (v.focal + zp);
    fd.X[i] = p.x * s;
    fd.Y[i] = yp * s;
    fd.S[i] = s;
    fd.Z[i] = zp;
    fd.N[i] = Math.max(0, Math.min(1, (1 - p.z / fd.hz) / 2));
    const e = Math.max(0, Math.min(1, (p.y - fd.tStart) / fadeLen, (fd.tEnd - p.y) / fadeLen));
    fd.F[i] = e * e * (3 - 2 * e);
  }
  fd.I.fill(0);
  if (still) {
    for (let i = 0; i < n; i += 17) fd.I[i] = 0.65;
  } else {
    for (const [i, f] of fd.flashes) {
      const I = envelope(f, now);
      if (I < 0) fd.flashes.delete(i);
      else fd.I[i] = I;
    }
  }
  const colour = tone(pal, pal.rampB, 0.55);
  const nodeC = tone(pal, pal.rampB, 0.8);
  const wireC = tone(pal, pal.rampA, 0.7);

  // Polygons: every pair of points closer than linkDist.
  for (let i = 0; i < n; i++) {
    const p = fd.pts[i];
    for (let j = i + 1; j < n; j++) {
      const q = fd.pts[j];
      const d = Math.hypot(q.x - p.x, q.y - p.y, q.z - p.z);
      if (d >= fd.linkDist) continue;
      const f = (fd.F[i] + fd.F[j]) * 0.5;
      if (f < 0.03) continue;
      const depth = 0.35 + 0.65 * (fd.N[i] + fd.N[j]) * 0.5;
      const a = (0.1 + 0.28 * (1 - d / fd.linkDist)) * depth * f * gain;
      const slice = slices[sliceOf((fd.Z[i] + fd.Z[j]) * 0.5, v)];
      const I = Math.max(fd.I[i], fd.I[j]);
      const ax = fd.X[i];
      const ay = fd.Y[i];
      const bx = fd.X[j];
      const by = fd.Y[j];
      if (I > 0.02) {
        slice.hot.push((ctx) => {
          ctx.strokeStyle = rgba(
            mix(colour, pal.highlight, I),
            Math.min(1, a + 0.7 * I * f * gain),
          );
          ctx.lineWidth = 0.6 + I * 0.9;
          ctx.beginPath();
          ctx.moveTo(ax, ay);
          ctx.lineTo(bx, by);
          ctx.stroke();
        });
        continue;
      }
      const qa = Math.round(a * 25) / 25;
      if (qa > 0) slice.line(`F|${qa}`, ax, ay, bx, by, () => [rgba(colour, qa), 0.6]);
    }
  }
  // Wires from the field into the molecule: the nearest couple of beads to each point.
  for (let i = 0; i < n; i++) {
    const p = fd.pts[i];
    let hooked = 0;
    for (const bi of main.beadSample) {
      if (hooked >= 2) break;
      const bp = main.nodes[bi].pin;
      const d = Math.hypot(main.LX[bp] - p.x, main.LY[bp] - p.y, main.LZ[bp] - p.z);
      if (d >= fd.reach) continue;
      hooked++;
      const f = Math.min(fd.F[i], main.F[bp]);
      if (f < 0.03) continue;
      const a = (0.08 + 0.18 * (1 - d / fd.reach)) * (0.4 + 0.6 * main.N[bp]) * f * gain;
      const slice = slices[sliceOf((fd.Z[i] + main.Z[bp]) * 0.5, v)];
      const I = Math.max(fd.I[i], main.I[bp]);
      const ax = fd.X[i];
      const ay = fd.Y[i];
      const bx = main.X[bp];
      const by = main.Y[bp];
      if (I > 0.02) {
        slice.hot.push((ctx) => {
          ctx.strokeStyle = rgba(
            mix(wireC, pal.highlight, I),
            Math.min(1, a + 0.55 * I * f * gain),
          );
          ctx.lineWidth = 0.6 + I;
          ctx.beginPath();
          ctx.moveTo(ax, ay);
          ctx.lineTo(bx, by);
          ctx.stroke();
        });
        continue;
      }
      const qa = Math.round(a * 25) / 25;
      if (qa > 0) slice.line(`G|${qa}`, ax, ay, bx, by, () => [rgba(wireC, qa), 0.6]);
    }
  }
  // The points themselves, every seventh an open diamond like a plotted datum.
  for (let i = 0; i < n; i++) {
    const f = fd.F[i];
    if (f < 0.03) continue;
    const x = fd.X[i];
    const y = fd.Y[i];
    if (x * x + y * y > v.bound2) continue;
    const depth = fd.N[i];
    const r = (0.9 + depth * 1.1) * fd.S[i];
    const a = (0.45 + depth * 0.5) * f * gain;
    const slice = slices[sliceOf(fd.Z[i], v)];
    const I = fd.I[i];
    if (I > 0.02) {
      slice.hot.push((ctx) => flare(ctx, x, y, r * 1.2, nodeC, a, I, f * gain, pal));
    } else {
      const qa = Math.round(a * 25) / 25;
      if (qa > 0) slice.dot(`P|${qa}`, x, y, r * 1.2, () => rgba(nodeC, qa));
    }
    if (i % 7 === 0) {
      const qa = Math.round((0.25 + depth * 0.35 + I * 0.4) * f * gain * 25) / 25;
      if (qa <= 0) continue;
      const s = r * 3.2 + I * 4;
      slice.hot.push((ctx) => {
        ctx.strokeStyle = rgba(nodeC, qa);
        ctx.lineWidth = 0.7;
        ctx.beginPath();
        ctx.moveTo(x, y - s);
        ctx.lineTo(x + s, y);
        ctx.lineTo(x, y + s);
        ctx.lineTo(x - s, y);
        ctx.closePath();
        ctx.stroke();
      });
    }
  }
}

// ------------------------------------------------------------------------------------- colour

function readPalette(darkQuery: MediaQueryList) {
  const dark =
    document.documentElement.dataset.theme === "dark" ||
    (document.documentElement.dataset.theme !== "light" && darkQuery.matches);
  const accent = parse(cssVar("--accent")) ?? (dark ? [79, 209, 197] : [15, 118, 110]);
  const blue = parse(cssVar("--case")) ?? (dark ? [106, 169, 242] : [43, 111, 200]);
  // Shadow → body → lit edge. The ramp is what a DAPI/SYBR-stained molecule looks like under
  // a fluorescence scope: indigo in the dark, cyan-blue in the body, white-cyan where lit.
  const shadow: RGB = dark ? [6, 18, 70] : [10, 30, 96];
  const highlight: RGB = dark ? [200, 255, 255] : [40, 220, 236];
  // Fully saturated stops for the spirals, so the stain reads electric rather than muted.
  const tealDeep: RGB = dark ? [0, 128, 150] : [0, 110, 130];
  const teal: RGB = dark ? [0, 240, 220] : [0, 190, 178];
  const blueDeep: RGB = dark ? [16, 70, 230] : [14, 60, 200];
  const blueBright: RGB = dark ? [40, 170, 255] : [20, 140, 240];
  return {
    dark,
    // Strand A is electric teal, strand B electric blue; both share shadow and highlight.
    rampA: [shadow, tealDeep, teal, highlight] as RGB[],
    rampB: [shadow, blueDeep, blueBright, highlight] as RGB[],
    // Trace colours: the two strands' tints over the shadow stop.
    baseA: mix(accent, shadow, 0.3),
    baseB: mix(blue, shadow, 0.3),
    glow: accent,
    highlight,
    gain: dark ? 1 : 0.85,
    // How far up the ramp a line may go: on the pale page the lit end is too faint to read.
    lineMax: dark ? 1 : 0.7,
  };
}

/** A line colour: the ramp, capped where the theme says lines stop reading. */
function tone(pal: Palette, stops: RGB[], u: number): RGB {
  return ramp(stops, u * pal.lineMax);
}
/** Colour at position u ∈ [0, 1] along a ramp of evenly spaced stops. */
function ramp(stops: RGB[], u: number): RGB {
  const x = Math.max(0, Math.min(1, u)) * (stops.length - 1);
  const i = Math.min(stops.length - 2, Math.floor(x));
  return mix(stops[i], stops[i + 1], x - i);
}
/** Darken toward indigo below 0.5, lighten toward white above. */
function shade(c: RGB, light: number): RGB {
  return light < 0.5
    ? mix([8, 16, 48], c, light * 2)
    : mix(c, [140, 214, 224], (light - 0.5) * 1.1);
}
function mix(a: RGB, b: RGB, u: number): RGB {
  return [a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u, a[2] + (b[2] - a[2]) * u];
}
function rgba([r, g, b]: RGB, alpha: number): string {
  const a = Math.max(0, Math.min(1, alpha));
  return `rgba(${Math.round(r)}, ${Math.round(g)}, ${Math.round(b)}, ${a})`;
}
/** Parse #rgb, #rrggbb or rgb()/rgba() into channels. */
function parse(colour: string): RGB | null {
  if (!colour) return null;
  if (colour.startsWith("#")) {
    const hex =
      colour.length === 4 ? colour.slice(1).replace(/./g, (c) => c + c) : colour.slice(1, 7);
    const n = Number.parseInt(hex, 16);
    if (Number.isNaN(n)) return null;
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }
  const m = colour.match(/[\d.]+/g);
  return m && m.length >= 3 ? [Number(m[0]), Number(m[1]), Number(m[2])] : null;
}
