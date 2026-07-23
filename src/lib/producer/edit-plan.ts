// Editor read-side subset of the Python-owned EDL. All `out*` times are OUTPUT
// seconds and therefore map 1:1 onto the rendered video's currentTime.

export interface CutSegment {
  id?: string;
  sourceId: string;
  start: number;
  end: number;
  speed?: number;
}

export interface GraphicEntry {
  /**
   * Stable identity for this entry, minted in CODE (never by the AI/brain — see
   * `reconcileGraphicIds`). The editor addresses graphics by `id`, not array
   * index, so a mid-drag insert/remove (an AI edit while the operator drags)
   * can never shift the target out from under a gesture. Optional on the wire:
   * legacy / brain-authored plans carry none and are stamped at load/save.
   */
  id?: string;
  /** Transcript-derived join key used only until code binds graphicsDecisions.graphicId. */
  semanticBeatId?: string;
  /** Profile-owned information anatomy; distinct forms may share one renderer kind. */
  informationForm?: string;
  /** Profile-owned macro layout, e.g. cream rail or dark presenter-PIP canvas. */
  chassis?: "cream" | "dark";
  outStart: number;
  outEnd: number;
  kind: string;
  anchor?: string;
  spec?: Record<string, unknown>;
  reason?: string;
  trigger?: string;
  /**
   * Explicit comp-canvas position (px on the comp's authored canvas, e.g.
   * 1080x1920 shorts) — WINS over anchor resolution at render; absent = the
   * anchor fallback. Written by the preview's drag-to-place (one commit per
   * gesture); never set on own-screen kinds (full-frame, not positionable).
   * Optional `scale` (0.25–1.5): the renderer scales the rendered comp clip
   * uniformly ABOUT the placement point (content bbox top-left stays pinned
   * at {x, y}); absent = 1.0 byte-identical. Own-screen never scales.
   */
  placement?: { x: number; y: number; scale?: number };
  /**
   * Measured painted-content bbox [x0, y0, x1, y1] in comp-canvas px
   * (UNSCALED), stamped by the preview's drag/scale commit from the in-iframe
   * measurement (use-comp-html.useContentOrigin — the same settled probe
   * times as the render's alpha probe, minus soft-shadow margins). Feeds the
   * plan lint's SAFE_BOX box check (plan_lint_motion._placed_box) so a placed
   * entry's warn net isn't point-degenerate (geometry contract v3 item #6e).
   * Cleared together with `placement` on auto-position reset.
   */
  contentBBox?: [number, number, number, number];
}

export interface PunchIn {
  id?: string;
  outStart: number;
  outEnd: number;
  zoom?: number;
  kind?: string;
  ramp?: { direction?: string; ratePctPerS?: number };
  role?: string;
}

export interface Transition {
  id?: string;
  outTime: number;
  kind: string;
  sfx?: boolean;
}

/** OUTPUT-time dialogue gain window, applied BASE-side (pre-master). */
export interface AudioGainEntry {
  id?: string;
  outStart: number;
  outEnd: number;
  dB: number;
}

/** Dialogue cleanup preset, BASE-side (catalog: producer_config.AUDIO_ENHANCE). */
export interface AudioEnhance {
  preset: "voice" | "voice-rnn" | "voice-strong" | "separate";
}

/** Music bed, applied at ASSEMBLE time (post-master, audio-only, video copied). */
export interface MusicSpec {
  enabled: boolean;
  path?: string;
  assetId?: string;
  duck?: boolean;
  /** How far under the dialogue the bed sits at rest (dB; smaller = louder music). */
  gapDb?: number;
}

/** Normalized [x, y, w, h] rect on the SOURCE frame — each component 0-1. */
export type CropRect = [number, number, number, number];

export interface SplitCell {
  crop?: CropRect;
  /** Top cell only: its share of the output height (0.3-0.7, default 0.5). */
  frac?: number;
}

/**
 * plan.reframe — BASE-side layout contract (any change flips the base
 * fingerprint → smart re-render rebuilds the base, ~3 min). `layout` absent =
 * today's behavior (fill). Split renders ONLY for 9:16 shorts.
 */
