/** Metadata-only validation for one sandbox media-admission receipt. */
import { createHash } from "node:crypto";
import path from "node:path";
import { SCRIPTS_DIR } from "../../_lib/spawn-python";
import { readBoundedAuthoringFile } from "./initial-authoring-capture";

const SHA256 = /^[a-f0-9]{64}$/;
const NATIVE = "sniper-external-media-probe-v4-native";
const CONTAINER = "sniper-external-media-probe-v3";
const MAC_POLICY = "sniper-native-media-jail-v2";
const WINDOWS_POLICY = "sniper-windows-appcontainer-v1";
const INSPECT = "/dev/null";
const MEMORY_MIB = 768;
const APPROVAL = path.join(
  SCRIPTS_DIR, "producer", "headless", "native_media_runtime_approval.json");
const MEDIA_KINDS = new Set(["timed-media", "still-image", "font", "svg"]);
const FACT_KEYS = ["mediaKind", "durationSeconds", "sizeBytes", "width", "height",
  "videoStreams", "audioStreams", "streamCount", "declaredFrames"];
const INTEGER_FACTS = ["sizeBytes", "videoStreams", "audioStreams",
  "streamCount", "declaredFrames"];
const LIMIT_DEFAULTS = { max_bytes: 16 * 1024 ** 3, max_width: 8192,
  max_height: 8192, max_frames: 2_000_000,
  max_duration_seconds: 6 * 60 * 60, max_streams: 32,
  max_decode_seconds: 20 * 60 };

export interface AdmissionIdentity {
  snapshotPath: string;
  sha256: string;
  sizeBytes: number;
  mediaKind: string;
}

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown> : null;
}

function object(value: unknown, label: string): Record<string, unknown> {
  const row = record(value);
  if (!row) throw new Error(`${label} must be an object`);
  return row;
}

function exact(row: Record<string, unknown>, keys: string[], label: string): void {
  if (Object.keys(row).sort().join("\0") !== [...keys].sort().join("\0")) {
    throw new Error(`${label} has invalid keys`);
  }
}

function sha(value: unknown): boolean {
  return typeof value === "string" && SHA256.test(value);
}

function receipt(file: string, sha256: string): Record<string, unknown> {
  const bytes = readBoundedAuthoringFile(file, "media admission receipt", 4 * 1024 * 1024);
  if (createHash("sha256").update(bytes).digest("hex") !== sha256) {
    throw new Error("media admission receipt hash differs from its source-set pin");
  }
  try { return object(JSON.parse(bytes.toString("utf8")), "media admission receipt"); }
  catch (error) {
    throw new Error(`media admission receipt must be UTF-8 JSON: ${(error as Error).message}`);
  }
}

function limits(value: unknown): Record<string, number> {
  const supplied = object(value, "media admission limits");
  const allowed = Object.keys(LIMIT_DEFAULTS);
  if (Object.keys(supplied).some(key => !allowed.includes(key))) {
    throw new Error("media admission limits have invalid keys");
  }
  const row = { ...LIMIT_DEFAULTS, ...supplied } as Record<string, unknown>;
  if (!Object.values(row).every(value => typeof value === "number" && Number.isFinite(value))
      || !Number.isSafeInteger(row.max_decode_seconds)
      || Number(row.max_decode_seconds) < 90 || Number(row.max_decode_seconds) > 3600) {
    throw new Error("media admission limits are invalid");
  }
  return row as Record<string, number>;
}

function kindConsistent(facts: Record<string, unknown>): boolean {
  const kind = facts.mediaKind, video = Number(facts.videoStreams);
  const audio = Number(facts.audioStreams), streams = Number(facts.streamCount);
  const width = Number(facts.width), height = Number(facts.height);
  const frames = Number(facts.declaredFrames);
  if (video < 0 || audio < 0 || video + audio > streams) return false;
  if (kind === "timed-media") {
    const videoValid = video > 0 && width > 0 && height > 0 && frames > 0;
    const audioOnly = video === 0 && width === 0 && height === 0 && frames === 0;
    return video + audio > 0 && (videoValid || audioOnly);
  }
  if (kind === "still-image") {
    return video > 0 && audio === 0 && width > 0 && height > 0 && frames > 0;
  }
  if (kind === "svg") {
    return video === 1 && audio === 0 && streams === 1 && frames === 1
      && width > 0 && height > 0;
  }
  return video === 0 && audio === 0 && streams === 1 && frames === 0
    && width === 0 && height === 0;
}

