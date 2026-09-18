import {
  existsSync,
  lstatSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  realpathSync,
  writeFileSync,
} from "node:fs";
import { createHash } from "node:crypto";
import path from "node:path";
import type { AutoEditAuthoritySnapshot } from "@/lib/server/auto-edit-authority-snapshot";
import { stableAuthorityHash } from "@/lib/server/auto-edit-authority-snapshot";
import { fileSha256 } from "@/lib/server/auto-edit-hash";
import type { GateBundleVerdict } from "./planning-gates";
import {
  packetCutSegments,
  packetSpeechEvidence,
  type PacketBoundaryEvidence,
  type PacketCutSegment,
  type PacketKeptWord,
  type PacketTranscriptEvidence,
} from "./plan-review-packet-source";
import type { AutoEditCtx } from "./stream";
import { AutoEditError } from "./stream";

export const PLAN_REVIEW_PACKET_SCHEMA_VERSION = 1 as const;
export const PLAN_REVIEW_PACKET_NAME = "plan-review-packet.json";

interface BoundJsonContent {
  byteHash: string;
  content: unknown;
}

interface BoundReferenceFile {
  role: string;
  byteHash: string;
}

interface BoundReferenceStudy {
  id: string;
  title: string;
  mode: string;
  files: BoundReferenceFile[];
}

interface PlanReviewPacketCore {
  schemaVersion: typeof PLAN_REVIEW_PACKET_SCHEMA_VERSION;
  kind: "producer-plan-review-packet";
  stage: "plan";
  round: number;
  inputAuthority: AutoEditAuthoritySnapshot;
  request: {
    scope: AutoEditCtx["scope"];
    operatorIntent: AutoEditCtx["intent"] | null;
  };
  doctrineHash: string | null;
  reference: BoundReferenceStudy | null;
  plan: BoundJsonContent;
  manifest: BoundJsonContent;
  gateDigest: string;
  gateVerdict: GateBundleVerdict;
  timeline: { outputDuration: number; segments: PacketCutSegment[] };
  transcriptEvidence: {
    transcripts: PacketTranscriptEvidence[];
    missingTranscriptSourceIds: string[];
    keptWords: PacketKeptWord[];
    boundaryNeighbors: PacketBoundaryEvidence[];
  };
}

export interface PlanReviewPacket extends PlanReviewPacketCore {
  contentDigest: string;
}

export interface PlanReviewPacketRef {
  path: string;
  hash: string;
  contentDigest: string;
  authorityDigest: string;
  gateDigest: string;
  round: number;
}

function regularFile(filePath: string, label: string): void {
  if (!existsSync(filePath)) throw new AutoEditError(`${label} is missing: ${filePath}`);
  const stat = lstatSync(filePath);
  if (stat.isSymbolicLink() || !stat.isFile()) {
    throw new AutoEditError(`${label} must be a regular non-symlink file: ${filePath}`);
  }
}

function bytesHash(bytes: Buffer): string {
  return createHash("sha256").update(bytes).digest("hex");
}

function boundJson(filePath: string, label: string): BoundJsonContent {
  regularFile(filePath, label);
  const bytes = readFileSync(filePath);
  const byteHash = bytesHash(bytes);
  let content: unknown;
  try {
    content = JSON.parse(bytes.toString("utf8")) as unknown;
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    throw new AutoEditError(`${label} is not valid JSON: ${detail}`);
  }
  return { byteHash, content };
}

function referenceFile(role: string, filePath: string): BoundReferenceFile {
  regularFile(filePath, `reference ${role}`);
  return { role, byteHash: bytesHash(readFileSync(filePath)) };
}

function boundReference(ctx: AutoEditCtx): BoundReferenceStudy | null {
  const study = ctx.referenceStudy;
  if (!study) return null;
  const files = [
    referenceFile("profile", study.profilePath),
    referenceFile("deep-study", study.deepStudyPath),
    ...study.representativeFrames.map((filePath, index) =>
      referenceFile(`representative-frame-${index + 1}`, filePath)),
  ];
  return { id: study.id, title: study.title, mode: study.mode, files };
}

function outputDuration(segments: PacketCutSegment[]): number {
  return segments.length ? segments[segments.length - 1].outputEnd : 0;
}

function verifyAuthority(
  authority: AutoEditAuthoritySnapshot,
  plan: BoundJsonContent,
  manifest: BoundJsonContent,
): void {
  if (authority.planHash !== plan.byteHash) {
    throw new AutoEditError("plan bytes do not match the planning authority snapshot");
  }
  if (authority.manifestHash !== manifest.byteHash) {
    throw new AutoEditError("manifest bytes do not match the planning authority snapshot");
  }
}

export function buildPlanReviewPacket(
  ctx: AutoEditCtx,
  round: number,
  gateVerdict: GateBundleVerdict,
  authority: AutoEditAuthoritySnapshot,
): PlanReviewPacket {
  if (!Number.isInteger(round) || round < 1) {
    throw new AutoEditError("plan review packet round must be a positive integer");
  }
  const plan = boundJson(ctx.planPath, "edit plan");
  const manifest = boundJson(ctx.manifestPath, "asset manifest");
  verifyAuthority(authority, plan, manifest);
  const segments = packetCutSegments(plan.content);
  const speech = packetSpeechEvidence(ctx, manifest.content, segments);
  const core: PlanReviewPacketCore = {
    schemaVersion: PLAN_REVIEW_PACKET_SCHEMA_VERSION,
    kind: "producer-plan-review-packet",
    stage: "plan",
    round,
    inputAuthority: authority,
    request: { scope: ctx.scope, operatorIntent: ctx.intent ?? null },
    doctrineHash: ctx.doctrine?.doctrineHash ?? null,
    reference: boundReference(ctx),
    plan,
    manifest,
    gateDigest: stableAuthorityHash(gateVerdict),
    gateVerdict,
    timeline: { outputDuration: outputDuration(segments), segments },
    transcriptEvidence: speech,
  };
  return { ...core, contentDigest: stableAuthorityHash(core) };
}

