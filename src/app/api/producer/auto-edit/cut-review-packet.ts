import { createHash } from "node:crypto";
import {
  existsSync, lstatSync, readFileSync, realpathSync,
} from "node:fs";
import path from "node:path";
import {
  autoEditAuthoritySnapshot,
  sameAutoEditAuthority,
  stableAuthorityHash,
  type AutoEditAuthoritySnapshot,
} from "@/lib/server/auto-edit-authority-snapshot";
import { fileSha256 } from "@/lib/server/auto-edit-hash";
import {
  packetCutSegments,
  packetSpeechEvidence,
  type PacketCutSegment,
  type PacketSpeechEvidence,
} from "./plan-review-packet-source";
import type { CutApprovalReceipt } from "./cut-approval";
import { AutoEditError, type AutoEditCtx } from "./stream";

export const CUT_REVIEW_PACKET_NAME = "cut-review-packet.json";

interface BoundJson {
  byteHash: string;
  content: unknown;
}

interface ExactKeptSpeech {
  fullText: string;
  segments: Array<{
    segmentIndex: number;
    text: string;
    outputStart: number;
    outputEnd: number;
  }>;
}

interface CutReviewPacketCore {
  schemaVersion: 1;
  kind: "producer-cut-review-packet";
  stage: "cut";
  round: number;
  inputAuthority: AutoEditAuthoritySnapshot;
  request: { scope: AutoEditCtx["scope"]; operatorIntent: AutoEditCtx["intent"] | null };
  doctrineHash: string | null;
  plan: BoundJson;
  manifest: BoundJson;
  deterministicReceipt: CutApprovalReceipt;
  timeline: { outputDuration: number; segments: PacketCutSegment[] };
  keptSpeech: ExactKeptSpeech;
  transcriptEvidence: PacketSpeechEvidence;
}

export interface CutReviewPacket extends CutReviewPacketCore {
  contentDigest: string;
}

export interface CutReviewPacketRef {
  path: string;
  hash: string;
  contentDigest: string;
  authorityDigest: string;
  round: number;
}

function regularFile(filePath: string, label: string): void {
  if (!existsSync(filePath)) throw new AutoEditError(`${label} is missing: ${filePath}`);
  const stat = lstatSync(filePath);
  if (stat.isSymbolicLink() || !stat.isFile()) {
    throw new AutoEditError(`${label} must be a regular non-symlink file`);
  }
}

function boundJson(filePath: string, label: string): BoundJson {
  regularFile(filePath, label);
  const bytes = readFileSync(filePath);
  try {
    return {
      byteHash: createHash("sha256").update(bytes).digest("hex"),
      content: JSON.parse(bytes.toString("utf8")) as unknown,
    };
  } catch (error) {
    throw new AutoEditError(`${label} is invalid JSON: ${(error as Error).message}`);
  }
}

function outputDuration(segments: PacketCutSegment[]): number {
  return segments.length ? segments[segments.length - 1].outputEnd : 0;
}

function exactKeptSpeech(
  speech: PacketSpeechEvidence,
  segments: PacketCutSegment[],
): ExactKeptSpeech {
  const rows = segments.map((segment) => ({
    segmentIndex: segment.index,
    text: speech.keptWords.filter((word) => word.segmentIndex === segment.index)
      .map((word) => word.word).join(" "),
    outputStart: segment.outputStart,
    outputEnd: segment.outputEnd,
  }));
  return { fullText: rows.map((row) => row.text).filter(Boolean).join(" "), segments: rows };
}

function assertReceipt(
  receipt: CutApprovalReceipt,
  authority: AutoEditAuthoritySnapshot,
): void {
  if (receipt.planHash !== authority.planHash
      || receipt.manifestHash !== authority.manifestHash
      || receipt.transcriptDigest !== authority.transcriptDigest) {
    throw new AutoEditError("cut validation receipt does not match critic authority");
  }
}

