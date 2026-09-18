// INTENT vocabulary + presets — the operator's up-front answer to "how produced
// should this edit be?", captured on the ingest card and stored in project.json
// ("intent"). The vocabulary MIRRORS scripts/producer/edit_scope.py (the source
// of truth): LANES, the scope ladder, and the directive words are verbatim, and
// `resolveLanes` copies its semantics — "off"/"operator" always win; "auto" only
// activates a lane the scope includes. The tsx test parses edit_scope.py so the
// mirror cannot drift silently.
import type { AudioEnhance } from "./edit-plan";
import { parseShortDirection } from "./short-direction";

// edit_scope.py: LANES — the engagement lanes the operator can scope/override.
// The base cut (trim + reframe) is ALWAYS on and is not a lane.
export const LANES = ["motion", "graphics", "transitions", "captions", "broll", "credibility"] as const;
export type Lane = (typeof LANES)[number];

// edit_scope.py: SCOPES — the scope ladder (each tier activates more lanes).
export const SCOPES = ["trim", "light", "produced", "full"] as const;
export type Scope = (typeof SCOPES)[number];

/** Canonical plan delivery formats used by requests, prompts, and validation. */
export const MODES = ["short", "longform"] as const;
export type Mode = (typeof MODES)[number];

// edit_scope.py: _DIRECTIVE_WORDS. Asset-id LISTS (broll/graphics) exist in the
// python vocabulary but are skill-flow territory — the intent card never emits
// them, and `validateLaneOverrides` rejects them loudly.
export const DIRECTIVE_WORDS = ["off", "operator", "auto"] as const;
export type LaneDirective = (typeof DIRECTIVE_WORDS)[number];

// edit_scope.py: SCOPES lane activation map, verbatim.
export const SCOPE_LANE_DEFAULTS: Record<Scope, Record<Lane, boolean>> = {
  trim: { motion: false, graphics: false, transitions: false, captions: false, broll: false, credibility: false },
  light: { motion: true, graphics: false, transitions: false, captions: true, broll: false, credibility: false },
  produced: { motion: true, graphics: true, transitions: true, captions: true, broll: true, credibility: true },
  full: { motion: true, graphics: true, transitions: true, captions: true, broll: true, credibility: true },
};

// plan_lint_motion._pacing_profile maps target.pace -> producer_config
// MODES["short"]["pacing_<pace>"] (dashes -> underscores). Every entry here
// MUST have a matching pacing_* profile — the tsx test parses
// producer_config.py so a missing/renamed profile fails loudly.
export const PACES = ["talking-head", "client-reel", "restrained", "punch", "slideware"] as const;
export type Pace = (typeof PACES)[number];

// Built-in short-form styles, each a Sniper style specification (paths in
// src/lib/server/auto-edit-doctrine.ts STYLE_DOCTRINE). target.style tells the
// auto-edit brain WHICH specification to read before authoring; target.pace
// (same name) picks the matching pacing_<style> lint profile.
export const STYLES = ["restrained", "punch", "slideware"] as const;
export type Style = (typeof STYLES)[number];

/** How the editor should use one measured reference without copying its IP. */
export const REFERENCE_STRATEGIES = ["mimic", "extend", "new-style"] as const;
export type ReferenceStrategy = (typeof REFERENCE_STRATEGIES)[number];

// producer_config.AUDIO_ENHANCE catalog keys (mirrored by edit-plan.AudioEnhance).
export const AUDIO_ENHANCE_PRESETS = ["voice", "voice-rnn", "voice-strong", "separate"] as const;

/** Operator intent for a studied reference selected from the reference library. */
export interface ReferenceIntent {
  id: string;
  title: string;
  mode: Mode;
  strategy: ReferenceStrategy;
  /** Existing, closed style grammar to mimic or extend. Never a new style name. */
  targetStyle?: Style;
  /** Provisional human label; valid only when strategy is "new-style". */
  candidateStyleName?: string;
}

