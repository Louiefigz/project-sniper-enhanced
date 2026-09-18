import type {
  ReferenceDecision,
  ReferenceMode,
  ReferenceStrategy,
} from "./reference-types";

const MODES = new Set<ReferenceMode>(["short", "longform"]);
const STRATEGIES = new Set<ReferenceStrategy>(["mimic", "extend", "new-style"]);
const TARGET_STYLES = new Set(["restrained", "punch", "slideware"]);
const KNOWN_STYLE_NAMES = new Set(["restrained", "punch", "slideware"]);
const FIELDS = new Set(["id", "mode", "strategy", "targetStyle", "candidateStyleName"]);
const STORED_FIELDS = new Set(["schemaVersion", "referenceId", "mode", "strategy",
  "targetStyle", "candidateStyleName", "decidedAt"]);

function optionalName(value: unknown, field: string): string | null {
  if (value == null || value === "") return null;
  if (typeof value !== "string" || value.trim().length < 2 || value.trim().length > 80 || /[\r\n\0]/.test(value)) {
    throw new Error(`${field} must be a name from 2 to 80 characters`);
  }
  return value.trim();
}

export function parseReferenceDecision(body: Record<string, unknown>, decidedAt = new Date()): ReferenceDecision {
  const unknown = Object.keys(body).filter((key) => !FIELDS.has(key));
  if (unknown.length) throw new Error(`unknown decision field(s): ${unknown.sort().join(", ")}`);
  const id = typeof body.id === "string" ? body.id.trim() : "";
  if (!id) throw new Error("id is required");
  if (!MODES.has(body.mode as ReferenceMode)) throw new Error("mode must be short or longform");
  if (!STRATEGIES.has(body.strategy as ReferenceStrategy)) {
    throw new Error("strategy must be mimic, extend, or new-style");
  }
  const strategy = body.strategy as ReferenceStrategy;
  const targetStyle = optionalName(body.targetStyle, "targetStyle");
  const candidateStyleName = optionalName(body.candidateStyleName, "candidateStyleName");
  if (strategy === "extend" && !targetStyle) throw new Error("extend requires targetStyle");
  if (strategy === "extend" && body.mode !== "short") throw new Error("extend is shorts-only");
  if (targetStyle && !TARGET_STYLES.has(targetStyle)) {
    throw new Error("targetStyle must be restrained, punch, or slideware");
  }
  if (strategy === "new-style" && !candidateStyleName) {
    throw new Error("new-style requires candidateStyleName");
  }
  if (strategy === "new-style" && candidateStyleName && KNOWN_STYLE_NAMES.has(candidateStyleName.toLowerCase())) {
    throw new Error("new-style candidate must be outside Restrained, Punch, and Slideware; use extend instead");
  }
  if (strategy !== "extend" && targetStyle) throw new Error("targetStyle is extend-only");
  if (strategy !== "new-style" && candidateStyleName) {
    throw new Error("candidateStyleName is new-style-only");
  }
  return {
    schemaVersion: 1, referenceId: id, mode: body.mode as ReferenceMode,
    strategy, targetStyle, candidateStyleName, decidedAt: decidedAt.toISOString(),
  };
}

export function validStoredReferenceDecision(value: unknown, expectedId: string): value is ReferenceDecision {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const row = value as Record<string, unknown>;
  if (Object.keys(row).some((key) => !STORED_FIELDS.has(key))) return false;
  if (row.schemaVersion !== 1 || row.referenceId !== expectedId || typeof row.decidedAt !== "string") return false;
  try {
    const parsed = parseReferenceDecision({ id: row.referenceId, mode: row.mode,
      strategy: row.strategy, targetStyle: row.targetStyle,
      candidateStyleName: row.candidateStyleName });
    return parsed.mode === row.mode && parsed.strategy === row.strategy;
  } catch {
    return false;
  }
}
