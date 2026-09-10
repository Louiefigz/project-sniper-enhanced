import { execFile } from "node:child_process";
import {
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import os from "node:os";
import path from "node:path";
import { promisify } from "node:util";
import { pythonInterpreter, SCRIPTS_DIR } from "../../_lib/spawn-python";
import { AutoEditError } from "./stream";
import { canonicalJsonSha256 } from "@/lib/server/auto-edit-hash";
import { currentCallerProcessDeadline } from "@/lib/server/caller-process-deadline";
import { CutPreviewProcessError, runCutPreviewProcess } from "./cut-preview-process";

const execFileAsync = promisify(execFile);
const SHA256 = /^[a-f0-9]{64}$/;
const SCRIPT = path.join(
  SCRIPTS_DIR, "producer", "edit", "compatibility_projection.py",
);
const PROJECTION_KEYS = [
  "approvedCutPlanHash", "compilerHash", "cutDecisionsDigest",
  "cutTrackDigest", "kind", "schemaVersion", "timelineMap", "timelineMapHash",
].sort();
const MAP_KEYS = ["outputDuration", "segments"].sort();
const SEGMENT_KEYS = [
  "audio_lead_s", "index", "out_end", "out_start", "source_id",
  "speed", "src_end", "src_start",
].sort();
const TIMELINE_UNITS = 1_000_000;

export interface CompatibilityTimelineSegmentV1 {
  index: number;
  source_id: string;
  src_start: number;
  src_end: number;
  speed: number;
  out_start: number;
  out_end: number;
  audio_lead_s: number;
}

export interface CompatibilityTimelineProjectionV1 {
  schemaVersion: 1;
  kind: "compatibility-timeline-projection";
  approvedCutPlanHash: string;
  cutTrackDigest: string;
  cutDecisionsDigest: string;
  compilerHash: string;
  timelineMap: {
    outputDuration: number;
    segments: CompatibilityTimelineSegmentV1[];
  };
  timelineMapHash: string;
}

function objectValue(value: unknown, label: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new AutoEditError(`${label} must be an object`);
  }
  return value as Record<string, unknown>;
}

function exactKeys(
  value: Record<string, unknown>,
  expected: string[],
  label: string,
): void {
  const actual = Object.keys(value).sort();
  if (actual.length !== expected.length
      || actual.some((key, index) => key !== expected[index])) {
    throw new AutoEditError(`${label} has unknown or missing fields`);
  }
}

function finiteNumber(value: unknown, label: string, minimum = 0): number {
  if (typeof value !== "number" || !Number.isFinite(value) || value < minimum) {
    throw new AutoEditError(`${label} must be a finite number >= ${minimum}`);
  }
  return value;
}

function parseSegment(value: unknown, position: number): CompatibilityTimelineSegmentV1 {
  const segment = objectValue(value, `timelineMap.segments[${position}]`);
  exactKeys(segment, SEGMENT_KEYS, `timelineMap.segments[${position}]`);
  const index = finiteNumber(segment.index, `segment ${position} index`);
  const sourceId = segment.source_id;
  if (!Number.isInteger(index) || index !== position
      || typeof sourceId !== "string" || !sourceId.trim()) {
    throw new AutoEditError(`timeline segment ${position} identity is malformed`);
  }
  const parsed = {
    index,
    source_id: sourceId,
    src_start: finiteNumber(segment.src_start, `segment ${position} src_start`),
    src_end: finiteNumber(segment.src_end, `segment ${position} src_end`),
    speed: finiteNumber(segment.speed, `segment ${position} speed`, Number.MIN_VALUE),
    out_start: finiteNumber(segment.out_start, `segment ${position} out_start`),
    out_end: finiteNumber(segment.out_end, `segment ${position} out_end`),
    audio_lead_s: finiteNumber(segment.audio_lead_s, `segment ${position} audio_lead_s`),
  };
  if (parsed.src_end <= parsed.src_start || parsed.out_end <= parsed.out_start) {
    throw new AutoEditError(`timeline segment ${position} has an empty range`);
  }
  return parsed;
}

function timelineUnits(value: number, label: string): number {
  const units = Math.floor(value * TIMELINE_UNITS + 0.5);
  const normalized = units / TIMELINE_UNITS;
  const tolerance = Number.EPSILON * Math.max(1, Math.abs(value)) * 4;
  if (!Number.isSafeInteger(units) || Math.abs(value - normalized) > tolerance) {
    throw new AutoEditError(`${label} is outside the V1 timeline quantization grid`);
  }
  return units;
}