export interface ReframeSpec {
  strategy?: string;
  layout?: "fill" | "split";
  /** Fill-mode manual override — wins over the automatic face crop. */
  crop?: CropRect;
  split?: { top?: SplitCell; bottom?: SplitCell };
  /** Reserved for the tracker; only `false` is accepted for v1. */
  track?: boolean;
}

export type GraphicsDecisionAction = "graphic" | "broll" | "omit";

/** Transcript-bound disposition for one deterministic introSemanticBeats row. */
export interface GraphicsDecision {
  beatId: string;
  decision: GraphicsDecisionAction;
  /** Required when decision="graphic"; must be one of the beat's compatibleKinds. */
  kind?: string;
  /** Required by a visualProfile; must be one of the beat's compatibleForms. */
  informationForm?: string;
  /** Macro-layout receipt derived from informationForm, never chosen ad hoc. */
  chassis?: "cream" | "dark";
  /** Controller-minted identity of the one graphicsTrack entry realizing this beat. */
  graphicId?: string;
  /** Other compatible anatomies explicitly rejected; fixed catalog order is not rank. */
  alternativesConsidered?: string[];
  /** Profile-owned information forms rejected before selecting informationForm. */
  alternativeFormsConsidered?: string[];
  /** Why the chosen anatomy expresses this transcript beat better than those alternatives. */
  selectionReason?: string;
  /** Required when recent approved-project history proves this chosen kind is overused. */
  reuseReason?: string;
  /** Specific editorial rationale; the Python contract requires 20+ characters. */
  reason: string;
}

export interface EditPlan {
  cutTrack?: CutSegment[];
  graphicsTrack?: GraphicEntry[];
  /** Preserved source-derived intro obligations; never inferred from card count. */
  graphicsDecisions?: GraphicsDecision[];
  punchIns?: PunchIn[];
  transitions?: Transition[];
  audioGain?: AudioGainEntry[];
  audioEnhance?: AudioEnhance;
  music?: MusicSpec;
  reframe?: ReframeSpec;
  target?: {
    mode?: string;
    durationTargetS?: number;
    scope?: string;
    excerpt?: boolean;
    /** Explicit produced/full longform grammar authority. */
    graphicsStyle?: "cutaway-only" | "overlay-rich" | "face-bridge";
    graphicsStyleRationale?: string;
    /** Executable grammar contract used by planner, renderer, Palmier, and QC. */
    visualProfile?: "nateherk-editorial-v1";
  };
  planVersion?: number;
}

/** Parse pasted/loaded plan text into an EditPlan, or null if it isn't JSON. */
export function parsePlan(text: string): EditPlan | null {
  try {
    return JSON.parse(text) as EditPlan;
  } catch {
    return null;
  }
}

export { GRAPHIC_ID_RE, newGraphicId, reconcileGraphicIds } from "./graphic-ids";

/** A short human label for a graphic block, derived from its kind + spec. */
export function graphicLabel(g: GraphicEntry): string {
  const spec = g.spec ?? {};
  const s = (k: string): string => (typeof spec[k] === "string" ? (spec[k] as string) : "");
  const words = s("words");
  if (words) return words;
  const title = s("titleBase") || s("title");
  if (title) return title;
  if (g.kind.startsWith("icon-badge") || g.kind === "chip-row") {
    const icons = ["icon1", "icon2", "icon3"]
      .map((k) => s(k))
      .filter(Boolean)
      .map((f) => f.replace(/\.svg$/, ""));
    return icons.length ? icons.join(" · ") : "icons";
  }
  return g.kind;
}

/** Display block addressed by stable id; unreconciled id-less entries are skipped. */
export interface GraphicBlock {
  id: string;
  start: number;
  end: number;
  kind: string;
  label: string;
  ownScreen: boolean;
}

export function graphicBlocks(plan: EditPlan): GraphicBlock[] {
  const out: GraphicBlock[] = [];
  for (const g of plan.graphicsTrack ?? []) {
    if (!g.id) continue; // unreconciled — not addressable; reconcileGraphicIds runs at load
    out.push({
      id: g.id,
      start: g.outStart,
      end: g.outEnd,
      kind: g.kind,
      label: graphicLabel(g),
      ownScreen: g.anchor === "own-screen",
    });
  }
  return out;
}