function decoded(value: unknown, admitted: AdmissionIdentity,
  bounds: Record<string, number>): Record<string, unknown> {
  const row = object(value, "media admission decode evidence");
  exact(row, ["schemaVersion", "ok", "decoded", "facts"],
    "media admission decode evidence");
  const facts = object(row.facts, "media admission decode facts");
  exact(facts, FACT_KEYS, "media admission decode facts");
  const numbers = FACT_KEYS.filter(key => key !== "mediaKind").map(key => facts[key]);
  const numeric = numbers.every(value => typeof value === "number" && Number.isFinite(value));
  const integers = INTEGER_FACTS.every(key => Number.isSafeInteger(facts[key]));
  const timed = facts.mediaKind === "timed-media";
  const bounded = (timed ? Number(facts.durationSeconds) > 0
    && Number(facts.durationSeconds) <= bounds.max_duration_seconds
    : facts.durationSeconds === 0)
    && Number(facts.sizeBytes) > 0 && Number(facts.sizeBytes) <= bounds.max_bytes
    && Number(facts.width) >= 0 && Number(facts.width) <= bounds.max_width
    && Number(facts.height) >= 0 && Number(facts.height) <= bounds.max_height
    && Number(facts.streamCount) >= 1 && Number(facts.streamCount) <= bounds.max_streams
    && Number(facts.declaredFrames) >= 0
    && Number(facts.declaredFrames) <= bounds.max_frames;
  if (row.schemaVersion !== 1 || row.ok !== true || row.decoded !== true
      || !numeric || !integers || !MEDIA_KINDS.has(String(facts.mediaKind))
      || !bounded || !kindConsistent(facts)
      || facts.mediaKind !== admitted.mediaKind || facts.sizeBytes !== admitted.sizeBytes) {
    throw new Error("media admission decode evidence differs from its source-set entry");
  }
  return facts;
}

function tool(value: unknown): boolean {
  const row = record(value);
  return row !== null && typeof row.path === "string" && row.path.length > 0
    && sha(row.sha256) && typeof row.version === "string";
}

function approvedMacRuntime(runtime: Record<string, unknown>): boolean {
  const approval = object(JSON.parse(readBoundedAuthoringFile(
    APPROVAL, "native media runtime approval", 64 * 1024).toString("utf8")),
  "native media runtime approval");
  const rows = Array.isArray(approval.approved) ? approval.approved : [];
  return approval.schemaVersion === 2 && approval.policy === MAC_POLICY && rows.length > 0
    && rows.some(value => record(value)?.profileTemplateSha256 === runtime.profileTemplateSha256
      && record(value)?.launcherSha256 === runtime.launcherSha256);
}

function runtimeValid(value: unknown): value is Record<string, unknown> {
  const runtime = record(value), tools = record(runtime?.tools);
  const toolsOk = tools !== null && Object.keys(tools).sort().join("\0") === "ffmpeg\0ffprobe"
    && tool(tools.ffprobe) && tool(tools.ffmpeg);
  if (!runtime || !toolsOk || !sha(runtime.profileSha256)) return false;
  if (runtime.kind === "windows-appcontainer" && runtime.policy === WINDOWS_POLICY) {
    const source = record(runtime.sourceSha256);
    const binaries = [record(runtime.launcher), record(runtime.inspector)];
    return typeof runtime.appContainerSid === "string" && source !== null
      && Object.keys(source).sort().join("\0") === "windows_media_inspect.cs\0windows_media_jail.cs"
      && Object.values(source).every(sha) && binaries.every(row => row !== null && sha(row.sha256));
  }
  return runtime.kind === "macos-seatbelt" && runtime.policy === MAC_POLICY
    && [runtime.closureCount, runtime.openedPathCount].every(
      value => Number.isSafeInteger(value) && Number(value) > 0)
    && ["profileTemplateSha256", "launcherSha256", "closureSha256"]
      .every(key => sha(runtime[key])) && approvedMacRuntime(runtime);
}

function runValid(value: unknown, decoder: string, runtime: Record<string, unknown>,
  snapshot: string): boolean {
  const run = record(value);
  if (!run || run.sandboxed !== true || run.mode !== (decoder === INSPECT ? "inspect" : "exec")
      || run.decoder !== decoder || run.input !== snapshot
      || run.profileSha256 !== runtime.profileSha256 || run.memoryMiB !== MEMORY_MIB) return false;
  if (runtime.kind === "windows-appcontainer") {
    return run.kind === "windows-appcontainer" && run.networkCapabilities === 0
      && run.ephemeralProfile === true && run.writeDeniedOutsideProfile === true
      && record(run.job)?.activeProcessLimit === 1;
  }
  const rlimits = record(run.rlimits);
  return ["RLIMIT_FSIZE", "RLIMIT_CORE"].every(key =>
    Array.isArray(rlimits?.[key]) && (rlimits?.[key] as unknown[]).length === 2
    && (rlimits?.[key] as unknown[]).every(item => item === 0));
}

