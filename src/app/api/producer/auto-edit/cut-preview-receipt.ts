import { createHash } from "node:crypto";
import { closeSync, constants, fstatSync, lstatSync, openSync, readSync, realpathSync } from "node:fs";
import path from "node:path";
import { canonicalJsonSha256 } from "@/lib/server/auto-edit-hash";
import type { CutApprovalRequestV1 } from "@/lib/producer/contracts/cut-approval-request";

const HASH = /^[a-f0-9]{64}$/;
const RECEIPT_KEYS = ["schemaVersion", "kind", "requestHash", "planHash", "authorityDigest",
  "pictureLockHash", "projectionReceiptHash", "timelineMapHash", "sourceSetDigest",
  "sourceSetReceiptHash", "manifestHash", "runId", "attempt", "executionKey", "createdAt",
  "toolchainHash", "profile", "media", "manifestationHash", "manifestationFileHash",
  "timelineFileHash", "audioClockHash", "scope", "receiptHash"];

export interface CutPreviewReceiptV1 {
  schemaVersion: 1; kind: "guided-cut-preview";
  requestHash: string; planHash: string; authorityDigest: string;
  pictureLockHash: string; projectionReceiptHash: string; timelineMapHash: string;
  sourceSetDigest: string; sourceSetReceiptHash: string; manifestHash: string;
  runId: string; attempt: number; executionKey: string; createdAt: string;
  toolchainHash: string; manifestationHash: string; manifestationFileHash: string;
  timelineFileHash: string; audioClockHash: string; receiptHash: string;
  scope: "cut-only-source-aspect-ungraded-unmixed-not-delivery";
  profile: { width: number; height: number; fps: string; pixFmt: "yuv420p"; proxyScale: number };
  media: { name: "cut-preview.mp4"; sha256: string; sizeBytes: number;
    videoCodec: "h264"; pixFmt: "yuv420p"; videoFrames: number; fullDecode: "passed";
    audio: { codec: "aac"; sampleRate: 48000; channels: 2; channelLayout: "stereo";
      timeBase: string; startPts: 0; durationTs: number; decodedAudioSamples: number;
      presentedAudioSamples: number; trailingPaddingSamples: number;
      presentationVsVideoSamples: number; trimPolicy: "ffmpeg-mp4-edit-list" } };
}

/** Proof observations only. Nested receipt media/decode fields are recorded historical claims. */
export interface CutPreviewEvidence {
  observationScope: "receipt-proofs-and-toolchain-only";
  mediaBytesObserved: false;
  receipt: CutPreviewReceiptV1;
}

function object(value: unknown, keys: string[]): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)
      || JSON.stringify(Object.keys(value).sort()) !== JSON.stringify([...keys].sort())) {
    throw new Error("cut preview receipt has unknown or missing fields");
  }
  return value as Record<string, unknown>;
}

function positive(value: unknown, maximum: number): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value > 0 && value <= maximum;
}

function rate(value: unknown): number {
  if (typeof value !== "string" || !/^\d+\/\d+$/.test(value)) throw new Error("cut preview rational clock is malformed");
  const [num, den] = value.split("/").map(Number);
  if (!positive(num, 1e9) || !positive(den, 1e9)) throw new Error("cut preview rational clock is invalid");
  return num / den;
}

function validateMedia(value: unknown, profile: CutPreviewReceiptV1["profile"]): void {
  const media = object(value, ["name", "sha256", "sizeBytes", "videoCodec", "pixFmt", "videoFrames", "audio", "fullDecode"]);
  const audio = object(media.audio, ["codec", "sampleRate", "channels", "channelLayout", "timeBase",
    "startPts", "durationTs", "decodedAudioSamples", "presentedAudioSamples", "trailingPaddingSamples",
    "presentationVsVideoSamples", "trimPolicy"]);
  if (media.name !== "cut-preview.mp4" || !HASH.test(String(media.sha256))
      || !positive(media.sizeBytes, 2 * 1024 ** 3) || !positive(media.videoFrames, 72_000)
      || media.videoCodec !== "h264" || media.pixFmt !== "yuv420p" || media.fullDecode !== "passed"
      || audio.codec !== "aac" || audio.sampleRate !== 48000 || audio.channels !== 2
      || audio.channelLayout !== "stereo" || audio.startPts !== 0 || audio.trimPolicy !== "ffmpeg-mp4-edit-list") {
    throw new Error("cut preview media is not qualified browser A/V");
  }
  for (const key of ["durationTs", "decodedAudioSamples", "presentedAudioSamples"])
    if (!positive(audio[key], 60_000_000)) throw new Error("cut preview sample evidence is invalid");
  const presented = audio.presentedAudioSamples as number;
  const decoded = audio.decodedAudioSamples as number;
  const videoSamples = Math.round((media.videoFrames as number) / rate(profile.fps) * 48000);
  if (Math.abs((audio.durationTs as number) * rate(audio.timeBase) * 48000 - presented) > 1e-6
      || decoded - presented !== audio.trailingPaddingSamples || decoded < presented || decoded - presented > 2048
      || presented - videoSamples !== audio.presentationVsVideoSamples || Math.abs(presented - videoSamples) > 1024) {
    throw new Error("cut preview sample clocks or AAC padding disagree");
  }
}