/** The stored shape (project.json "intent") — what the operator asked for. */
export interface ProjectIntent {
  mode: Mode;
  scope: Scope;
  /** Deliberate partial long-form render, such as a first-minute intro proof. */
  excerpt?: boolean;
  /** Plain-language creative direction supplied by the operator. */
  brief?: string;
  /** Requested native visual treatment; automatic choice when selected. */
  shortDirection?: import("./short-direction").ShortDirectionRequest;
  /** Per-lane overrides vs the scope default (edit_scope target.lanes). */
  lanes: Partial<Record<Lane, LaneDirective>>;
  pace?: Pace;
  /** Built-in style whose specification the brain must read before authoring. */
  style?: Style;
  /** Studied asset mechanics to apply to this edit. */
  reference?: ReferenceIntent;
  /** Music bed (plan.music at assemble) — NOT a lane; default off (house rule). */
  music?: boolean;
  audioEnhance?: AudioEnhance;
  /** Preset id this intent came from, or "custom" after lane edits. */
  preset?: string;
}

/**
 * Active state per lane — edit_scope.resolve_lanes semantics: a directive
 * overrides the scope; "auto" only takes effect if the scope activates the lane
 * (you cannot "auto" a lane a trim job excludes).
 */
export function resolveLanes(
  scope: Scope,
  overrides: Partial<Record<Lane, LaneDirective>> = {},
): Record<Lane, LaneDirective> {
  const base = SCOPE_LANE_DEFAULTS[scope];
  const out = {} as Record<Lane, LaneDirective>;
  for (const lane of LANES) {
    const d = overrides[lane];
    out[lane] = d === "off" || d === "operator" ? d : base[lane] ? "auto" : "off";
  }
  return out;
}

/**
 * Lanes unavailable to a mechanics mimic after scope + overrides.
 * B-roll is asset-dependent: an explicit `off` is the persisted capability
 * waiver used when no cutaways exist, so it may reduce fidelity but must not
 * make an otherwise valid reference edit impossible to launch.
 */
export function mimicLaneConflicts(
  intent: Pick<ProjectIntent, "scope" | "lanes">,
): Lane[] {
  const resolved = resolveLanes(intent.scope, intent.lanes);
  return LANES.filter((lane) => lane !== "broll" && resolved[lane] !== "auto");
}

/**
 * Map a desired ACTIVE lane set (the card's checkboxes) onto {scope, lanes}:
 * the LOWEST ladder scope whose defaults cover every active lane, plus "off"
 * overrides for scope-active lanes the operator unchecked. Invariant (tested):
 * resolveLanes(scope, lanes) is "auto" exactly on the active set.
 */
export function deriveScopeAndLanes(active: Record<Lane, boolean>): {
  scope: Scope;
  lanes: Partial<Record<Lane, LaneDirective>>;
} {
  // "produced" activates every lane, so the find always hits; "full" is the
  // same lane set (reachable only by explicit scope choice, never derived).
  const scope = (["trim", "light", "produced"] as Scope[]).find((s) =>
    LANES.every((l) => !active[l] || SCOPE_LANE_DEFAULTS[s][l]),
  ) as Scope;
  const lanes: Partial<Record<Lane, LaneDirective>> = {};
  for (const lane of LANES) {
    if (SCOPE_LANE_DEFAULTS[scope][lane] && !active[lane]) lanes[lane] = "off";
  }
  return { scope, lanes };
}

/** Validate a lanes-override object — malformed input THROWS (no-fallback rule:
 * a typo'd "no b-roll" must not silently run the full produced stack). */
export function validateLaneOverrides(v: unknown): Partial<Record<Lane, LaneDirective>> {
  if (v == null) return {};
  if (typeof v !== "object" || Array.isArray(v)) {
    throw new Error("lanes must be an object of {lane: directive}");
  }
  const out: Partial<Record<Lane, LaneDirective>> = {};
  for (const [lane, d] of Object.entries(v as Record<string, unknown>)) {
    if (!(LANES as readonly string[]).includes(lane)) {
      throw new Error(`unknown lane ${JSON.stringify(lane)} — one of ${[...LANES].sort().join(", ")}`);
    }
    if (Array.isArray(d)) {
      throw new Error(`lane ${lane}: asset lists are set via the producer skill, not the intent card — use a directive word`);
    }
    if (!(DIRECTIVE_WORDS as readonly string[]).includes(d as string)) {
      throw new Error(`lane ${lane} directive ${JSON.stringify(d)} invalid — one of ${[...DIRECTIVE_WORDS].sort().join(", ")}`);
    }
    out[lane as Lane] = d as LaneDirective;
  }
  return out;
}

