import type {
  SurgicalEditLane,
  SurgicalEditScope,
} from "@/lib/producer/surgical-edit";
import {
  palmierNativeTools,
  type PalmierNativeTool,
} from "./palmier-native-prompt";

const SHA256 = /^[0-9a-f]{64}$/;
const DRAFT_KEYS = ["schemaVersion", "lanes", "operations"] as const;
const OPERATION_KEYS = ["tool", "args", "reason"] as const;

export interface PalmierNativeDraft {
  schemaVersion: 1;
  lanes: string[];
  operations: Array<{
    tool: PalmierNativeTool;
    args: Record<string, unknown>;
    reason: string;
  }>;
}

export interface PalmierNativeAuthority {
  schemaVersion: 1;
  authority: "palmier";
  projectId: string;
  timelineId: string;
  fingerprint: string;
  readbackCoverage: { complete: true };
  timeline: Record<string, unknown>;
}

export interface PalmierNativeResult {
  timelineId: string;
  fingerprint: string;
  operationCount: number;
}

function record(value: unknown, label: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} must be an object`);
  }
  return value as Record<string, unknown>;
}

function exactKeys(
  value: Record<string, unknown>,
  keys: readonly string[],
  label: string,
): void {
  const allowed = new Set(keys);
  const extra = Object.keys(value).filter((key) => !allowed.has(key));
  const missing = keys.filter((key) => !(key in value));
  if (extra.length || missing.length) {
    throw new Error(`${label} keys are invalid; missing=${missing.join(",") || "none"} extra=${extra.join(",") || "none"}`);
  }
}

function text(value: unknown, label: string, max = 1_000): string {
  if (typeof value !== "string" || !value.trim() || value.length > max) {
    throw new Error(`${label} must be a non-empty string of at most ${max} characters`);
  }
  return value;
}

function validateOperation(
  value: unknown,
  index: number,
  allowed: ReadonlySet<PalmierNativeTool>,
  scope: SurgicalEditScope,
): PalmierNativeDraft["operations"][number] {
  const label = `Palmier native operation ${index + 1}`;
  const row = record(value, label);
  exactKeys(row, OPERATION_KEYS, label);
  const tool = row.tool as PalmierNativeTool;
  if (typeof row.tool !== "string" || !allowed.has(tool)) {
    throw new Error(`${label} is outside the controller-owned lane scope`);
  }
  const args = record(row.args, `${label}.args`);
  if (!operationLanes(tool, args).some((lane) => scope.lanes.includes(lane))) {
    throw new Error(`${label} arguments are outside the controller-owned lane scope`);
  }
  return {
    tool,
    args,
    reason: text(row.reason, `${label}.reason`),
  };
}

export function validatePalmierNativeDraft(
  value: unknown,
  scope: SurgicalEditScope,
): PalmierNativeDraft {
  const row = record(value, "Palmier native draft");
  exactKeys(row, DRAFT_KEYS, "Palmier native draft");
  if (row.schemaVersion !== 1) throw new Error("Palmier native draft schemaVersion must be 1");
  if (!Array.isArray(row.lanes)
      || JSON.stringify(row.lanes) !== JSON.stringify(scope.lanes)) {
    throw new Error("Palmier native planner changed the controller-owned lane scope");
  }
  if (!Array.isArray(row.operations) || !row.operations.length || row.operations.length > 24) {
    throw new Error("Palmier native draft requires 1-24 operations");
  }
  const allowed = new Set(palmierNativeTools(scope));
  return {
    schemaVersion: 1,
    lanes: [...scope.lanes],
    operations: row.operations.map((item, index) => validateOperation(item, index, allowed, scope)),
  };
}

function propertyLanes(args: Record<string, unknown>): SurgicalEditLane[] {
  const keys = new Set(Object.keys(args).filter((key) => key !== "clipIds"));
  const lanes: SurgicalEditLane[] = [];
  if (["durationFrames", "trimStartFrame", "trimEndFrame", "speed"].some((key) => keys.has(key))) {
    lanes.push("cuts");
  }
  if (keys.has("volume")) lanes.push("audio");
  if (["opacity", "blendMode"].some((key) => keys.has(key))) lanes.push("graphics");
  if (keys.has("transform")) lanes.push("reframe");
  return [...new Set(lanes)];
}

function operationLanes(
  tool: PalmierNativeTool,
  args: Record<string, unknown>,
): SurgicalEditLane[] {
  if (tool === "set_clip_properties") return propertyLanes(args);
  if (tool === "set_keyframes") {
    if (args.property === "volume") return ["audio"];
    return ["motion"];
  }
  const fixed: Record<Exclude<PalmierNativeTool, "set_clip_properties" | "set_keyframes">, SurgicalEditLane[]> = {
    remove_silence: ["cuts"], remove_words: ["cuts"],
    ripple_delete_ranges: ["cuts"], split_clips: ["cuts"],
    apply_layout: ["reframe"], add_texts: ["graphics"],
    update_text: ["graphics", "captions"], add_captions: ["captions"],
    denoise_audio: ["audio"],
  };
  return fixed[tool];
}

export function validatePalmierNativeAuthority(value: unknown): PalmierNativeAuthority {
  const row = record(value, "Palmier native authority");
  const timeline = record(row.timeline, "Palmier native authority.timeline");
  const coverage = record(
    row.readbackCoverage, "Palmier native authority.readbackCoverage",
  );
  const projectId = text(row.projectId, "Palmier native authority.projectId", 200);
  const timelineId = text(row.timelineId, "Palmier native authority.timelineId", 200);
  if (row.schemaVersion !== 1 || row.authority !== "palmier") {
    throw new Error("Palmier native authority is not a schemaVersion 1 Palmier record");
  }
  if (timeline.id !== timelineId || !Array.isArray(timeline.tracks)) {
    throw new Error("Palmier native authority does not contain its complete working timeline");
  }
  if (typeof row.fingerprint !== "string" || !SHA256.test(row.fingerprint)) {
    throw new Error("Palmier native authority fingerprint is invalid");
  }
  if (coverage.complete !== true) {
    throw new Error("Palmier native authority readback is incomplete");
  }
  return {
    schemaVersion: 1,
    authority: "palmier",
    projectId,
    timelineId,
    fingerprint: row.fingerprint,
    readbackCoverage: { complete: true },
    timeline,
  };
}

function sameAuthority(
  left: { projectId?: unknown; timelineId?: unknown; fingerprint?: unknown },
  right: PalmierNativeAuthority,
): boolean {
  return left.projectId === right.projectId
    && left.timelineId === right.timelineId
    && left.fingerprint === right.fingerprint;
}

export function validateReconcileVerdict(
  value: unknown,
  authority: PalmierNativeAuthority,
): void {
  const row = record(value, "Palmier native reconcile verdict");
  const found = record(row.authority, "Palmier native reconcile verdict.authority");
  if (row.ok !== true || row.status !== "reconciled" || !sameAuthority(found, authority)) {
    throw new Error("Palmier native reconcile verdict does not match the saved working authority");
  }
}

export function validateExecuteVerdict(
  value: unknown,
  authority: PalmierNativeAuthority,
  requestHash: string,
  draft: PalmierNativeDraft,
): PalmierNativeResult {
  const row = record(value, "Palmier native execute verdict");
  const candidate = record(row.candidate, "Palmier native execute verdict.candidate");
  const base = record(candidate.base, "Palmier native execute verdict.candidate.base");
  const qc = record(candidate.qc, "Palmier native execute verdict.candidate.qc");
  if (row.ok !== true || row.status !== "candidate-staged"
      || candidate.schemaVersion !== 1 || candidate.status !== "edited") {
    throw new Error("Palmier native controller did not stage an edited candidate");
  }
  if (!sameAuthority(base, authority) || candidate.requestHash !== requestHash
      || JSON.stringify(candidate.lanes) !== JSON.stringify(draft.lanes)) {
    throw new Error("Palmier native candidate provenance does not match this request");
  }
  if (qc.status !== "pending" || qc.approved !== false) {
    throw new Error("Palmier native candidate bypassed the required QC checkpoint");
  }
  const operations = candidate.operations;
  if (!Array.isArray(operations) || operations.length !== draft.operations.length) {
    throw new Error("Palmier native candidate operation receipt is incomplete");
  }
  const timelineId = text(candidate.timelineId, "Palmier native candidate.timelineId", 200);
  if (timelineId === authority.timelineId || typeof candidate.fingerprint !== "string"
      || !SHA256.test(candidate.fingerprint)) {
    throw new Error("Palmier native candidate identity is invalid");
  }
  return { timelineId, fingerprint: candidate.fingerprint, operationCount: operations.length };
}

export function assertAuthorityUnchanged(
  value: unknown,
  expected: PalmierNativeAuthority,
): void {
  const current = validatePalmierNativeAuthority(value);
  if (!sameAuthority(current, expected)) {
    throw new Error("Palmier canonical authority changed while staging the candidate");
  }
}