export function parseCutPreviewReceipt(value: unknown): CutPreviewReceiptV1 {
  const row = object(value, RECEIPT_KEYS);
  for (const key of RECEIPT_KEYS.filter((key) => key.endsWith("Hash") || key.endsWith("Digest") || key === "executionKey"))
    if (typeof row[key] !== "string" || !HASH.test(row[key] as string)) throw new Error("cut preview hash is invalid");
  if (row.schemaVersion !== 1 || row.kind !== "guided-cut-preview"
      || row.scope !== "cut-only-source-aspect-ungraded-unmixed-not-delivery"
      || typeof row.runId !== "string" || !row.runId || row.runId.length > 200
      || !positive(row.attempt, 10_000) || typeof row.createdAt !== "string"
      || !Number.isFinite(Date.parse(row.createdAt)) || new Date(row.createdAt).toISOString() !== row.createdAt) {
    throw new Error("cut preview receipt identity is malformed");
  }
  const profile = object(row.profile, ["width", "height", "fps", "pixFmt", "proxyScale"]);
  if (!positive(profile.width, 1280) || !positive(profile.height, 1280)
      || (profile.width as number) % 2 || (profile.height as number) % 2 || profile.pixFmt !== "yuv420p"
      || rate(profile.fps) > 60 || rate(profile.fps) < 1 || typeof profile.proxyScale !== "number"
      || !Number.isFinite(profile.proxyScale) || profile.proxyScale <= 0 || profile.proxyScale > 1) {
    throw new Error("cut preview profile is unqualified");
  }
  validateMedia(row.media, profile as unknown as CutPreviewReceiptV1["profile"]);
  const { receiptHash, ...core } = row;
  if (canonicalJsonSha256(core) !== receiptHash) throw new Error("cut preview receipt hash changed");
  return row as unknown as CutPreviewReceiptV1;
}

export function assertCutPreviewDirectory(directory: string): void {
  if (path.resolve(directory) !== directory || realpathSync(directory) !== directory
      || !lstatSync(directory).isDirectory() || lstatSync(directory).isSymbolicLink()) {
    throw new Error("cut preview artifact directory is not canonical and real");
  }
}

/** Hash media incrementally; JSON callers retain only their explicitly bounded bytes. */
export function observeCutPreviewFile(file: string, maximum: number, retain = false, guard?: () => void) {
  guard?.();
  assertCutPreviewDirectory(path.dirname(file));
  const descriptor = openSync(file, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
  try {
    const before = fstatSync(descriptor, { bigint: true });
    if (!before.isFile() || before.nlink !== BigInt(1) || before.size < BigInt(1) || before.size > BigInt(maximum)) {
      throw new Error("cut preview artifact is not a bounded regular file");
    }
    const hash = createHash("sha256"), chunks: Buffer[] = [];
    const buffer = Buffer.alloc(Math.min(maximum, 1024 * 1024));
    let remaining = Number(before.size);
    while (remaining > 0) {
      guard?.();
      const count = readSync(descriptor, buffer, 0, Math.min(remaining, buffer.length), null);
      if (!count) throw new Error("cut preview artifact truncated during observation");
      const chunk = buffer.subarray(0, count);
      hash.update(chunk); if (retain) chunks.push(Buffer.from(chunk));
      remaining -= count;
    }
    const after = fstatSync(descriptor, { bigint: true }), current = lstatSync(file, { bigint: true });
    for (const field of ["dev", "ino", "size", "mtimeNs", "ctimeNs", "nlink"] as const)
      if (before[field] !== after[field] || before[field] !== current[field]) throw new Error("cut preview artifact identity changed");
    if (current.isSymbolicLink()) throw new Error("cut preview artifact was linked");
    guard?.();
    return { sha256: hash.digest("hex"), sizeBytes: Number(before.size), bytes: Buffer.concat(chunks) };
  } finally { closeSync(descriptor); }
}

export function readCutPreviewObject(file: string) {
  const observed = observeCutPreviewFile(file, 16 * 1024 * 1024, true);
  return { ...observed, value: JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(observed.bytes)) as Record<string, unknown> };
}