const REFERENCE_KEYS = new Set([
  "id", "title", "mode", "strategy", "targetStyle", "candidateStyleName",
]);
const CLOSED_STYLE_NAMES = new Set(["restrained", "punch", "slideware"]);

function requiredReferenceText(value: unknown, field: string, maxLength: number): string {
  if (typeof value !== "string") throw new Error(`reference.${field} must be a string`);
  const text = value.trim();
  if (!text) throw new Error(`reference.${field} must not be empty`);
  if (text.length > maxLength || /[\r\n\0]/.test(text)) {
    throw new Error(`reference.${field} is too long or contains control characters`);
  }
  return text;
}

/** Validate a studied-reference selection independently of filesystem state. */
export function validateReferenceIntent(v: unknown, expectedMode?: Mode): ReferenceIntent {
  if (!v || typeof v !== "object" || Array.isArray(v)) {
    throw new Error("reference must be an object");
  }
  const o = v as Record<string, unknown>;
  const unknown = Object.keys(o).filter((key) => !REFERENCE_KEYS.has(key));
  if (unknown.length) throw new Error(`reference has unknown field(s): ${unknown.sort().join(", ")}`);
  const id = requiredReferenceText(o.id, "id", 160);
  if (!/^[A-Za-z0-9][A-Za-z0-9._:-]*$/.test(id)) {
    throw new Error("reference.id must be an opaque id, not a path");
  }
  const title = requiredReferenceText(o.title, "title", 240);
  if (o.mode !== "short" && o.mode !== "longform") {
    throw new Error('reference.mode must be "short" or "longform"');
  }
  if (expectedMode && o.mode !== expectedMode) {
    throw new Error(`reference.mode ${JSON.stringify(o.mode)} must match intent.mode ${JSON.stringify(expectedMode)}`);
  }
  if (!(REFERENCE_STRATEGIES as readonly unknown[]).includes(o.strategy)) {
    throw new Error(`reference.strategy must be one of: ${REFERENCE_STRATEGIES.join(", ")}`);
  }
  const ref: ReferenceIntent = { id, title, mode: o.mode, strategy: o.strategy as ReferenceStrategy };
  if (o.targetStyle !== undefined) {
    if (!(STYLES as readonly unknown[]).includes(o.targetStyle)) {
      throw new Error(`reference.targetStyle must be one of: ${STYLES.join(", ")}`);
    }
    if (ref.mode !== "short") throw new Error("reference.targetStyle is shorts-only");
    ref.targetStyle = o.targetStyle as Style;
  }
  if (o.candidateStyleName !== undefined) {
    ref.candidateStyleName = requiredReferenceText(o.candidateStyleName, "candidateStyleName", 120);
  }
  if (ref.strategy === "extend" && !ref.targetStyle) {
    throw new Error("reference.targetStyle is required for strategy \"extend\"");
  }
  if (ref.strategy !== "extend" && ref.targetStyle) {
    throw new Error(`reference.targetStyle is not allowed for strategy ${JSON.stringify(ref.strategy)}`);
  }
  if (ref.strategy === "new-style" && !ref.candidateStyleName) {
    throw new Error("reference.candidateStyleName is required for strategy \"new-style\"");
  }
  if (ref.strategy === "new-style" && ref.candidateStyleName &&
      CLOSED_STYLE_NAMES.has(ref.candidateStyleName.toLowerCase())) {
    throw new Error("reference.candidateStyleName must name a style outside Restrained, Punch, and Slideware");
  }
  if (ref.strategy !== "new-style" && ref.candidateStyleName) {
    throw new Error(`reference.candidateStyleName is not allowed for strategy ${JSON.stringify(ref.strategy)}`);
  }
  return ref;
}