export function buildCutReviewPacket(
  ctx: AutoEditCtx,
  round: number,
  receipt: CutApprovalReceipt,
  authority: AutoEditAuthoritySnapshot,
): CutReviewPacket {
  if (!Number.isInteger(round) || round < 1) {
    throw new AutoEditError("cut review packet round must be a positive integer");
  }
  const plan = boundJson(ctx.planPath, "edit plan");
  const manifest = boundJson(ctx.manifestPath, "asset manifest");
  if (plan.byteHash !== authority.planHash || manifest.byteHash !== authority.manifestHash) {
    throw new AutoEditError("cut review bytes do not match critic authority");
  }
  assertReceipt(receipt, authority);
  const segments = packetCutSegments(plan.content);
  const speech = packetSpeechEvidence(ctx, manifest.content, segments);
  const core: CutReviewPacketCore = {
    schemaVersion: 1,
    kind: "producer-cut-review-packet",
    stage: "cut",
    round,
    inputAuthority: authority,
    request: { scope: ctx.scope, operatorIntent: ctx.intent ?? null },
    doctrineHash: ctx.doctrine?.doctrineHash ?? null,
    plan,
    manifest,
    deterministicReceipt: receipt,
    timeline: { outputDuration: outputDuration(segments), segments },
    keptSpeech: exactKeptSpeech(speech, segments),
    transcriptEvidence: speech,
  };
  return { ...core, contentDigest: stableAuthorityHash(core) };
}

function packetCore(packet: CutReviewPacket): CutReviewPacketCore {
  const { contentDigest: _digest, ...core } = packet;
  void _digest;
  return core;
}

function canonicalPath(ctx: AutoEditCtx, filePath: string, round: number): void {
  const relative = path.relative(path.resolve(ctx.dir), path.resolve(filePath));
  const parts = relative.split(path.sep);
  const valid = !relative.startsWith("..") && !path.isAbsolute(relative)
    && parts.length === 6 && parts[0] === ".sniper-qc"
    && /^[a-zA-Z0-9._-]+$/.test(parts[1]) && parts[2] === "cut"
    && parts[3] === `round-${round}`
    && /^critic-input-[a-zA-Z0-9-]+$/.test(parts[4])
    && parts[5] === CUT_REVIEW_PACKET_NAME;
  if (!valid) throw new AutoEditError("cut review packet has a non-canonical path");
}

export function bindCutReviewPacket(
  filePath: string,
  packet: CutReviewPacket,
): CutReviewPacketRef {
  const hash = fileSha256(filePath);
  if (!hash) throw new AutoEditError("persisted cut review packet is unreadable");
  return {
    path: filePath, hash, contentDigest: packet.contentDigest,
    authorityDigest: packet.inputAuthority.digest, round: packet.round,
  };
}

function parsePacket(filePath: string): CutReviewPacket {
  try {
    return JSON.parse(readFileSync(filePath, "utf8")) as CutReviewPacket;
  } catch (error) {
    throw new AutoEditError(`cut review packet is invalid JSON: ${(error as Error).message}`);
  }
}

export function validateCutReviewPacketRef(
  ctx: AutoEditCtx,
  round: number,
  ref: CutReviewPacketRef,
): CutReviewPacket {
  if (ref.round !== round) throw new AutoEditError("cut review packet round mismatch");
  canonicalPath(ctx, ref.path, round);
  regularFile(ref.path, "cut review packet");
  const root = realpathSync(ctx.dir);
  const relative = path.relative(root, realpathSync(ref.path));
  if (!relative || relative.startsWith("..") || path.isAbsolute(relative)) {
    throw new AutoEditError("cut review packet resolves outside producer directory");
  }
  if (fileSha256(ref.path) !== ref.hash) {
    throw new AutoEditError("cut review packet changed before critic launch");
  }
  const packet = parsePacket(ref.path);
  const valid = packet.schemaVersion === 1 && packet.kind === "producer-cut-review-packet"
    && packet.stage === "cut" && packet.round === round
    && packet.contentDigest === ref.contentDigest
    && packet.inputAuthority?.digest === ref.authorityDigest
    && stableAuthorityHash(packetCore(packet)) === packet.contentDigest;
  if (!valid) throw new AutoEditError("cut review packet content binding is invalid");
  if (!sameAutoEditAuthority(packet.inputAuthority, autoEditAuthoritySnapshot(ctx))) {
    throw new AutoEditError("cut review packet no longer matches current inputs");
  }
  return packet;
}
