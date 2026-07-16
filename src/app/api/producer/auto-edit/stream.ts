// Shared shapes + tiny stream plumbing for the AUTO-EDIT lane. The route
// streams SSE; both child processes (claude CLI, assemble.py) emit
// newline-delimited JSON on stdout that gets re-framed as `data:` lines.
import {
  AUDIO_ENHANCE_PRESETS,
  mimicLaneConflicts,
  PACES,
  STYLES,
  validateLaneOverrides,
  validateReferenceIntent,
  type Lane,
  type LaneDirective,
  type Mode,
  type Pace,
  type ReferenceIntent,
  type Style,
} from "@/lib/producer/intent-presets";
import type { AudioEnhance } from "@/lib/producer/edit-plan";
import type { TemplateUsageAuthority } from "@/lib/server/template-usage-history";

export const AUTO_EDIT_SCOPES = ["trim", "light", "produced", "full"] as const;
export type AutoEditScope = (typeof AUTO_EDIT_SCOPES)[number];

/** Operator-intent extras riding on the POST body (from the stored project
 * intent) — all optional; the prompt honors what's present. */
export interface AutoEditIntent {
  lanes?: Partial<Record<Lane, LaneDirective>>;
  mode?: Mode;
  excerpt?: boolean;
  brief?: string;
  pace?: Pace;
  /** Measured style grammar — the prompt tells the brain to READ its doc. */
  style?: Style;
  reference?: ReferenceIntent;
  music?: boolean;
  audioEnhance?: AudioEnhance;
}

function assertMimicLaneContract(
  body: Record<string, unknown>,
  intent: AutoEditIntent,
): void {
  if (intent.reference?.strategy !== "mimic") return;
  const scope = body.scope as AutoEditScope;
  if (!AUTO_EDIT_SCOPES.includes(scope)) {
    throw new Error("a valid scope is required when reference strategy is \"mimic\"");
  }
  const conflicts = mimicLaneConflicts({ scope, lanes: intent.lanes ?? {} });
  if (conflicts.length) {
    throw new Error(`reference strategy "mimic" requires every engagement lane; unavailable: ${conflicts.join(", ")}`);
  }
}

function optionalBrief(body: Record<string, unknown>): string | undefined {
  if (body.brief === undefined) return undefined;
  if (typeof body.brief !== "string") throw new Error("brief must be a string");
  const brief = body.brief.trim();
  if (!brief || brief.length > 1200 || brief.includes("\0")) {
    throw new Error("brief must be 1–1200 characters and contain no null bytes");
  }
  return brief;
}

function optionalEnum<T extends string>(
  body: Record<string, unknown>,
  key: string,
  values: readonly T[],
): T | undefined {
  if (body[key] === undefined) return undefined;
  if (!values.includes(body[key] as T)) {
    throw new Error(`${key} must be one of: ${values.join(", ")}`);
  }
  return body[key] as T;
}

function optionalMode(body: Record<string, unknown>): Mode | undefined {
  if (body.mode === undefined) return undefined;
  if (body.mode !== "short" && body.mode !== "longform") {
    throw new Error(`mode must be "short" or "longform", got ${JSON.stringify(body.mode)}`);
  }
  return body.mode;
}

function parseReference(body: Record<string, unknown>, out: AutoEditIntent): void {
  if (body.reference === undefined) return;
  if (!out.mode) throw new Error("mode is required when reference is set");
  out.reference = validateReferenceIntent(body.reference, out.mode);
  if (out.reference.strategy === "extend" && out.style !== out.reference.targetStyle) {
    throw new Error("style must equal reference.targetStyle for strategy \"extend\"");
  }
  if (out.reference.strategy === "extend" && out.pace !== out.reference.targetStyle) {
    throw new Error("pace must equal reference.targetStyle for strategy \"extend\"");
  }
  if (out.reference.strategy !== "extend" && out.style) {
    throw new Error(`style must stay unset for reference strategy ${JSON.stringify(out.reference.strategy)}`);
  }
  assertMimicLaneContract(body, out);
}

function parseMusic(body: Record<string, unknown>): boolean | undefined {
  if (body.music === undefined) return undefined;
  if (typeof body.music !== "boolean") throw new Error("music must be a boolean");
  return body.music;
}

function parseExcerpt(body: Record<string, unknown>, mode?: Mode): boolean | undefined {
  if (body.excerpt === undefined) return undefined;
  if (typeof body.excerpt !== "boolean") throw new Error("excerpt must be a boolean");
  if (body.excerpt && mode !== "longform") {
    throw new Error("excerpt is valid only for longform edits");
  }
  return body.excerpt;
}