/** Validate + normalize an intent payload from a request body — THROWS loudly. */
export function validateIntent(v: unknown): ProjectIntent {
  if (!v || typeof v !== "object" || Array.isArray(v)) throw new Error("intent must be an object");
  const o = v as Record<string, unknown>;
  if (o.mode !== "short" && o.mode !== "longform") {
    throw new Error(`intent.mode must be "short" or "longform", got ${JSON.stringify(o.mode)}`);
  }
  if (!(SCOPES as readonly string[]).includes(o.scope as string)) {
    throw new Error(`unknown scope ${JSON.stringify(o.scope)} — one of ${[...SCOPES].sort().join(", ")}`);
  }
  const intent: ProjectIntent = { mode: o.mode, scope: o.scope as Scope, lanes: validateLaneOverrides(o.lanes) };
  if (o.excerpt !== undefined) {
    if (typeof o.excerpt !== "boolean") throw new Error("intent.excerpt must be a boolean");
    if (o.excerpt && o.mode !== "longform") {
      throw new Error("intent.excerpt is valid only for longform edits");
    }
    intent.excerpt = o.excerpt;
  }
  if (o.brief !== undefined) {
    if (typeof o.brief !== "string") throw new Error("intent.brief must be a string");
    const brief = o.brief.trim();
    if (!brief) throw new Error("intent.brief must not be empty when provided");
    if (brief.length > 1200 || brief.includes("\0")) {
      throw new Error("intent.brief must be 1–1200 characters and contain no null bytes");
    }
    intent.brief = brief;
  }
  if (o.shortDirection !== undefined) intent.shortDirection = parseShortDirection(o.shortDirection, o.mode);
  if (o.pace !== undefined) {
    if (!(PACES as readonly string[]).includes(o.pace as string)) {
      throw new Error(`intent.pace must be one of: ${PACES.join(", ")}`);
    }
    intent.pace = o.pace as Pace;
  }
  if (o.style !== undefined) {
    if (!(STYLES as readonly string[]).includes(o.style as string)) {
      throw new Error(`intent.style must be one of: ${STYLES.join(", ")}`);
    }
    intent.style = o.style as Style;
  }
  if (o.reference !== undefined) {
    intent.reference = validateReferenceIntent(o.reference, intent.mode);
    if (intent.reference.strategy === "extend" && intent.style !== intent.reference.targetStyle) {
      throw new Error("intent.style must equal reference.targetStyle for strategy \"extend\"");
    }
    if (intent.reference.strategy === "extend" && intent.pace !== intent.reference.targetStyle) {
      throw new Error("intent.pace must equal reference.targetStyle for strategy \"extend\"");
    }
    if (intent.reference.strategy !== "extend" && intent.style) {
      throw new Error(`intent.style must stay unset for reference strategy ${JSON.stringify(intent.reference.strategy)}`);
    }
    const conflicts = intent.reference.strategy === "mimic" ? mimicLaneConflicts(intent) : [];
    if (conflicts.length) {
      throw new Error(`reference strategy "mimic" requires every engagement lane; unavailable: ${conflicts.join(", ")}`);
    }
  }
  if (o.music !== undefined) {
    if (typeof o.music !== "boolean") throw new Error("intent.music must be a boolean");
    intent.music = o.music;
  }
  if (o.audioEnhance !== undefined) {
    const preset = (o.audioEnhance as { preset?: unknown } | null)?.preset;
    if (!(AUDIO_ENHANCE_PRESETS as readonly string[]).includes(preset as string)) {
      throw new Error(`intent.audioEnhance.preset must be one of: ${AUDIO_ENHANCE_PRESETS.join(", ")}`);
    }
    intent.audioEnhance = { preset: preset as AudioEnhance["preset"] };
  }
  if (o.preset !== undefined) {
    if (typeof o.preset !== "string") throw new Error("intent.preset must be a string");
    intent.preset = o.preset;
  }
  return intent;
}

/** Compact badge text for project cards / editor header, e.g. "SHORT · Light". */
export function intentBadge(intent: Pick<ProjectIntent, "mode" | "scope">): string {
  const mode = intent.mode === "short" ? "SHORT" : "LONG";
  return `${mode} · ${intent.scope[0].toUpperCase()}${intent.scope.slice(1)}`;
}

/** Plain-language names for the card's lane checkboxes (keys stay verbatim). */
export const LANE_LABELS: Record<Lane, string> = {
  motion: "zooms (punch-ins & aliveness)",
  graphics: "graphics (cards & chips)",
  transitions: "animations (seam transitions)",
  captions: "captions",
  broll: "b-roll cutaways",
  credibility: "credibility move (PIP/card)",
};

