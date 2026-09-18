export interface GraphicIdentityEntry {
  id?: string;
  semanticBeatId?: string;
}

export interface GraphicIdentityDecision {
  beatId: string;
  decision: string;
  graphicId?: string;
}

export interface GraphicIdentityPlan {
  graphicsTrack?: GraphicIdentityEntry[];
  graphicsDecisions?: GraphicIdentityDecision[];
}

/** The canonical graphic-id shape: `g-` + 8 base36 chars. */
export const GRAPHIC_ID_RE = /^g-[0-9a-z]{8}$/;

/** Mint a fresh, well-formed graphic id (`g-<8 base36>`). */
export function newGraphicId(): string {
  let value = "";
  while (value.length < 8) value += Math.random().toString(36).slice(2);
  return `g-${value.slice(0, 8)}`;
}

function freshId(seen: Set<string>): string {
  let value = newGraphicId();
  while (seen.has(value)) value = newGraphicId();
  return value;
}

function reconcileTrack<T extends GraphicIdentityPlan>(plan: T): {
  track: GraphicIdentityEntry[];
  minted: number;
  reminted: number;
  changed: boolean;
} {
  const seen = new Set<string>();
  let minted = 0;
  let reminted = 0;
  const track = (plan.graphicsTrack ?? []).map((entry) => {
    const id = entry.id;
    if (typeof id === "string" && GRAPHIC_ID_RE.test(id) && !seen.has(id)) {
      seen.add(id);
      return entry;
    }
    const next = freshId(seen);
    seen.add(next);
    if (id == null) minted += 1;
    else reminted += 1;
    return { ...entry, id: next };
  });
  return { track, minted, reminted, changed: minted + reminted > 0 };
}

function uniqueBeatIds(track: GraphicIdentityEntry[]): Map<string, string> {
  const grouped = new Map<string, string[]>();
  for (const entry of track) {
    if (!entry.semanticBeatId || !entry.id) continue;
    grouped.set(entry.semanticBeatId, [...(grouped.get(entry.semanticBeatId) ?? []), entry.id]);
  }
  return new Map([...grouped].flatMap(([beatId, ids]) => ids.length === 1
    ? [[beatId, ids[0]] as const] : []));
}

function bindDecisions(
  decisions: GraphicIdentityDecision[] | undefined,
  track: GraphicIdentityEntry[],
): { decisions: GraphicIdentityDecision[] | undefined; bound: number; changed: boolean } {
  if (!decisions?.length) return { decisions, bound: 0, changed: false };
  const validIds = new Set(track.map((entry) => entry.id).filter((id): id is string => !!id));
  const byBeat = uniqueBeatIds(track);
  let changed = false;
  let bound = 0;
  const next = decisions.map((decision) => {
    if (decision.decision !== "graphic") {
      if (!decision.graphicId) return decision;
      changed = true;
      const rest = { ...decision };
      delete rest.graphicId;
      return rest;
    }
    const resolved = validIds.has(decision.graphicId ?? "")
      ? decision.graphicId : byBeat.get(decision.beatId);
    if (!resolved || resolved === decision.graphicId) return decision;
    changed = true;
    bound += 1;
    return { ...decision, graphicId: resolved };
  });
  return { decisions: changed ? next : decisions, bound, changed };
}

/** Mint track ids and bind transcript decisions through semanticBeatId. */
export function reconcileGraphicIds<T extends GraphicIdentityPlan>(plan: T): {
  plan: T;
  minted: number;
  reminted: number;
  bound: number;
} {
  if (!plan.graphicsTrack?.length) {
    return { plan, minted: 0, reminted: 0, bound: 0 };
  }
  const track = reconcileTrack(plan);
  const decisions = bindDecisions(plan.graphicsDecisions, track.track);
  if (!track.changed && !decisions.changed) {
    return { plan, minted: 0, reminted: 0, bound: 0 };
  }
  return {
    plan: { ...plan, graphicsTrack: track.track,
      ...(decisions.decisions ? { graphicsDecisions: decisions.decisions } : {}) },
    minted: track.minted,
    reminted: track.reminted,
    bound: decisions.bound,
  };
}