function parseAudioEnhance(body: Record<string, unknown>): AudioEnhance | undefined {
  if (body.audioEnhance === undefined) return undefined;
  const preset = (body.audioEnhance as { preset?: unknown } | null)?.preset;
  if (!(AUDIO_ENHANCE_PRESETS as readonly string[]).includes(preset as string)) {
    throw new Error(`audioEnhance.preset must be one of: ${AUDIO_ENHANCE_PRESETS.join(", ")}`);
  }
  return { preset: preset as AudioEnhance["preset"] };
}

/** Parse the optional intent extras off the auto-edit body — malformed values
 * THROW (fail loudly; a typo'd lane must not silently run the produced stack). */
export function parseAutoEditIntent(body: Record<string, unknown>): AutoEditIntent | undefined {
  const out: AutoEditIntent = {
    brief: optionalBrief(body),
    mode: optionalMode(body),
    pace: optionalEnum(body, "pace", PACES),
    style: optionalEnum(body, "style", STYLES),
    music: parseMusic(body),
    audioEnhance: parseAudioEnhance(body),
  };
  out.excerpt = parseExcerpt(body, out.mode);
  if (body.lanes !== undefined) out.lanes = validateLaneOverrides(body.lanes);
  parseReference(body, out);
  for (const key of Object.keys(out) as Array<keyof AutoEditIntent>) {
    if (out[key] === undefined) delete out[key];
  }
  return Object.keys(out).length ? out : undefined;
}

export interface AutoEditCtx {
  dir: string; // the producer dir (holds edit_plan.json / base_final.mp4)
  scope: AutoEditScope;
  intent?: AutoEditIntent;
  referenceStudy?: ResolvedReferenceStudy;
  planPath: string;
  manifestPath: string;
  transcriptsDir: string; // dirname(manifestPath) — transcripts live beside it
  /** Immutable doctrine authority captured before the first writer starts.
   * Runtime-only: request identity deliberately excludes this field. */
  doctrine?: AutoEditDoctrineAuthority;
  /** Immutable renderer/gate/template bytes used by this run. Runtime-only:
   * request identity deliberately excludes this field. */
  pipeline?: AutoEditPipelineAuthority;
  /** Approved-project graphic-form memory captured before the writer launches. */
  templateUsage?: TemplateUsageAuthority;
  /** Stable Claude Code conversation used by cut authoring, visual authoring,
   * and the later Palmier live-build execution turn. Runtime-only. */
  brainSessionId?: string;
  /** True only after Claude stream output proved that this UUID exists. */
  brainSessionEstablished?: boolean;
}

export interface AutoEditDoctrineAuthority {
  runId: string;
  doctrineHash: string;
  snapshotPath: string;
  files: Record<string, string>;
}

export interface PipelineAuthorityFile {
  path: string;
  hash: string;
}

export interface AutoEditPipelineAuthority {
  schemaVersion: 1;
  runId: string;
  digest: string;
  snapshotRoot: string;
  lockPath: string;
  files: PipelineAuthorityFile[];
}

/** Filesystem-resolved, fully studied reference supplied by the server library. */
export interface ResolvedReferenceStudy {
  id: string;
  title: string;
  mode: Mode;
  dir: string;
  profilePath: string;
  deepStudyPath: string;
  representativeFrames: string[];
}

/** Send one SSE event object (already-JSON payloads go through sendRaw). */
export type Send = (obj: Record<string, unknown>) => void;
/** Send one pre-serialized NDJSON line as an SSE data frame. */
export type SendRaw = (line: string) => void;

/**
 * Incremental line splitter for a child's stdout. Returns a push(chunk)
 * handler plus flush() for the unterminated tail on process close.
 */
export function lineSplitter(onLine: (line: string) => void): {
  push: (chunk: string) => void;
  flush: () => void;
} {
  let buf = "";
  return {
    push(chunk: string) {
      buf += chunk;
      const parts = buf.split("\n");
      buf = parts.pop() || "";
      for (const line of parts) if (line.trim()) onLine(line);
    },
    flush() {
      if (buf.trim()) onLine(buf);
      buf = "";
    },
  };
}

/** Rolling tail collector for stderr (last `keep` chars). */
export function tailCollector(keep = 800): { push: (chunk: string) => void; get: () => string } {
  let tail = "";
  return {
    push(chunk: string) {
      tail = (tail + chunk).slice(-keep);
    },
    get: () => tail,
  };
}

export const SSE_HEADERS = {
  "Content-Type": "text/event-stream",
  "Cache-Control": "no-cache",
  Connection: "keep-alive",
  "X-Accel-Buffering": "no",
} as const;

/** A pipeline failure whose message is already operator-readable. */
export class AutoEditError extends Error {}
