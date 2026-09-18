import { existsSync, lstatSync, readFileSync, realpathSync } from "node:fs";
import path from "node:path";
import { fileSha256 } from "./auto-edit-hash";
import { stableAuthorityHash } from "./auto-edit-authority-snapshot";
import { audioAuditFailure } from "@/lib/producer/audit-audio-policy";

export interface HashedArtifactRef {
  path: string;
  hash: string;
}

export interface PlanningReviewEvidence {
  round: number;
  authorityDigest: string;
  planHash: string;
  packet: HashedArtifactRef;
  gates: HashedArtifactRef;
  review: HashedArtifactRef;
}

export interface RenderedReviewEvidenceRef extends HashedArtifactRef {
  lens: "composition" | "editorial";
}

export interface AuditEvidenceAuthority {
  candidateHash: string;
  assembledProofHash: string;
  machine: HashedArtifactRef;
  report: HashedArtifactRef;
  frames: HashedArtifactRef[];
  digest: string;
}

export interface ApprovalRecord {
  schemaVersion: 2;
  qualityPolicyVersion: 1;
  authorityDigest: string;
  planHash: string;
  manifestHash: string;
  finalHash: string;
  candidateHash: string;
  assembledProofHash: string;
  qcRound: number;
  approvedAt: string;
  planningRoundsRequired: number;
  planningReviews: PlanningReviewEvidence[];
  renderedReviews: RenderedReviewEvidenceRef[];
  audit: AuditEvidenceAuthority;
  qualitySummary: HashedArtifactRef;
}

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown> : null;
}

function sha(value: unknown): value is string {
  return typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
}

function artifact(value: unknown): HashedArtifactRef | null {
  const row = record(value);
  return row && typeof row.path === "string" && path.isAbsolute(row.path) && sha(row.hash)
    ? { path: row.path, hash: row.hash } : null;
}

function planningEvidence(value: unknown): PlanningReviewEvidence | null {
  const row = record(value);
  const packet = artifact(row?.packet);
  const gates = artifact(row?.gates);
  const review = artifact(row?.review);
  if (!row || !Number.isInteger(row.round) || Number(row.round) < 1
      || !sha(row.authorityDigest) || !sha(row.planHash) || !packet || !gates || !review) return null;
  return {
    round: Number(row.round), authorityDigest: row.authorityDigest,
    planHash: row.planHash, packet, gates, review,
  };
}

function renderedEvidence(value: unknown): RenderedReviewEvidenceRef | null {
  const row = record(value);
  const ref = artifact(value);
  if (!row || !ref || (row.lens !== "composition" && row.lens !== "editorial")) return null;
  return { ...ref, lens: row.lens };
}

function auditEvidence(value: unknown): AuditEvidenceAuthority | null {
  const row = record(value);
  const machine = artifact(row?.machine);
  const report = artifact(row?.report);
  const frames = Array.isArray(row?.frames) ? row.frames.map(artifact) : [];
  if (!row || !sha(row.candidateHash) || !sha(row.assembledProofHash)
      || !machine || !report || !frames.length || frames.some((item) => !item)
      || !sha(row.digest)) return null;
  return {
    candidateHash: row.candidateHash,
    assembledProofHash: row.assembledProofHash,
    machine,
    report,
    frames: frames as HashedArtifactRef[],
    digest: row.digest,
  };
}

export function parseApprovalRecord(value: unknown): ApprovalRecord | null {
  const row = record(value);
  if (!row || row.schemaVersion !== 2 || row.qualityPolicyVersion !== 1
      || !sha(row.authorityDigest) || !sha(row.planHash) || !sha(row.manifestHash)
      || !sha(row.finalHash) || !sha(row.candidateHash) || !sha(row.assembledProofHash)
      || !Number.isInteger(row.qcRound) || Number(row.qcRound) < 1
      || typeof row.approvedAt !== "string" || !Number.isFinite(Date.parse(row.approvedAt))
      || !Number.isInteger(row.planningRoundsRequired) || Number(row.planningRoundsRequired) < 1
      || !Array.isArray(row.planningReviews) || !Array.isArray(row.renderedReviews)) return null;
  const planningReviews = row.planningReviews.map(planningEvidence);
  const renderedReviews = row.renderedReviews.map(renderedEvidence);
  const audit = auditEvidence(row.audit);
  const qualitySummary = artifact(row.qualitySummary);
  if (planningReviews.some((item) => !item) || renderedReviews.some((item) => !item)
      || !audit || !qualitySummary) return null;
  return {
    schemaVersion: 2,
    qualityPolicyVersion: 1,
    authorityDigest: row.authorityDigest,
    planHash: row.planHash,
    manifestHash: row.manifestHash,
    finalHash: row.finalHash,
    candidateHash: row.candidateHash,
    assembledProofHash: row.assembledProofHash,
    qcRound: Number(row.qcRound),
    approvedAt: row.approvedAt,
    planningRoundsRequired: Number(row.planningRoundsRequired),
    planningReviews: planningReviews as PlanningReviewEvidence[],
    renderedReviews: renderedReviews as RenderedReviewEvidenceRef[],
    audit,
    qualitySummary,
  };
}

