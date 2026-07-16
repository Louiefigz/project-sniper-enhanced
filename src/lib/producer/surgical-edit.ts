export const SURGICAL_EDIT_LANES = [
  "cuts",
  "graphics",
  "motion",
  "captions",
  "broll",
  "audio",
  "music",
  "reframe",
] as const;

export type SurgicalEditLane = (typeof SURGICAL_EDIT_LANES)[number];

export interface SurgicalEditScope {
  lanes: SurgicalEditLane[];
}

const FIELDS_BY_LANE: Record<SurgicalEditLane, readonly string[]> = {
  cuts: ["cutTrack"],
  graphics: ["graphicsTrack"],
  motion: ["punchIns", "transitions", "treatmentMap"],
  captions: ["captions", "captionsTrack"],
  broll: ["brollTrack"],
  audio: ["audioGain", "audioEnhance"],
  music: ["music"],
  reframe: ["reframe"],
};

const REQUEST_PATTERNS: Record<SurgicalEditLane, RegExp> = {
  cuts: /\b(cut|trim|remove|delete|shorten|tighten|retake|pause|silence|filler|hook|pace|faster|slower|speed)\b/i,
  graphics: /\b(graphic|card|title|lower[- ]third|overlay|icon|badge|hyperframe|whiteboard|statement|quote|full[- ]screen|font|typography)\b/i,
  motion: /\b(transition|punch[- ]?in|zoom|motion|animate|animation|easing|crossfade|wipe|push[- ]?in)\b/i,
  captions: /\b(caption|subtitle|subtitles|karaoke|word[s]? on screen)\b/i,
  broll: /\b(b[- ]?roll|cutaway|cutaways|stock footage|insert shot)\b/i,
  audio: /\b(audio|dialogue|dialog|voice|volume|gain|noise|denoise|enhance|cleanup|clean up|loudness)\b/i,
  music: /\b(music|soundtrack|music bed|song|track bed|ducking)\b/i,
  reframe: /\b(reframe|crop|aspect|vertical|horizontal|landscape|portrait|split[- ]screen|face framing)\b/i,
};

function uniqueLanes(lanes: SurgicalEditLane[]): SurgicalEditLane[] {
  return SURGICAL_EDIT_LANES.filter((lane) => lanes.includes(lane));
}

/** Deterministic routing only; an LLM never chooses its own mutation scope. */
export function inferSurgicalEditScope(request: string): SurgicalEditScope | null {
  const lanes = uniqueLanes(
    SURGICAL_EDIT_LANES.filter((lane) => REQUEST_PATTERNS[lane].test(request)),
  );
  return lanes.length ? { lanes } : null;
}

export function parseSurgicalEditScope(value: unknown): SurgicalEditScope {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("edit scope is required");
  }
  const row = value as Record<string, unknown>;
  if (Object.keys(row).some((key) => key !== "lanes") || !Array.isArray(row.lanes)) {
    throw new Error("edit scope must contain only a lanes array");
  }
  const lanes = row.lanes.filter(
    (lane): lane is SurgicalEditLane =>
      typeof lane === "string" && SURGICAL_EDIT_LANES.includes(lane as SurgicalEditLane),
  );
  if (!lanes.length || lanes.length !== row.lanes.length || new Set(lanes).size !== lanes.length) {
    throw new Error(`edit scope lanes must be unique values from: ${SURGICAL_EDIT_LANES.join(", ")}`);
  }
  return { lanes: uniqueLanes(lanes) };
}

/** The client surfaces this scope, while the server independently recomputes it. */
export function validateRequestedSurgicalEditScope(
  request: string,
  value: unknown,
): SurgicalEditScope {
  const supplied = parseSurgicalEditScope(value);
  const inferred = inferSurgicalEditScope(request);
  if (!inferred) throw new Error("the request does not identify a supported edit lane");
  if (JSON.stringify(supplied.lanes) !== JSON.stringify(inferred.lanes)) {
    throw new Error(
      `supplied lanes ${supplied.lanes.join(", ")} do not match controller lanes ${inferred.lanes.join(", ")}`,
    );
  }
  return inferred;
}

export function surgicalScopeFields(scope: SurgicalEditScope): string[] {
  return [...new Set(scope.lanes.flatMap((lane) => FIELDS_BY_LANE[lane]))];
}

function stableValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(stableValue);
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, item]) => [key, stableValue(item)]),
  );
}

function sameJson(left: unknown, right: unknown): boolean {
  return JSON.stringify(stableValue(left)) === JSON.stringify(stableValue(right));
}

export function changedPlanFields(
  before: Record<string, unknown>,
  after: Record<string, unknown>,
): string[] {
  const keys = [...new Set([...Object.keys(before), ...Object.keys(after)])].sort();
  return keys.filter((key) => !sameJson(before[key], after[key]));
}

export function assertSurgicalPlanChange(
  before: Record<string, unknown>,
  after: Record<string, unknown>,
  scope: SurgicalEditScope,
): string[] {
  const changed = changedPlanFields(before, after);
  if (!changed.length) throw new Error("the editor returned without changing the plan");
  const allowed = new Set(surgicalScopeFields(scope));
  const outside = changed.filter((field) => !allowed.has(field));
  if (outside.length) {
    throw new Error(`the editor changed fields outside the requested scope: ${outside.join(", ")}`);
  }
  return changed;
}
