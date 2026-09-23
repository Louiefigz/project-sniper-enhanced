import { requireCatalogKind } from "./visual-source-policy";
// Curated ELEMENTS catalog — the operator-insertable comp kinds. Each entry
// mirrors a template at templates/motion/compositions/<kind>.html (the Python
// renderer resolves kind → that file, so `kind` strings here are load-bearing).
//
// `ownScreen` kinds are full-frame CUTAWAYS (opaque, they hard-cut the frame —
// anchor "own-screen"); the rest are alpha overlays placed in the free band
// (anchor "free-band"). `canvas` is the aspect the comp authors on (from the
// planner's kind→canvas map) so the UI can flag vertical-only comps inside a
// 16:9 longform edit. `defaultSpec` = the comp's data-composition-variables
// with placeholder copy the operator overwrites in the properties panel.
//
// Data catalog — exempt from the logic-file line limit.

export type CompCanvas = "16:9" | "9:16";

/** One extra spec knob the properties panel exposes beyond the primary text key. */
export interface SpecField {
  key: string;
  label: string;
  type: "number" | "color";
  min?: number;
  max?: number;
  /** number fields: input step; < 1 = decimal field, else integer. Default 1. */
  step?: number;
}

export interface CompCatalogEntry {
  kind: string;
  label: string;
  description: string;
  ownScreen: boolean;
  canvas: CompCanvas;
  defaultSpec: Record<string, unknown>;
  /** Verified upstream source, shared with runtime admission. */
  catalogId?: string;
  section?: "catalog";
  /** Extra editable spec fields (graphic-properties renders them generically). */
  specFields?: SpecField[];
}

/** The canvas a plan renders on — longform edits are 16:9, everything else 9:16. */
export function planCanvas(target?: { mode?: string }): CompCanvas {
  return target?.mode === "longform" ? "16:9" : "9:16";
}

