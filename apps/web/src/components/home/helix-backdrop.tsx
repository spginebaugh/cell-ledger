import { useEffect, useRef } from "react";
import { cssVar } from "@/lib/theme";

/**
 * A procedurally drawn B-DNA double helix, wired into a field of data, turning slowly behind
 * the start page.
 *
 * The molecule: two sugar-phosphate backbones drawn as continuous shaded tubes, offset around
 * the axis by about 126° so the helix shows a major and a minor groove the way real DNA does,
 * with base pairs bridging the strands as two half-rods meeting at the axis. Every mark is lit
 * from the upper left and coloured along a fluorescence-microscopy ramp. Rotating a helix about
 * its own axis is the same as advancing the phase of the winding, so the turn is one parameter
 * that grows with time.
 *
 * The data: nodes sit on the backbones every few samples and a triangulated web of hairlines
 * runs between them, across the groove and along each strand, so the molecule reads as a mesh
 * of measurements. Around it drifts a plexus of points joined wherever two are close, on its own
 * clock, independent of the turn; points near the helix are wired to it. Nodes flash at random
 * like lightning, a fast attack with a flicker and a decay, and a flash often jumps to a
 * neighbour a moment later. With prefers-reduced-motion everything draws once and holds still.
 */
export function HelixBackdrop() {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    // Narrowing does not reach the hoisted function declarations below, so bind non-null
    // constants once the checks pass.
    const canvasEl = ref.current;
    if (!canvasEl) return;
    const canvas: HTMLCanvasElement = canvasEl;
    const context = canvas.getContext("2d");
    if (!context) return;
    const ctx: CanvasRenderingContext2D = context;

    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
    const darkQuery = window.matchMedia("(prefers-color-scheme: dark)");

    let width = 0;
    let height = 0;
    let dpr = 1;
    let raf = 0;
    let last = 0;
    let now = 0;
    let phase = 0.6;
    let palette = readPalette();

    // The data field: points that drift inside a box around the helix, re-seeded on resize.
    type FieldPoint = { x: number; y: number; z: number; vx: number; vy: number; vz: number };
    let field: FieldPoint[] = [];
    let bounds = { hx: 0, hy: 0, hz: 0 };
    // Lightning: node key → when it struck and for how long.
    const flashes = new Map<string, { start: number; dur: number }>();
    let helixNodeCount = 0;

    function readPalette() {
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
        // Base colours: purine/pyrimidine halves in two tints of the same ramp.
        baseA: mix(accent, shadow, 0.3),
        baseB: mix(blue, shadow, 0.3),
        glow: accent,
        highlight,
        gain: dark ? 1 : 0.78,
      };
    }

    /** Everything that depends on the viewport. */
    function geometry() {
      const narrow = width < 768;
      const radius = Math.max(44, Math.min(width, height) * (narrow ? 0.13 : 0.14));
      return {
        narrow,
        cx: narrow ? width * 0.92 : width * 0.74,
        cy: height * 0.5,
        radius,
        pitch: radius * 3.4, // rise per full turn (B-DNA: pitch ≈ 3.4 nm, radius ≈ 1 nm)
        tilt: -0.22,
        step: 4, // px of rise between samples
        focal: radius * 7,
        strength: palette.gain * (narrow ? 0.5 : 1),
        grooveOffset: 2.2, // radians between the two backbones: major + minor groove
        tube: Math.max(2.2, radius * 0.075),
        span: height * 0.75,
        nodeEvery: narrow ? 4 : 3, // samples between data nodes on a backbone
        linkDist: radius * 1.7, // field points closer than this are joined
      };
    }

    function seedField() {
      const g = geometry();
      bounds = { hx: g.radius * 4.8, hy: g.span, hz: g.radius * 2 };
      const count = g.narrow ? 44 : 110;
      field = Array.from({ length: count }, () => ({
        x: (Math.random() * 2 - 1) * bounds.hx,
        y: (Math.random() * 2 - 1) * bounds.hy,
        z: (Math.random() * 2 - 1) * bounds.hz,
        vx: (Math.random() * 2 - 1) * 7,
        vy: (Math.random() * 2 - 1) * 9,
        vz: (Math.random() * 2 - 1) * 5,
      }));
      flashes.clear();
    }

    function drift(dt: number) {
      for (const p of field) {
        p.x += p.vx * dt;
        p.y += p.vy * dt;
        p.z += p.vz * dt;
        if (p.x < -bounds.hx || p.x > bounds.hx) p.vx = -p.vx;
        if (p.y < -bounds.hy || p.y > bounds.hy) p.vy = -p.vy;
        if (p.z < -bounds.hz || p.z > bounds.hz) p.vz = -p.vz;
      }
    }

    /** Strike a node now, and often a neighbour a moment later. */
    function strike(key: string, at: number, dur: number, hops: number) {
      flashes.set(key, { start: at, dur });
      if (hops <= 0 || Math.random() > 0.75) return;
      // The strike crawls to a neighbour: a third of a second or more before it lands there.
      const delay = 320 + Math.random() * 380;
      if (key.startsWith("f")) {
        const i = Number(key.slice(1));
        const p = field[i];
        if (!p) return;
        const g = geometry();
        let best = -1;
        let bestD = g.linkDist;
        field.forEach((q, j) => {
          if (j === i) return;
          const d = Math.hypot(q.x - p.x, q.y - p.y, q.z - p.z);
          if (d < bestD) {
            bestD = d;
            best = j;
          }
        });
        if (best >= 0) strike(`f${best}`, at + delay, dur * 0.9, hops - 1);
      } else {
        const strand = key[1];
        const k = Number(key.slice(2));
        const other = strand === "A" ? "B" : "A";
        const next =
          Math.random() < 0.5
            ? `h${other}${k}`
            : `h${strand}${Math.min(helixNodeCount - 1, Math.max(0, k + (Math.random() < 0.5 ? -1 : 1)))}`;
        strike(next, at + delay, dur * 0.9, hops - 1);
      }
    }

    function spawn() {
      const dur = 900 + Math.random() * 900;
      if (Math.random() < 0.6 && field.length) {
        strike(`f${Math.floor(Math.random() * field.length)}`, now, dur, 3);
      } else if (helixNodeCount) {
        const strand = Math.random() < 0.5 ? "A" : "B";
        strike(`h${strand}${Math.floor(Math.random() * helixNodeCount)}`, now, dur, 3);
      }
    }

    /** 0 when dark; up to 1 at the peak of a strike, with a flicker on the way down. */
    function intensity(key: string): number {
      const f = flashes.get(key);
      if (!f) return 0;
      const age = now - f.start;
      if (age < 0) return 0;
      if (age > f.dur) {
        flashes.delete(key);
        return 0;
      }
      const u = age / f.dur;
      const envelope = u < 0.12 ? u / 0.12 : 1 - (u - 0.12) / 0.88;
      const flicker = 0.78 + 0.22 * Math.sin(age * 0.035) * Math.sin(age * 0.009);
      return envelope * flicker;
    }

    function resize() {
      width = window.innerWidth;
      height = window.innerHeight;
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      seedField();
      draw();
    }

    function draw() {
      ctx.clearRect(0, 0, width, height);
      const g = geometry();
      const { radius, pitch, step, focal, strength, grooveOffset, tube, span } = g;
      const still = reduced.matches;

      // A soft pool of light behind the molecule.
      const pool = ctx.createRadialGradient(
        g.cx,
        g.cy,
        0,
        g.cx,
        g.cy,
        Math.max(width, height) * 0.42,
      );
      pool.addColorStop(0, rgba(palette.glow, (palette.dark ? 0.1 : 0.07) * strength));
      pool.addColorStop(1, rgba(palette.glow, 0));
      ctx.fillStyle = pool;
      ctx.fillRect(0, 0, width, height);

      ctx.save();
      ctx.translate(g.cx, g.cy);
      ctx.rotate(g.tilt);
      ctx.lineCap = "round";

      const edgeFade = (t: number) => 1 - Math.min(1, Math.abs(t) / span) ** 3;
      type P = { x: number; y: number; z: number };
      const project = (p: P) => {
        const s = focal / (focal + p.z);
        return { x: p.x * s, y: p.y * s, s };
      };
      const point = (t: number, angle: number): P => {
        const theta = (t / pitch) * Math.PI * 2 + phase + angle;
        return { x: Math.cos(theta) * radius, y: t, z: Math.sin(theta) * radius };
      };
      const nearOf = (z: number, scale = radius) => (z / scale + 1) / 2; // 0 far, 1 near

      // ---------------------------------------------------------------- data nodes on the helix
      type Node = { p: P; key: string; I: number };
      const nodesA: Node[] = [];
      const nodesB: Node[] = [];
      for (let k = 0, t = -span; t <= span; k++, t += step * g.nodeEvery) {
        const keyA = `hA${k}`;
        const keyB = `hB${k}`;
        nodesA.push({
          p: point(t, 0),
          key: keyA,
          I: still ? (k % 11 === 0 ? 0.6 : 0) : intensity(keyA),
        });
        nodesB.push({
          p: point(t, grooveOffset),
          key: keyB,
          I: still ? (k % 13 === 5 ? 0.6 : 0) : intensity(keyB),
        });
      }
      helixNodeCount = nodesA.length;

      // ---------------------------------------------------------------------- the data field
      const fieldI = field.map((_, i) => (still ? (i % 17 === 0 ? 0.65 : 0) : intensity(`f${i}`)));
      const fieldColour = ramp(palette.rampB, 0.55);
      const fieldNode = ramp(palette.rampB, 0.8);
      ctx.lineWidth = 0.6;
      // Polygons: every pair of points closer than linkDist.
      for (let i = 0; i < field.length; i++) {
        const p = field[i];
        for (let j = i + 1; j < field.length; j++) {
          const q = field[j];
          const d = Math.hypot(q.x - p.x, q.y - p.y, q.z - p.z);
          if (d >= g.linkDist) continue;
          const I = Math.max(fieldI[i], fieldI[j]);
          const depth = 0.35 + 0.65 * nearOf((p.z + q.z) / 2, bounds.hz);
          const fade = edgeFade((p.y + q.y) / 2) * strength;
          const a = ((0.09 + 0.24 * (1 - d / g.linkDist)) * depth + 0.7 * I) * fade;
          ctx.strokeStyle = rgba(mix(fieldColour, palette.highlight, I), a);
          ctx.lineWidth = 0.6 + I * 0.9;
          line(project(p), project(q));
        }
      }
      // Wires from the field into the molecule: the nearest couple of points to each node.
      const reach = radius * 1.5;
      const wire = ramp(palette.rampA, 0.7);
      for (const n of [...nodesA, ...nodesB]) {
        let hooked = 0;
        for (let i = 0; i < field.length && hooked < 2; i++) {
          const q = field[i];
          const d = Math.hypot(q.x - n.p.x, q.y - n.p.y, q.z - n.p.z);
          if (d >= reach) continue;
          hooked++;
          const I = Math.max(n.I, fieldI[i]);
          const fade = edgeFade(n.p.y) * strength;
          ctx.strokeStyle = rgba(
            mix(wire, palette.highlight, I),
            ((0.08 + 0.18 * (1 - d / reach)) * (0.4 + 0.6 * nearOf(n.p.z)) + 0.55 * I) * fade,
          );
          ctx.lineWidth = 0.6 + I;
          line(project(n.p), project(q));
        }
      }
      // Field points, flashing ones with a burst.
      field.forEach((p, i) => {
        const pp = project(p);
        const depth = nearOf(p.z, bounds.hz);
        const fade = edgeFade(p.y) * strength;
        const r = (0.9 + depth * 1.1) * pp.s;
        dot(pp.x, pp.y, r * 1.2, fieldNode, (0.45 + depth * 0.5) * fade, fieldI[i], fade);
        // Every so often a point is a marker: a small open diamond, like a plotted datum.
        if (i % 7 === 0) {
          ctx.strokeStyle = rgba(fieldNode, (0.25 + depth * 0.35 + fieldI[i] * 0.4) * fade);
          ctx.lineWidth = 0.7;
          const s = r * 3.2 + fieldI[i] * 4;
          ctx.beginPath();
          ctx.moveTo(pp.x, pp.y - s);
          ctx.lineTo(pp.x + s, pp.y);
          ctx.lineTo(pp.x, pp.y + s);
          ctx.lineTo(pp.x - s, pp.y);
          ctx.closePath();
          ctx.stroke();
        }
      });

      // ------------------------------------------------------------------------ the molecule
      // Each backbone is a wireframe lattice, not a solid: at every section a ring of four
      // scattered vertices sits around the backbone path, joined around the ring, to the ring
      // ahead, and by long chords to the ring three ahead, so the strand reads as a tube built
      // from points and lines. A soft bloom along the centreline keeps it luminous, and the
      // vertices that face outward carry bright glints.
      type Wire = { kind: "wire"; a: P; b: P; ramp: RGB[]; z: number; t: number; a0: number };
      type Vert = { kind: "vert"; p: P; ramp: RGB[]; z: number; t: number; glint: boolean };
      type Bloom = { kind: "bloom"; a: P; b: P; ramp: RGB[]; z: number; t: number };
      type Pair = {
        kind: "pair";
        a: P;
        b: P;
        z: number;
        t: number;
        thin: boolean;
        ringA: P[];
        ringB: P[];
      };
      type Web = { kind: "web"; a: Node; b: Node; z: number; t: number; colour: RGB; max: number };
      type Dot = { kind: "node"; n: Node; strand: "A" | "B"; z: number; t: number };
      const items: (Wire | Vert | Bloom | Pair | Web | Dot)[] = [];

      const secStep = g.narrow ? 14 : 10; // px of rise between lattice sections
      // A stable pseudo-random in [0, 1) so the scatter turns rigidly with the helix.
      const hash = (a: number, b: number, c: number) => {
        const x = Math.sin(a * 12.9898 + b * 78.233 + c * 37.719) * 43758.5453;
        return x - Math.floor(x);
      };
      // Ring layout around the backbone: two vertices beside it, one outward, one inward.
      const RING: [number, number][] = [
        [-0.12, 0],
        [0, 1],
        [0.12, 0],
        [0, -1],
      ];
      const vertex = (t: number, angle: number, s: number, j: number, seed: number): P => {
        const [ba, br] = RING[j];
        const da = ba + (hash(s, j, seed) - 0.5) * 0.07;
        const dr = br * tube * 1.7 + (hash(s, j, seed + 7) - 0.5) * tube * 0.9;
        const dt = (hash(s, j, seed + 13) - 0.5) * secStep * 0.5;
        const theta = ((t + dt) / pitch) * Math.PI * 2 + phase + angle + da;
        const r = radius + dr;
        return { x: Math.cos(theta) * r, y: t + dt, z: Math.sin(theta) * r };
      };
      const strands = [
        { angle: 0, ramp: palette.rampA, seed: 1, rings: [] as P[][] },
        { angle: grooveOffset, ramp: palette.rampB, seed: 2, rings: [] as P[][] },
      ];
      const sections = Math.floor((span * 2) / secStep) + 4;
      for (const st of strands) {
        for (let s = 0; s < sections; s++) {
          const t = -span + s * secStep;
          st.rings.push([0, 1, 2, 3].map((j) => vertex(t, st.angle, s, j, st.seed)));
        }
        const wire = (a: P, b: P, a0: number) =>
          items.push({
            kind: "wire",
            a,
            b,
            ramp: st.ramp,
            z: (a.z + b.z) / 2,
            t: (a.y + b.y) / 2,
            a0,
          });
        for (let s = 0; s < sections; s++) {
          const ring = st.rings[s];
          const next = st.rings[s + 1];
          const far = st.rings[s + 3];
          for (let j = 0; j < 4; j++) {
            wire(ring[j], ring[(j + 1) % 4], 0.5);
            if (next) {
              wire(ring[j], next[j], 0.85);
              wire(ring[j], next[(j + 1) % 4], 0.6);
            }
            if (far && (j === 1 || j === 3)) wire(ring[j], far[j], 0.35);
            items.push({
              kind: "vert",
              p: ring[j],
              ramp: st.ramp,
              z: ring[j].z,
              t: ring[j].y,
              glint: (s % 3 === 0 && j === 1) || (s % 5 === 2 && j === 3),
            });
          }
          if (next) {
            const a = point(-span + s * secStep, st.angle);
            const b = point(-span + (s + 1) * secStep, st.angle);
            items.push({
              kind: "bloom",
              a,
              b,
              ramp: st.ramp,
              z: (a.z + b.z) / 2,
              t: (a.y + b.y) / 2,
            });
          }
        }
      }
      // Twenty-four cross-links per turn: every other one a fan of base-pair wires meeting at
      // the axis, the rest single hairlines.
      const pairSpacing = pitch / 24;
      for (let n = 0, t = -span; t <= span; n++, t += pairSpacing) {
        const a = point(t, 0);
        const b = point(t, grooveOffset);
        const s = Math.min(sections - 1, Math.max(0, Math.round((t + span) / secStep)));
        items.push({
          kind: "pair",
          a,
          b,
          z: (a.z + b.z) / 2,
          t,
          thin: n % 2 !== 0,
          ringA: strands[0].rings[s],
          ringB: strands[1].rings[s],
        });
      }

      // The web: triangulated hairlines across the groove and chords along each strand.
      const webA = ramp(palette.rampA, 0.8);
      const webB = ramp(palette.rampB, 0.8);
      const webX = mix(webA, webB, 0.5);
      const addWeb = (a: Node, b: Node, colour: RGB, max: number) => {
        const d = Math.hypot(b.p.x - a.p.x, b.p.y - a.p.y, b.p.z - a.p.z);
        if (d >= max) return;
        items.push({
          kind: "web",
          a,
          b,
          z: (a.p.z + b.p.z) / 2,
          t: (a.p.y + b.p.y) / 2,
          colour,
          max,
        });
      };
      for (let k = 0; k < nodesA.length; k++) {
        const a = nodesA[k];
        const b = nodesB[k];
        addWeb(a, b, webX, radius * 2.2);
        if (nodesB[k + 1]) addWeb(a, nodesB[k + 1], webX, radius * 2.2);
        if (nodesB[k + 2]) addWeb(a, nodesB[k + 2], webX, radius * 1.7);
        if (nodesA[k + 1]) addWeb(nodesA[k + 1], b, webX, radius * 2.2);
        if (nodesA[k + 2]) addWeb(a, nodesA[k + 2], webA, radius * 1.6);
        if (nodesA[k + 3]) addWeb(a, nodesA[k + 3], webA, radius * 1.6);
        if (nodesB[k + 2]) addWeb(b, nodesB[k + 2], webB, radius * 1.6);
        if (nodesB[k + 3]) addWeb(b, nodesB[k + 3], webB, radius * 1.6);
        items.push({ kind: "node", n: a, strand: "A", z: a.p.z, t: a.p.y });
        items.push({ kind: "node", n: b, strand: "B", z: b.p.z, t: b.p.y });
      }
      items.sort((p, q) => p.z - q.z);

      for (const it of items) {
        const fade = edgeFade(it.t) * strength;
        const near = nearOf(it.z);

        if (it.kind === "vert") {
          const pp = project(it.p);
          if (it.glint) {
            // An outward-facing vertex catches the light: a bright point in a soft halo.
            ctx.fillStyle = rgba(palette.highlight, (0.12 + near * 0.16) * fade);
            ctx.beginPath();
            ctx.arc(pp.x, pp.y, (3.5 + near * 4) * pp.s, 0, Math.PI * 2);
            ctx.fill();
            ctx.fillStyle = rgba(palette.highlight, (0.7 + near * 0.3) * fade);
            ctx.beginPath();
            ctx.arc(pp.x, pp.y, (1.2 + near * 1.2) * pp.s, 0, Math.PI * 2);
            ctx.fill();
          } else {
            ctx.fillStyle = rgba(ramp(it.ramp, 0.8 + near * 0.2), (0.4 + near * 0.55) * fade);
            ctx.beginPath();
            ctx.arc(pp.x, pp.y, (0.7 + near * 0.9) * pp.s, 0, Math.PI * 2);
            ctx.fill();
          }
          continue;
        }
        if (it.kind === "wire") {
          ctx.strokeStyle = rgba(
            ramp(it.ramp, 0.42 + near * 0.5),
            it.a0 * (0.22 + near * 0.6) * fade,
          );
          ctx.lineWidth = 0.55 + near * 0.45;
          line(project(it.a), project(it.b));
          continue;
        }
        if (it.kind === "bloom") {
          // Two layers of bloom along the centreline: a wide faint halo and a tighter one,
          // strongest on the near strand so the outer helix reads as luminous.
          const pa = project(it.a);
          const pb = project(it.b);
          const w = tube * (0.75 + near * 0.5) * pa.s;
          ctx.strokeStyle = rgba(ramp(it.ramp, 0.4 + near * 0.45), (0.03 + near * 0.05) * fade);
          ctx.lineWidth = w * 9;
          line(pa, pb);
          ctx.strokeStyle = rgba(ramp(it.ramp, 0.5 + near * 0.3), (0.07 + near * 0.12) * fade);
          ctx.lineWidth = w * 4;
          line(pa, pb);
          continue;
        }
        if (it.kind === "node") {
          const pp = project(it.n.p);
          const colour = ramp(it.strand === "A" ? palette.rampA : palette.rampB, 0.9);
          dot(
            pp.x,
            pp.y,
            (1.6 + near * 1.6) * pp.s,
            colour,
            (0.55 + near * 0.45) * fade,
            it.n.I,
            fade,
          );
          continue;
        }
        if (it.kind === "web") {
          const pa = project(it.a.p);
          const pb = project(it.b.p);
          const d = Math.hypot(it.b.p.x - it.a.p.x, it.b.p.y - it.a.p.y, it.b.p.z - it.a.p.z);
          const I = Math.max(it.a.I, it.b.I);
          ctx.strokeStyle = rgba(
            mix(it.colour, palette.highlight, I),
            ((0.18 + 0.36 * (1 - d / it.max)) * (0.35 + 0.65 * near) + 0.7 * I) * fade,
          );
          ctx.lineWidth = 0.7 + near * 0.4 + I;
          line(pa, pb);
          continue;
        }

        // Cross-links.
        const pa = project(it.a);
        const pb = project(it.b);
        const mid = { x: (pa.x + pb.x) / 2, y: (pa.y + pb.y) / 2, s: (pa.s + pb.s) / 2 };
        if (it.thin) {
          ctx.strokeStyle = rgba(ramp(palette.rampA, 0.55), (0.12 + near * 0.22) * fade);
          ctx.lineWidth = 0.7;
          line(pa, pb);
          continue;
        }
        // A fan of hairlines from each strand's ring converging on the junction at the axis.
        const light = 0.3 + near * 0.7;
        const alpha = (0.3 + near * 0.5) * fade;
        ctx.lineWidth = 0.6 + near * 0.4;
        ctx.strokeStyle = rgba(shade(palette.baseA, light), alpha);
        for (const v of [it.ringA[0], it.a, it.ringA[2]]) line(project(v), mid);
        ctx.strokeStyle = rgba(shade(palette.baseB, light), alpha);
        for (const v of [it.ringB[0], it.b, it.ringB[2]]) line(mid, project(v));
        // Hydrogen-bond junction at the axis.
        ctx.fillStyle = rgba(palette.highlight, (0.12 + near * 0.14) * fade);
        ctx.beginPath();
        ctx.arc(mid.x, mid.y, (3 + near * 3) * mid.s, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = rgba(palette.highlight, (0.5 + near * 0.45) * fade);
        ctx.beginPath();
        ctx.arc(mid.x, mid.y, (1.1 + near * 1.1) * mid.s, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.restore();

      function line(a: { x: number; y: number }, b: { x: number; y: number }) {
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.stroke();
      }
      /** A node: a small core, and when struck a burst of light around it. */
      function dot(
        x: number,
        y: number,
        r: number,
        colour: RGB,
        alpha: number,
        I: number,
        fade: number,
      ) {
        if (I > 0) {
          ctx.fillStyle = rgba(palette.highlight, 0.22 * I * fade);
          ctx.beginPath();
          ctx.arc(x, y, r * 4 + 26 * I, 0, Math.PI * 2);
          ctx.fill();
          ctx.fillStyle = rgba(palette.highlight, 0.5 * I * fade);
          ctx.beginPath();
          ctx.arc(x, y, r * 2 + 6 * I, 0, Math.PI * 2);
          ctx.fill();
        }
        ctx.fillStyle = rgba(mix(colour, palette.highlight, I), Math.min(1, alpha + I));
        ctx.beginPath();
        ctx.arc(x, y, r + 2.4 * I, 0, Math.PI * 2);
        ctx.fill();
      }
    }

    function frame(t: number) {
      now = t;
      if (last) {
        const dt = Math.min(0.1, (t - last) / 1000);
        phase += dt * 0.3; // the turn: unchanged
        drift(dt); // the field: its own clock
        // Strikes arrive at random, a few a second.
        const rate = width < 768 ? 0.7 : 1.4;
        if (Math.random() < dt * rate) spawn();
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
      palette = readPalette();
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
    <div aria-hidden="true" className="pointer-events-none fixed inset-0 -z-10 overflow-hidden">
      <canvas ref={ref} className="block" />
    </div>
  );
}

type RGB = [number, number, number];

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
