import { readFileSync } from "fs";
import {
  codexSettings,
  type CodexReasoningLevel,
} from "../../_lib/ai-provider";
import type { AutoEditCtx } from "./stream";

const BOUNDED_SOURCE_SECONDS = 120;

export interface AuthoringReasoningSelection {
  reasoning: CodexReasoningLevel;
  basis: "short" | "light" | "bounded-source" | "configured";
  sourceDurationS?: number;
}

function manifestDuration(manifestPath: string): number | undefined {
  try {
    const manifest = JSON.parse(readFileSync(manifestPath, "utf8")) as {
      sources?: Array<{ duration?: unknown; role?: unknown }>;
    };
    const sources = Array.isArray(manifest.sources) ? manifest.sources : [];
    const primary = sources.filter((source) => source.role === "primary");
    const selected = primary.length ? primary : sources;
    const durations = selected.map((source) => source.duration)
      .filter((value): value is number => typeof value === "number" && Number.isFinite(value) && value > 0);
    return durations.length ? durations.reduce((total, value) => total + value, 0) : undefined;
  } catch {
    return undefined;
  }
}

function capAtHigh(reasoning: CodexReasoningLevel): CodexReasoningLevel {
  return ["xhigh", "max", "ultra"].includes(reasoning) ? "high" : reasoning;
}

/** Keep bounded work bounded; preserve an explicit lower global effort. */
export function authoringReasoning(ctx: AutoEditCtx): AuthoringReasoningSelection {
  const configured = codexSettings().reasoning;
  const sourceDurationS = manifestDuration(ctx.manifestPath);
  if (ctx.intent?.mode === "short") {
    return { reasoning: capAtHigh(configured), basis: "short", sourceDurationS };
  }
  if (ctx.scope === "light") {
    return { reasoning: capAtHigh(configured), basis: "light", sourceDurationS };
  }
  if (sourceDurationS !== undefined && sourceDurationS <= BOUNDED_SOURCE_SECONDS) {
    return { reasoning: capAtHigh(configured), basis: "bounded-source", sourceDurationS };
  }
  return { reasoning: configured, basis: "configured", sourceDurationS };
}