export interface IntentPreset {
  id: string;
  label: string;
  /** null = mode-agnostic (the card's Short|Long toggle decides). */
  mode: Mode | null;
  scope: Scope;
  lanes: Partial<Record<Lane, LaneDirective>>;
  pace?: Pace;
  /** Set on STYLE presets only — also what groups the card's chips. */
  style?: Style;
  /** Preset music state. Safety rule: presets may recommend, but never enable. */
  music?: false;
  audioEnhance?: AudioEnhance;
  will: string[];
  wont: string[];
}

/** Build the stored intent from a preset (mode-agnostic presets keep the toggle). */
export function presetToIntent(p: IntentPreset, fallbackMode: Mode): ProjectIntent {
  return {
    mode: p.mode ?? fallbackMode,
    scope: p.scope,
    lanes: { ...p.lanes },
    ...(p.pace ? { pace: p.pace } : {}),
    ...(p.style ? { style: p.style } : {}),
    ...(p.music !== undefined ? { music: p.music } : {}),
    ...(p.audioEnhance ? { audioEnhance: { ...p.audioEnhance } } : {}),
    preset: p.id,
  };
}

// ─── Preset catalog (data — descriptions state what WILL and WON'T happen) ───

export const INTENT_PRESETS: IntentPreset[] = [
  {
    id: "light-short",
    label: "Light short",
    mode: "short",
    scope: "light",
    lanes: {},
    audioEnhance: { preset: "voice-rnn" },
    will: [
      "Cut pauses, retakes and the cold-open (the base cut is always on)",
      "Clean the dialogue with voice-rnn (RNNoise)",
      "ONE hook title card in the opening",
      "Burned karaoke captions",
      "Subtle aliveness motion (slow creep — no hard punch-ins)",
      "9:16 face-aware reframe + −14 LUFS master",
    ],
    wont: [
      "No other graphics (cards / chips / gauges)",
      "No b-roll cutaways",
      "No seam transitions",
      "No credibility PIP",
      "No music bed",
    ],
  },
  {
    id: "produced-short",
    label: "Produced short",
    mode: "short",
    scope: "produced",
    lanes: {},
    audioEnhance: { preset: "voice-rnn" },
    will: [
      "Cut pauses, retakes and the cold-open",
      "Clean the dialogue with voice-rnn (RNNoise)",
      "Hook card + graphics (cards / chips) where beats earn them",
      "Punch-ins, zooms and seam transitions",
      "B-roll cutaways from your pool",
      "Credibility move when the transcript claims one",
      "Burned karaoke captions",
      "9:16 face-aware reframe + −14 LUFS master",
    ],
    wont: [
      "Won't generate or source missing assets (that's beyond \"produced\")",
      "No music bed unless you tick Music",
    ],
  },
  {
    id: "longform-produced",
    label: "Longform produced",
    mode: "longform",
    scope: "produced",
    lanes: {},
    audioEnhance: { preset: "voice" },
    will: [
      "Cut pauses, retakes and the cold-open",
      "Clean steady room tone and hum with the measured voice preset",
      "Full engaging stack: section cards, punch-ins, transitions, b-roll, credibility move",
      "Front-loaded envelope: dense hook, breathing body",
      "Sidecar SRT + chapters (longform always ships caption files)",
      "16:9 kept as-is + −14 LUFS master",
    ],
    wont: [
      "Captions are NOT burned into the picture (sidecar SRT instead)",
      "Won't generate or source missing assets",
      "No music bed unless you tick Music",
    ],
  },
  {
    id: "trim-only",
    label: "Trim only",
    mode: null,
    scope: "trim",
    lanes: {},
    will: [
      "Cut pauses, retakes and the cold-open — the clean cut only",
      "Reframe + −14 LUFS master (always on)",
    ],
    wont: [
      "No captions, no hook card, no graphics",
      "No zooms / motion, no transitions",
      "No b-roll, no credibility move",
      "No music, no dialogue cleanup",
    ],
  },

  // ── STYLE presets — the three built-in Sniper style specifications (style
  // set = Styles group). will/wont cite the specification's anchors; pace picks
  // the matching pacing_<style> lint profile; style tells the auto-edit brain
  // which specification to read.
  {
    id: "restrained-light",
    label: "Restrained light",
    mode: "short",
    scope: "light",
    lanes: { motion: "off" }, // RESTRAINED_STYLE §3 Z1: no punch-ins, zoom ramps or creep
    pace: "restrained",
    style: "restrained",
    music: false, // RESTRAINED_STYLE §6 M1: no bed; the operator may still tick Music
    will: [
      "Plain captions carry the pace: short verbatim cues that replace each other, white, no box (RESTRAINED_STYLE §4 CAP1-CAP2)",
      "One thesis card from frame one — the clip's only graphic (§1 H1, §5, §11)",
      "Cuts only to remove flubs, retakes and dead air, placed where a caption changes (§2 C2, C5)",
      "A single uncut take is on-style — cuts are never added for rhythm (§2 C1, §9)",
      "9:16 face-aware reframe + −14 LUFS master with the true-peak ceiling (§6 M2)",
    ],
    wont: [
      "No zooms, punch-ins or slow creep (§3 Z1)",
      "No other graphics, receipts, pills, PIP or b-roll (§5, §7)",
      "No seam transitions (§7)",
      "No karaoke, coloured or boxed captions (§4 CAP2)",
      "No music bed unless you tick Music (§6 M1)",
      "No dialogue cleanup — natural pauses and breaths stay (§6 M3)",
    ],
  },
  {
    id: "punch-produced",
    label: "Punch produced",
    mode: "short",
    scope: "produced",
    // Every Punch seam is a hard cut; seam transitions stay off (PUNCH_STYLE §7).
    lanes: { transitions: "off" },
    pace: "punch",
    style: "punch",
    music: false, // PUNCH_STYLE §6 M1 recommends a bed; the operator checkbox still owns opt-in
    audioEnhance: { preset: "voice-rnn" },
    will: [
      "Cut engine: hard cuts between wide and tight framings on key words, at least 14 visual changes/min (PUNCH_STYLE §2 C1-C5)",
      "Two text layers: keyword lockups above the face + small replace-per-cue captions below it (§4)",
      "Word-locked list/diagram builds and blurred-footage takeovers where beats earn them (§5.4)",
      "Hook carried by a graphic from frame zero, not by a burst of cuts (§1 H2)",
      "Dead air stripped hard + voice-rnn cleanup; 9:16 reframe + −14 LUFS master (§2 C3)",
    ],
    wont: [
      "No dissolves, flashes or light leaks — every seam is a hard cut (§2 C6, §7)",
      "No karaoke captions — emphasis is an inline accent word or a lockup (§4 CAP1, CAP3)",
      "No slow zoom creep between cuts — the frame stays locked (§3 Z2)",
      "Music stays off until you explicitly tick Music (the style recommendation is never auto-enabled)",
      "Won't generate or source missing assets",
    ],
  },
  {
    id: "slideware-involved",
    label: "Slideware involved",
    mode: "short",
    scope: "full",
    // The style's no-zoom and hard-cut rules are operator-visible lane intent (SLIDEWARE_STYLE §4 AZ1-AZ2).
    lanes: { motion: "off", transitions: "off" },
    pace: "slideware",
    style: "slideware",
    music: false, // SLIDEWARE_STYLE §7 AM1 recommends a bed; the operator checkbox still owns opt-in
    will: [
      "Full-frame slide sections alternate with the talking head — one graphic economy per clip (SLIDEWARE_STYLE §3 AC3)",
      "Frame zero fully dressed + real proof inside the first 3 seconds (§2 AH1-AH2)",
      "Cuts land only at section boundaries — the slides provide the change of view (§3 AC1)",
      "Two caption skins: plain on footage, pill-backed on the slide canvas; bold is the only emphasis (§5 ACAP1-ACAP2)",
      "One accent colour across every slide, lockup and pill (§1 B1, §9 checklist)",
      "9:16 reframe + −14 LUFS master with the true-peak ceiling (§7 AM2)",
    ],
    wont: [
      "No punch-ins or zoom steps — the punchIns track stays empty (§4 AZ1)",
      "No seam transitions — every cut is hard (§4 AZ2)",
      "No karaoke or coloured captions (§5 ACAP1)",
      "Won't mix graphic economies — slide deck OR persistent ledger, never both (§3 AC3)",
      "Music stays off until you explicitly tick Music (the style recommendation is never auto-enabled)",
      "Won't fake evidence — every receipt shows real media, and every number shown is spoken (§6 E3)",
    ],
  },
];