function safeArtifactPath(producerDir: string, filePath: string): boolean {
  const root = path.resolve(producerDir);
  const relative = path.relative(root, path.resolve(filePath));
  if (!relative || relative.startsWith("..") || path.isAbsolute(relative)) return false;
  let cursor = root;
  for (const part of relative.split(path.sep)) {
    cursor = path.join(cursor, part);
    if (!existsSync(cursor) || lstatSync(cursor).isSymbolicLink()) return false;
  }
  const realRelative = path.relative(realpathSync(root), realpathSync(filePath));
  return !!realRelative && !realRelative.startsWith("..") && !path.isAbsolute(realRelative);
}

function verifiedArtifact(producerDir: string, item: HashedArtifactRef): boolean {
  if (!existsSync(item.path)) return false;
  try {
    return safeArtifactPath(producerDir, item.path) && lstatSync(item.path).isFile()
      && fileSha256(item.path) === item.hash;
  } catch {
    return false;
  }
}

function readJson(filePath: string): Record<string, unknown> | null {
  try { return record(JSON.parse(readFileSync(filePath, "utf8")) as unknown); } catch { return null; }
}

function auditDigest(audit: AuditEvidenceAuthority): string {
  const { digest: _digest, ...content } = audit;
  void _digest;
  return stableAuthorityHash(content);
}

function packetBinding(value: unknown): Record<string, unknown> | null {
  const row = record(value);
  return row && artifact(row) && sha(row.contentDigest) && sha(row.authorityDigest)
    && sha(row.gateDigest) && Number.isInteger(row.round) ? row : null;
}

function boundToPacket(
  value: unknown,
  item: PlanningReviewEvidence,
  packet: Record<string, unknown>,
): boolean {
  const binding = packetBinding(value);
  return !!binding && binding.path === item.packet.path && binding.hash === item.packet.hash
    && binding.round === item.round && binding.authorityDigest === item.authorityDigest
    && binding.contentDigest === packet.contentDigest && binding.gateDigest === packet.gateDigest;
}

function validPacketContent(packet: Record<string, unknown>, item: PlanningReviewEvidence): boolean {
  const { contentDigest, ...core } = packet;
  return packet.schemaVersion === 1 && packet.kind === "producer-plan-review-packet"
    && packet.stage === "plan" && packet.round === item.round && sha(contentDigest)
    && stableAuthorityHash(core) === contentDigest
    && recordValue(packet.inputAuthority, "digest") === item.authorityDigest
    && recordValue(packet.plan, "byteHash") === item.planHash;
}

function validTemplateUsageGate(gates: Record<string, unknown>): boolean {
  const bundle = record(gates.gates);
  const results = record(bundle?.gates);
  const templateUsage = record(results?.templateUsage);
  const metrics = record(templateUsage?.metrics);
  return record(results?.operatorIntent)?.ok === true
    && templateUsage?.ok === true && sha(metrics?.snapshotDigest);
}