function nativeEvidence(row: Record<string, unknown>, snapshot: string,
  mediaKind: string): void {
  const runtime = record(row.runtime), isolation = record(row.isolation);
  if (!runtimeValid(runtime) || !isolation) {
    throw new Error("native media admission runtime or isolation is invalid");
  }
  const windows = runtime.kind === "windows-appcontainer";
  const fixed = windows
    ? { kind: "windows-appcontainer", policy: WINDOWS_POLICY, network: "denied",
      processCreation: "job-limited", writes: "ephemeral profile only",
      otherProcesses: "denied", watchdog: "job-object", memoryMiB: MEMORY_MIB }
    : { kind: "macos-seatbelt", policy: MAC_POLICY, network: "denied",
      processCreation: "denied", writes: "/dev/null only", otherProcesses: "denied",
      watchdog: "footprint+cpu", memoryMiB: MEMORY_MIB };
  const tools = object(runtime.tools, "native media admission tools");
  const steps = mediaKind === "font" || mediaKind === "svg" ? [INSPECT]
    : [INSPECT, String(object(tools.ffprobe, "ffprobe").path),
      String(object(tools.ffmpeg, "ffmpeg").path)];
  const runs = Array.isArray(isolation.jailRuns) ? isolation.jailRuns : [];
  const valid = Object.entries(fixed).every(([key, value]) => isolation[key] === value)
    && isolation.profileSha256 === runtime.profileSha256 && runs.length === steps.length
    && runs.every((run, index) => runValid(run, steps[index], runtime, snapshot));
  if (!valid) throw new Error("native media admission runtime or isolation is invalid");
}

/** Apply the same metadata semantics as Python validate_admission_receipt. */
export function validateAdmissionReceiptDocument(row: Record<string, unknown>,
  admitted: AdmissionIdentity): void {
  const policy = row.policy;
  const keys = policy === NATIVE
    ? ["schemaVersion", "policy", "snapshot", "limits", "runtime", "isolation", "decoded"]
    : ["schemaVersion", "policy", "snapshot", "limits", "image", "isolation", "network", "decoded"];
  if (row.schemaVersion !== 1 || (policy !== NATIVE && policy !== CONTAINER)) {
    throw new Error("media admission receipt policy is unsupported");
  }
  exact(row, keys, "media admission receipt");
  const snapshot = object(row.snapshot, "media admission snapshot");
  if (snapshot.path !== admitted.snapshotPath || snapshot.sha256 !== admitted.sha256
      || snapshot.sizeBytes !== admitted.sizeBytes) {
    throw new Error("media admission receipt differs from its source-set entry");
  }
  const facts = decoded(row.decoded, admitted, limits(row.limits));
  if (policy === NATIVE) nativeEvidence(row, admitted.snapshotPath, String(facts.mediaKind));
}

/** Reopen/hash receipt metadata and bind its snapshot/decode facts without reading media. */
export function validateMediaAdmissionReceipt(file: string, sha256: string,
  admitted: AdmissionIdentity): void {
  validateAdmissionReceiptDocument(receipt(file, sha256), admitted);
}

/** Accept a controller-pinned origin for local review without claiming publication approval. */
export function validateExternalAuthorization(file: string, sha256: string,
  sourceSha256: string): void {
  const bytes = readBoundedAuthoringFile(
    file, "external-media authorization receipt", 4 * 1024 * 1024);
  if (createHash("sha256").update(bytes).digest("hex") !== sha256) {
    throw new Error("external-media authorization hash differs from its controller pin");
  }
  const row = object(JSON.parse(bytes.toString("utf8")),
    "external-media authorization receipt");
  exact(row, ["schemaVersion", "kind", "assetFile", "record", "acquisition"],
    "external-media authorization receipt");
  const origin = object(row.record, "external-media authorization record");
  const rights = object(origin.rights, "external-media authorization rights");
  const uses = Array.isArray(rights.allowedUses) ? rights.allowedUses : [];
  const platforms = Array.isArray(rights.allowedPlatforms) ? rights.allowedPlatforms : [];
  const disposition = origin.publicationDisposition;
  if (row.schemaVersion !== 1 || row.kind !== "native-short-asset-origin"
      || origin.sha256 !== sourceSha256
      || !["approved", "needs-review"].includes(String(disposition))
      || !uses.includes("editorial") || !platforms.includes("local-review")
      || !record(row.acquisition)) {
    throw new Error("external-media authorization is not eligible for local review");
  }
}