function timelineHashPayload(timeline: CompatibilityTimelineProjectionV1["timelineMap"]) {
  return {
    quantization: "millionths-half-up-v1",
    outputDuration: timelineUnits(timeline.outputDuration, "timeline outputDuration"),
    segments: timeline.segments.map((segment) => ({
      index: segment.index,
      source_id: segment.source_id,
      src_start: timelineUnits(segment.src_start, `segment ${segment.index} src_start`),
      src_end: timelineUnits(segment.src_end, `segment ${segment.index} src_end`),
      speed: timelineUnits(segment.speed, `segment ${segment.index} speed`),
      out_start: timelineUnits(segment.out_start, `segment ${segment.index} out_start`),
      out_end: timelineUnits(segment.out_end, `segment ${segment.index} out_end`),
      audio_lead_s: timelineUnits(
        segment.audio_lead_s, `segment ${segment.index} audio_lead_s`,
      ),
    })),
  };
}

function assertTimelineContinuity(
  timeline: CompatibilityTimelineProjectionV1["timelineMap"],
): void {
  for (const [index, segment] of timeline.segments.entries()) {
    const expected = index === 0 ? 0 : timeline.segments[index - 1].out_end;
    if (segment.out_start !== expected) {
      throw new AutoEditError(`timeline segment ${index} is not output-contiguous`);
    }
  }
}

export function parseCompatibilityProjection(
  value: unknown,
  approvedCutPlanHash: string,
): CompatibilityTimelineProjectionV1 {
  const projection = objectValue(value, "compatibility timeline projection");
  exactKeys(projection, PROJECTION_KEYS, "compatibility timeline projection");
  const hashes = [
    projection.approvedCutPlanHash, projection.cutTrackDigest,
    projection.cutDecisionsDigest, projection.compilerHash,
    projection.timelineMapHash,
  ];
  if (projection.schemaVersion !== 1
      || projection.kind !== "compatibility-timeline-projection"
      || hashes.some((hash) => typeof hash !== "string" || !SHA256.test(hash))
      || projection.approvedCutPlanHash !== approvedCutPlanHash) {
    throw new AutoEditError("compatibility timeline projection identity is malformed");
  }
  const timeline = objectValue(projection.timelineMap, "timelineMap");
  exactKeys(timeline, MAP_KEYS, "timelineMap");
  if (!Array.isArray(timeline.segments) || timeline.segments.length === 0) {
    throw new AutoEditError("timelineMap.segments must be a non-empty array");
  }
  const segments = timeline.segments.map(parseSegment);
  const outputDuration = finiteNumber(timeline.outputDuration, "timelineMap.outputDuration");
  if (outputDuration !== segments.at(-1)?.out_end) {
    throw new AutoEditError("timelineMap output duration does not match its final segment");
  }
  const timelineMap = { outputDuration, segments };
  assertTimelineContinuity(timelineMap);
  if (canonicalJsonSha256(timelineHashPayload(timelineMap))
      !== projection.timelineMapHash) {
    throw new AutoEditError("timelineMapHash does not bind the stored timeline map");
  }
  return {
    ...(projection as unknown as Omit<CompatibilityTimelineProjectionV1, "timelineMap">),
    timelineMap,
  };
}

export async function compileCompatibilityProjection(
  planBytes: Buffer,
  approvedCutPlanHash: string,
): Promise<CompatibilityTimelineProjectionV1> {
  if (!SHA256.test(approvedCutPlanHash)) {
    throw new AutoEditError("approved cut plan hash is malformed");
  }
  const caller = currentCallerProcessDeadline();
  const temporary = mkdtempSync(path.join(os.tmpdir(), "sniper-compat-projection-"));
  const planPath = path.join(temporary, "edit_plan.json");
  const outputPath = path.join(temporary, "projection.json");
  let retain = false;
  try {
    writeFileSync(planPath, planBytes, { flag: "wx", mode: 0o600 });
    const args = [SCRIPT, planPath, approvedCutPlanHash, outputPath];
    if (caller) {
      retain = true; // An invocation error is not evidence that no child started.
      await runCutPreviewProcess({ command: pythonInterpreter(), args, cwd: temporary,
        env: { ...process.env }, timeoutMs: caller.timeoutMs, signal: caller.signal, trackForShutdown: true });
      retain = false;
    } else await execFileAsync(pythonInterpreter(), args, { env: { ...process.env }, maxBuffer: 1024 * 1024 });
    currentCallerProcessDeadline();
    const value = JSON.parse(readFileSync(outputPath, "utf8")) as unknown;
    return parseCompatibilityProjection(value, approvedCutPlanHash);
  } catch (error) {
    if (error instanceof CutPreviewProcessError) {
      retain = !error.details.groupStopped || error.details.forcedStop;
      Object.assign(error, { retainedProjectionDirectory: retain ? temporary : null });
      throw error;
    }
    if (retain && error instanceof Error) Object.assign(error, { retainedProjectionDirectory: temporary });
    if (retain) throw error;
    if (error instanceof AutoEditError) throw error;
    const detail = error instanceof Error ? error.message : String(error);
    throw new AutoEditError(`compatibility timeline projection failed: ${detail}`);
  } finally {
    if (!retain) rmSync(temporary, { recursive: true, force: true });
  }
}