function verifyToolchain(runtime: Record<string, unknown>, expectedHash: string, mediaPath: string): void {
  const { toolchainHash, ...toolchain } = object(runtime, ["kind", "pipelineDigest", "binaries", "files", "toolchainHash"]);
  const binaries = object(runtime.binaries, ["python", "ffmpeg", "ffprobe"]);
  if (runtime.kind !== "cut-preview-toolchain-v1" || canonicalJsonSha256(toolchain) !== expectedHash
      || toolchainHash !== expectedHash || !Array.isArray(runtime.files)
      || !runtime.files.length || runtime.files.length > 1000
      || (runtime.pipelineDigest !== null && (typeof runtime.pipelineDigest !== "string" || !HASH.test(runtime.pipelineDigest)))) {
    throw new Error("cut preview toolchain receipt changed");
  }
  const seen = new Set<string>();
  let bytes = 0;
  for (const value of runtime.files) {
    const file = object(value, ["path", "sha256"]);
    if (typeof file.path !== "string" || !path.isAbsolute(file.path) || seen.has(file.path)
        || path.resolve(file.path) === mediaPath
        || typeof file.sha256 !== "string" || !HASH.test(file.sha256)) throw new Error("cut preview toolchain row is invalid or repeated");
    seen.add(file.path);
    const observed = observeCutPreviewFile(file.path, 1024 ** 3 - bytes);
    bytes += observed.sizeBytes;
    if (observed.sha256 !== file.sha256) throw new Error("cut preview executed toolchain changed");
  }
  if (!Object.values(binaries).every((file) => typeof file === "string" && seen.has(file))
      || ![...seen].some((file) => file.endsWith("/scripts/producer/cut_preview.py"))) {
    throw new Error("cut preview toolchain omits an executed entrypoint");
  }
}

/**
 * Validate bounded receipt/proof bytes and current toolchain, never the preview media.
 * This does not establish media existence, integrity, decode or safe playback. A media
 * route must still hash the actual opened descriptor before using it; other callers
 * should retain readCurrentCutPreview. Neither reader requalifies source-media bytes.
 */
export function readCutPreviewEvidence(outputDir: string, request: CutApprovalRequestV1): CutPreviewEvidence {
  const receipt = parseCutPreviewReceipt(readCutPreviewObject(path.join(outputDir, "receipt.json")).value);
  for (const key of ["requestHash", "planHash", "authorityDigest", "pictureLockHash", "projectionReceiptHash", "timelineMapHash"] as const)
    if (receipt[key] !== request[key]) throw new Error("cut preview targets another reviewed cut");
  if (path.basename(outputDir) !== receipt.executionKey || path.basename(path.dirname(outputDir)) !== request.requestHash)
    throw new Error("cut preview attempt directory disagrees with its receipt");
  const manifestation = readCutPreviewObject(path.join(outputDir, "cut_manifestation.v1.json"));
  const { receiptHash: manifestationHash, ...core } = manifestation.value;
  if (manifestation.sha256 !== receipt.manifestationFileHash || manifestationHash !== receipt.manifestationHash
      || canonicalJsonSha256(core) !== manifestationHash || core.kind !== "cut-manifestation-v1"
      || (core.concat as Record<string, unknown>)?.sha256 !== receipt.media.sha256
      || (core.concat as Record<string, unknown>)?.videoFrames !== receipt.media.videoFrames)
    throw new Error("cut preview exact manifestation proof changed");
  if (observeCutPreviewFile(path.join(outputDir, "timeline_map.json"), 16 * 1024 * 1024).sha256 !== receipt.timelineFileHash
      || core.timelineMapSha256 !== receipt.timelineFileHash) throw new Error("cut preview timeline bytes changed");
  const audioClock = readCutPreviewObject(path.join(outputDir, "audio-clock.json"));
  if (audioClock.sha256 !== receipt.audioClockHash || audioClock.value.kind !== "cut-preview-source-audio-clock"
      || audioClock.value.totalSamples !== receipt.media.audio.presentedAudioSamples)
    throw new Error("cut preview source-derived audio clock changed");
  const picture = object(audioClock.value.pictureClock, ["schemaVersion", "kind", "originalStartPts", "normalizedStartPts",
    "timeBase", "frameRate", "packetCount", "relativePacketsHash", "beforeFileHash", "afterFileHash"]);
  if (picture.schemaVersion !== 1 || picture.kind !== "cut-preview-picture-origin"
      || picture.normalizedStartPts !== 0 || !Number.isSafeInteger(picture.originalStartPts)
      || Math.abs((picture.originalStartPts as number) * rate(picture.timeBase)) > 1 / rate(receipt.profile.fps)
      || rate(picture.frameRate) !== rate(receipt.profile.fps) || picture.packetCount !== receipt.media.videoFrames
      || picture.afterFileHash !== receipt.media.sha256 || !HASH.test(String(picture.relativePacketsHash))
      || !HASH.test(String(picture.beforeFileHash))) throw new Error("cut preview picture-clock proof changed");
  const runtime = readCutPreviewObject(path.join(outputDir, "toolchain.json")).value;
  verifyToolchain(runtime, receipt.toolchainHash, path.join(outputDir, "cut-preview.mp4"));
  return { observationScope: "receipt-proofs-and-toolchain-only", mediaBytesObserved: false, receipt };
}

/** Strong current media hash/size observation; never delivery, source or operator acceptance. */
export function readCurrentCutPreview(outputDir: string, request: CutApprovalRequestV1): CutPreviewReceiptV1 {
  const { receipt } = readCutPreviewEvidence(outputDir, request);
  const media = observeCutPreviewFile(path.join(outputDir, "cut-preview.mp4"), 2 * 1024 ** 3);
  if (media.sha256 !== receipt.media.sha256 || media.sizeBytes !== receipt.media.sizeBytes) {
    throw new Error("cut preview media bytes changed");
  }
  return receipt;
}