function validPlanningEvidence(producerDir: string, item: PlanningReviewEvidence, record: ApprovalRecord): boolean {
  if (item.authorityDigest !== record.authorityDigest || item.planHash !== record.planHash
      || !verifiedArtifact(producerDir, item.packet) || !verifiedArtifact(producerDir, item.gates)
      || !verifiedArtifact(producerDir, item.review)) return false;
  const packet = readJson(item.packet.path);
  const gates = readJson(item.gates.path);
  const review = readJson(item.review.path);
  return !!packet && validPacketContent(packet, item)
    && recordValue(packet.manifest, "byteHash") === record.manifestHash
    && packet.gateDigest === stableAuthorityHash(packet.gateVerdict)
    && gates?.schemaVersion === 1 && gates.stage === "plan-gates" && gates.round === item.round
    && recordValue(gates.inputAuthority, "digest") === record.authorityDigest
    && boundToPacket(gates.inputPacket, item, packet)
    && recordValue(gates.gates, "ok") === true
    && validTemplateUsageGate(gates)
    && packet.gateDigest === stableAuthorityHash(gates.gates)
    && review?.schemaVersion === 1 && review.stage === "plan" && review.round === item.round
    && recordValue(review.inputAuthority, "digest") === record.authorityDigest
    && boundToPacket(review.inputPacket, item, packet)
    && recordValue(review.review, "verdict") === "pass";
}

function recordValue(value: unknown, key: string): unknown {
  return record(value)?.[key];
}

function validRenderedEvidence(producerDir: string, item: RenderedReviewEvidenceRef, record: ApprovalRecord): boolean {
  if (!verifiedArtifact(producerDir, item)) return false;
  const review = readJson(item.path);
  return review?.schemaVersion === 1 && review.stage === "rendered" && review.lens === item.lens
    && recordValue(review.inputAuthority, "digest") === record.authorityDigest
    && recordValue(review.evidence, "digest") === record.audit.digest
    && recordValue(review.review, "verdict") === "pass";
}

function validSummary(producerDir: string, approval: ApprovalRecord): boolean {
  if (!verifiedArtifact(producerDir, approval.qualitySummary)) return false;
  const summary = readJson(approval.qualitySummary.path);
  const aggregate = record(summary?.aggregate);
  return summary?.schemaVersion === 1 && summary.stage === "quality-summary"
    && summary.qcRound === approval.qcRound
    && recordValue(summary.inputAuthority, "digest") === approval.authorityDigest
    && recordValue(summary.evidence, "digest") === approval.audit.digest
    && recordValue(summary.audit, "failure") === null
    && aggregate?.verdict === "pass"
    && Array.isArray(aggregate.materialIssues) && aggregate.materialIssues.length === 0;
}

function validAuditMachine(item: HashedArtifactRef, expectedSha256: string): boolean {
  const machine = readJson(item.path);
  if (audioAuditFailure(machine, expectedSha256)) return false;
  if (machine?.overall !== "pass" && machine?.overall !== "warn") return false;
  if (!Array.isArray(machine.checks)) return false;
  return !machine.checks.some((check) => recordValue(check, "status") === "fail");
}

/** Validate media, assembly proof, audit/frames, and every independent review receipt. */
export function approvalEvidenceValid(
  producerDir: string,
  mediaPath: string,
  record: ApprovalRecord,
): boolean {
  if (record.finalHash !== record.candidateHash || fileSha256(mediaPath) !== record.finalHash) return false;
  const proofPath = `${mediaPath}.assembled.json`;
  if (fileSha256(proofPath) !== record.assembledProofHash) return false;
  const proof = readJson(proofPath);
  if (proof?.authorityHash !== record.finalHash
      || proof.inputAuthorityDigest !== record.authorityDigest
      || proof.qualityPolicyVersion !== record.qualityPolicyVersion) return false;
  if (record.audit.candidateHash !== record.finalHash
      || record.audit.assembledProofHash !== record.assembledProofHash
      || record.audit.digest !== auditDigest(record.audit)) return false;
  const auditArtifacts = [record.audit.machine, record.audit.report, ...record.audit.frames];
  if (!auditArtifacts.every((item) => verifiedArtifact(producerDir, item))
      || !validAuditMachine(record.audit.machine, record.finalHash)) return false;
  if (record.planningReviews.length !== record.planningRoundsRequired
      || new Set(record.planningReviews.map((item) => item.round)).size !== record.planningReviews.length
      || !record.planningReviews.every((item) => validPlanningEvidence(producerDir, item, record))) return false;
  const lenses = record.renderedReviews.map((item) => item.lens).sort().join(",");
  return lenses === "composition,editorial"
    && record.renderedReviews.every((item) => validRenderedEvidence(producerDir, item, record))
    && validSummary(producerDir, record);
}