const CATALOG_PORTS: CompCatalogEntry[] = [
{
    kind: "marker-highlight",
    label: "Marker highlight",
    description:
      "Cream paper panel with one spoken line — a hand-drawn marker stroke (highlight/circle/underline/scribble) draws over the emphasis word on cue (whole-word match).",
    ownScreen: false,
    canvas: "9:16",
    defaultSpec: {
      text: "The hook does the heavy lifting",
      emphasisWord: "hook",
      style: "highlight",
      drawAt: 0.9,
      accent: "#054BC9",
    },
    specFields: [
      { key: "drawAt", label: "draw at s", type: "number", min: 0, max: 30, step: 0.05 },
      { key: "accent", label: "ink", type: "color" },
    ],
  },
{
    kind: "hw-callout-circle",
    label: "Callout circle",
    description:
      "Hand-wobbled ellipse draws around an x/y/w/h region of the frame with an optional scribble hatch and a connected handwritten label; the whole callout boils like marker ink.",
    ownScreen: false,
    canvas: "9:16",
    defaultSpec: {
      x: 240, y: 780, w: 600, h: 300,
      label: "look here",
      labelAt: "below",
      scribble: false,
      seed: 4,
      drawAt: 0.2,
      accent: "#054BC9",
    },
    specFields: [
      { key: "x", label: "region x", type: "number", min: 0, max: 1080, step: 1 },
      { key: "y", label: "region y", type: "number", min: 0, max: 1920, step: 1 },
      { key: "w", label: "region w", type: "number", min: 20, max: 1080, step: 1 },
      { key: "h", label: "region h", type: "number", min: 20, max: 1920, step: 1 },
      { key: "drawAt", label: "draw at s", type: "number", min: 0, max: 30, step: 0.05 },
    ],
  },
{
    kind: "hw-scribble-transition",
    label: "Scribble transition",
    description:
      "Seam cover for a hard subject switch — fat hand-drawn zigzag bands scribble across the frame over a solid backstop, then clear the other way ({} spec is legitimate).",
    ownScreen: false,
    canvas: "9:16",
    defaultSpec: {
      bands: 12,
      strokeScale: 1,
      seed: 17,
      accent: "#054BC9",
    },
    specFields: [
      { key: "bands", label: "bands", type: "number", min: 3, max: 18, step: 1 },
      { key: "strokeScale", label: "stroke scale", type: "number", min: 0.5, max: 2, step: 0.05 },
      { key: "accent", label: "ink", type: "color" },
    ],
  },
{
    kind: "chart-story",
    label: "Chart story",
    description:
      "Evidence card with four chart forms (bars/line/donut/progress) that builds in reading order and lands the exact supplied values; the emphasized datum takes the accent callout. Plan it as a panel, not a takeover.",
    ownScreen: false,
    canvas: "16:9",
    defaultSpec: {
      type: "bars",
      data: "12, 28, 45, 64",
      labels: "Q1, Q2, Q3, Q4",
      emphasize: 3,
      unit: "%",
      accent: "#054BC9",
    },
    specFields: [
      { key: "emphasize", label: "emphasize idx", type: "number", min: 0, max: 7, step: 1 },
      { key: "accent", label: "accent", type: "color" },
    ],
  },
{
    kind: "count-up",
    label: "Count up",
    description:
      "One hero number on the house card accelerates from start and lands exactly on the integer end value with a restrained pulse; prefix/suffix state the unit.",
    ownScreen: false,
    canvas: "9:16",
    defaultSpec: {
      start: 0,
      end: 100,
      prefix: "",
      suffix: "%",
      accent: "#054BC9",
    },
    specFields: [
      { key: "start", label: "start", type: "number", step: 1 },
      { key: "end", label: "end", type: "number", step: 1 },
      { key: "accent", label: "accent", type: "color" },
    ],
  },
{
    kind: "line-swap",
    label: "Line swap",
    description:
      "Setup-then-subvert hook card — line A holds center in a masked slot, exits up on the swap beat as line B slams in, and an accent underline draws under the matched word.",
    ownScreen: false,
    canvas: "9:16",
    defaultSpec: {
      lineA: "You do not need more footage",
      lineB: "You need a sharper first line",
      swapAt: 1.5,
      underlineWord: "sharper",
      accent: "#054BC9",
    },
    specFields: [
      { key: "swapAt", label: "swap at s", type: "number", min: 0, max: 30, step: 0.1 },
      { key: "accent", label: "accent", type: "color" },
    ],
  },
{
    kind: "ui-focus-zoom",
    label: "UI focus zoom",
    description:
      "Screen/tutorial cutaway that points — the framed screenshot establishes, then the camera zooms and pans to the anchored region on cue and holds (screenshot must live under templates/motion/assets).",
    ownScreen: true,
    canvas: "16:9",
    defaultSpec: {
      image: "assets/sample-screen.png",
      anchorX: 64,
      anchorY: 36,
      zoom: 1.6,
      zoomAt: 1.4,
      accent: "#054BC9",
    },
    specFields: [
      { key: "anchorX", label: "anchor x %", type: "number", min: 0, max: 100, step: 1 },
      { key: "anchorY", label: "anchor y %", type: "number", min: 0, max: 100, step: 1 },
      { key: "zoom", label: "zoom", type: "number", min: 1.05, max: 3, step: 0.05 },
      { key: "zoomAt", label: "zoom at s", type: "number", min: 0, max: 30, step: 0.1 },
    ],
  }
];

export const COMPS_CATALOG: CompCatalogEntry[] = CATALOG_PORTS.map(row => ({ ...row, kind: requireCatalogKind(row.kind), catalogId: row.kind, section: "catalog" }));

const BY_KIND = new Map(COMPS_CATALOG.map((c) => [c.kind, c]));

/** The extra editable spec fields for a kind ([] for kinds without any). */
export function specFieldsFor(kind: string): SpecField[] {
  return BY_KIND.get(kind)?.specFields ?? [];
}

/**
 * Vocabulary block for the Ask-Claude AND auto-edit authoring prompts: one line
 * per comp (kind, canvas, description) plus a hard canvas rule — a comp authored
 * on the wrong canvas composites half-frame, and the fast assemble path has no
 * lint. Pass `null` when the plan's canvas isn't known at prompt time (auto-edit
 * before target.mode is decided): the rule is phrased against target.mode.
 */
export function catalogPromptLines(canvas: CompCanvas | null): string[] {
  const rule = canvas
    ? `Only insert comps whose canvas matches this plan (${canvas})`
    : `Only insert comps whose canvas matches your target.mode (longform → 16:9, short → 9:16)`;
  return [
    "Visual sources must come from the HyperFrames upstream catalog. This list contains only installed compatibility ports, not the full catalog.",
    "Search the full catalog with graphics/catalog_discovery_cli.py. Use a source-bound native project for other catalog components, current-job references or justified custom work. Never use retired Sniper templates.",
    ...COMPS_CATALOG.map(
      (c) =>
        `- ${c.kind} [canvas ${c.canvas}] — ${c.description}${c.ownScreen ? " (own-screen full-frame cutaway)" : " (free-band overlay)"}`,
    ),
    `${rule} — a mismatched-canvas comp composites half-frame and there is no lint on the fast assemble path.`,
  ];
}