function packetRelativePath(ctx: AutoEditCtx, filePath: string, round: number): string[] {
  const relative = path.relative(path.resolve(ctx.dir), path.resolve(filePath));
  if (!relative || relative.startsWith("..") || path.isAbsolute(relative)) {
    throw new AutoEditError("plan review packet must stay inside the producer directory");
  }
  const parts = relative.split(path.sep);
  const valid = parts.length === 6 && parts[0] === ".sniper-qc" && !!parts[1]
    && parts[2] === "planning" && parts[3] === `round-${round}`
    && /^critic-input-[a-zA-Z0-9-]+$/.test(parts[4])
    && parts[5] === PLAN_REVIEW_PACKET_NAME;
  if (!valid) throw new AutoEditError("plan review packet has a non-canonical artifact path");
  return parts;
}

export function assertPlanReviewPacketDestination(
  ctx: AutoEditCtx,
  filePath: string,
  round: number,
): void {
  const parts = packetRelativePath(ctx, filePath, round);
  let cursor = path.resolve(ctx.dir);
  for (const part of parts.slice(0, -1)) {
    cursor = path.join(cursor, part);
    if (existsSync(cursor) && lstatSync(cursor).isSymbolicLink()) {
      throw new AutoEditError(`plan review packet path contains a symlink: ${cursor}`);
    }
  }
}

export function bindPlanReviewPacket(
  filePath: string,
  packet: PlanReviewPacket,
): PlanReviewPacketRef {
  const hash = fileSha256(filePath);
  if (!hash) throw new AutoEditError("persisted plan review packet is unreadable");
  return {
    path: filePath,
    hash,
    contentDigest: packet.contentDigest,
    authorityDigest: packet.inputAuthority.digest,
    gateDigest: packet.gateDigest,
    round: packet.round,
  };
}

export function writePlanReviewPacketExclusive(
  filePath: string,
  packet: PlanReviewPacket,
): string {
  mkdirSync(path.dirname(filePath), { recursive: true, mode: 0o700 });
  writeFileSync(filePath, `${JSON.stringify(packet, null, 2)}\n`, {
    flag: "wx", mode: 0o600,
  });
  return filePath;
}

function parsePacket(filePath: string): PlanReviewPacket {
  try {
    return JSON.parse(readFileSync(filePath, "utf8")) as PlanReviewPacket;
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    throw new AutoEditError(`plan review packet is invalid JSON: ${detail}`);
  }
}

function packetCore(packet: PlanReviewPacket): PlanReviewPacketCore {
  const { contentDigest: _digest, ...core } = packet;
  void _digest;
  return core;
}

function verifyPacketShape(packet: PlanReviewPacket, ref: PlanReviewPacketRef): void {
  const valid = packet.schemaVersion === PLAN_REVIEW_PACKET_SCHEMA_VERSION
    && packet.kind === "producer-plan-review-packet" && packet.stage === "plan"
    && packet.round === ref.round && packet.contentDigest === ref.contentDigest
    && packet.inputAuthority?.digest === ref.authorityDigest
    && packet.gateDigest === ref.gateDigest;
  if (!valid || stableAuthorityHash(packetCore(packet)) !== packet.contentDigest
      || stableAuthorityHash(packet.gateVerdict) !== packet.gateDigest) {
    throw new AutoEditError("plan review packet content binding is invalid");
  }
}

export function validatePlanReviewPacketRef(
  ctx: AutoEditCtx,
  round: number,
  ref: PlanReviewPacketRef,
): PlanReviewPacket {
  if (ref.round !== round) throw new AutoEditError("plan review packet round does not match request");
  packetRelativePath(ctx, ref.path, round);
  regularFile(ref.path, "plan review packet");
  const siblings = readdirSync(path.dirname(ref.path)).sort();
  if (siblings.length !== 1 || siblings[0] !== PLAN_REVIEW_PACKET_NAME) {
    throw new AutoEditError("plan review critic-input directory contains unapproved evidence");
  }
  const root = realpathSync(ctx.dir);
  const relative = path.relative(root, realpathSync(ref.path));
  if (!relative || relative.startsWith("..") || path.isAbsolute(relative)) {
    throw new AutoEditError("plan review packet resolves outside the producer directory");
  }
  if (fileSha256(ref.path) !== ref.hash) {
    throw new AutoEditError("plan review packet file hash changed before critic launch");
  }
  const packet = parsePacket(ref.path);
  verifyPacketShape(packet, ref);
  if (packet.plan?.byteHash !== fileSha256(ctx.planPath)
      || packet.manifest?.byteHash !== fileSha256(ctx.manifestPath)
      || packet.doctrineHash !== (ctx.doctrine?.doctrineHash ?? null)
      || stableAuthorityHash(packet.reference) !== stableAuthorityHash(boundReference(ctx))) {
    throw new AutoEditError("plan review packet no longer matches current review inputs");
  }
  return packet;
}