/** Output-time windows for each cut segment (source length ÷ speed, concatenated). */
export function cutWindows(plan: EditPlan): { start: number; end: number; sourceId: string }[] {
  let acc = 0;
  const out: { start: number; end: number; sourceId: string }[] = [];
  for (const c of plan.cutTrack ?? []) {
    const len = (c.end - c.start) / (c.speed ?? 1);
    out.push({ start: acc, end: acc + len, sourceId: c.sourceId });
    acc += len;
  }
  return out;
}

/** Total output duration = sum of the cut windows (fallback when no <video> yet). */
export function planDuration(plan: EditPlan): number {
  const windows = cutWindows(plan);
  return windows.length ? windows[windows.length - 1].end : plan.target?.durationTargetS ?? 0;
}

/**
 * Map a SOURCE-time second of `sourceId` to its OUTPUT-time second through the
 * cutTrack (piecewise linear — same arithmetic as `cutWindows`). Returns null
 * when the source moment is not kept by any segment (i.e. it is cut).
 */
export function sourceToOutput(
  cutTrack: CutSegment[],
  sourceId: string,
  sourceTime: number,
): number | null {
  let acc = 0;
  for (const c of cutTrack) {
    const len = (c.end - c.start) / (c.speed ?? 1);
    if (c.sourceId === sourceId && sourceTime >= c.start && sourceTime < c.end) {
      return acc + (sourceTime - c.start) / (c.speed ?? 1);
    }
    acc += len;
  }
  return null;
}

/**
 * Map an OUTPUT-time second back to the SOURCE moment it shows — the inverse
 * of `sourceToOutput` (same piecewise-linear arithmetic as `cutWindows`).
 * Returns null when the output time falls outside every cut window (before 0
 * or past the end of the last segment).
 */
export function outputToSource(
  cutTrack: CutSegment[],
  outputTime: number,
): { sourceId: string; tSrc: number } | null {
  let acc = 0;
  for (const c of cutTrack) {
    const speed = c.speed ?? 1;
    const len = (c.end - c.start) / speed;
    if (outputTime >= acc && outputTime < acc + len) {
      return { sourceId: c.sourceId, tSrc: c.start + (outputTime - acc) * speed };
    }
    acc += len;
  }
  return null;
}

/**
 * Split the cutTrack segment under OUTPUT time `outputTime` into two segments
 * at the corresponding SOURCE moment (same piecewise arithmetic as
 * `outputToSource`) — the timeline's S-key/Split action. The two halves play
 * back identically; the new seam enables half-removal via range-select.
 *
 * Returns the new track, or null when there is nothing to split: the time
 * falls outside every cut window, or maps within `epsilonS` of an existing
 * seam (a split there would mint a zero-length fragment). Callers guard on
 * null and skip the undo push — a no-op must not dirty the plan.
 */
export function splitSegmentAt(
  cutTrack: CutSegment[],
  outputTime: number,
  epsilonS = 0.01,
): CutSegment[] | null {
  let acc = 0;
  for (let i = 0; i < cutTrack.length; i++) {
    const c = cutTrack[i];
    const speed = c.speed ?? 1;
    const len = (c.end - c.start) / speed;
    if (outputTime >= acc && outputTime < acc + len) {
      const tSrc = c.start + (outputTime - acc) * speed;
      if (tSrc - c.start < epsilonS || c.end - tSrc < epsilonS) return null; // at a seam
      const out = cutTrack.map((s) => ({ ...s }));
      out.splice(i, 1, { ...c, end: tSrc }, { ...c, start: tSrc });
      return out;
    }
    acc += len;
  }
  return null; // outside every cut window
}

// cutTrack surgery (strike-to-cut + restore + output-range cut) lives in
// cut-track.ts (300-line budget); re-exported here so consumers keep one
// import surface.
export { removeSourceRange, addSourceRange, cutOutputRange } from "./cut-track";
