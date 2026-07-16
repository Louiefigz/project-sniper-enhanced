import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import type { AutoEditCtx } from "../../../app/api/producer/auto-edit/stream";
import { bindAuthorityProof } from "../../server/auto-edit-authority";
import {
  autoEditAuthoritySnapshot,
  stableAuthorityHash,
} from "../../server/auto-edit-authority-snapshot";
import { artifactRef } from "../../../app/api/producer/auto-edit/review-evidence";
import { fileSha256 } from "../../server/auto-edit-hash";
import {
  planningRoundDir,
  writeQualityJson,
  type ApprovalRecord,
} from "../../server/auto-edit-quality-artifacts";

interface ApprovalFixtureArgs {
  ctx: AutoEditCtx;
  token: string;
  candidate: string;
  qcRound?: number;
  planningRoundsRequired?: number;
}

function passReview(stage: "plan" | "rendered") {
  return {
    schemaVersion: 1, stage, verdict: "pass", summary: "clean",
    materialIssues: [], findings: [],
  };
}

function writePacketFixture(
  dir: string,
  round: number,
  authority: ReturnType<typeof autoEditAuthoritySnapshot>,
  gates: Record<string, unknown>,
) {
  const gateDigest = stableAuthorityHash(gates);
  const core = {
    schemaVersion: 1, kind: "producer-plan-review-packet", stage: "plan", round,
    inputAuthority: authority,
    request: { scope: "produced", operatorIntent: null },
    doctrineHash: null, reference: null,
    plan: { byteHash: authority.planHash, content: {} },
    manifest: { byteHash: authority.manifestHash, content: {} },
    gateDigest, gateVerdict: gates,
    timeline: { outputDuration: 0, segments: [] },
    transcriptEvidence: {
      transcripts: [], missingTranscriptSourceIds: [], keptWords: [], boundaryNeighbors: [],
    },
  };
  const value = { ...core, contentDigest: stableAuthorityHash(core) };
  const packetPath = writeQualityJson(
    path.join(dir, "critic-input", "plan-review-packet.json"), value,
  );
  return {
    ...artifactRef(packetPath), contentDigest: value.contentDigest,
    authorityDigest: authority.digest, gateDigest, round,
  };
}

export function writeApprovalFixture(args: ApprovalFixtureArgs): ApprovalRecord {
  const authority = autoEditAuthoritySnapshot(args.ctx);
  bindAuthorityProof(args.candidate, authority, { exists: (item) => !!fileSha256(item), hashFile: fileSha256 });
  const required = args.planningRoundsRequired ?? 1;
  const planningReviews = writePlanningReviewFixtures(args.ctx, args.token, authority, required);
  const candidateDir = path.dirname(args.candidate);
  const framePath = path.join(candidateDir, "approval-frame.jpg");
  const machinePath = path.join(candidateDir, "audit_report.json");
  const reportPath = path.join(candidateDir, "audit_report.md");
  writeFileSync(framePath, "approved-frame");
  writeFileSync(machinePath, JSON.stringify({
    overall: "pass", frames: [{ path: framePath }], checks: [],
  }));
  writeFileSync(reportPath, "# pass\n");
  const evidenceContent = {
    candidateHash: fileSha256(args.candidate)!,
    assembledProofHash: fileSha256(`${args.candidate}.assembled.json`)!,
    machine: artifactRef(machinePath), report: artifactRef(reportPath), frames: [artifactRef(framePath)],
  };
  const evidence = { ...evidenceContent, digest: stableAuthorityHash(evidenceContent) };
  const renderedReviews = (["composition", "editorial"] as const).map((lens) => {
    const reviewPath = writeQualityJson(path.join(candidateDir, `${lens}-review.json`), {
      schemaVersion: 1, stage: "rendered", round: args.qcRound ?? 1, lens,
      inputAuthority: authority, evidence, provider: "codex", ms: 1,
      review: passReview("rendered"),
    });
    return { lens, ...artifactRef(reviewPath) };
  });
  const qualitySummaryPath = writeQualityJson(path.join(candidateDir, "quality-summary.json"), {
    schemaVersion: 1, stage: "quality-summary", qcRound: args.qcRound ?? 1,
    inputAuthority: authority, evidence, audit: { failure: null },
    aggregate: passReview("rendered"), reviews: renderedReviews,
  });
  return {
    schemaVersion: 2,
    qualityPolicyVersion: 1,
    authorityDigest: authority.digest,
    planHash: authority.planHash!, manifestHash: authority.manifestHash!,
    finalHash: evidence.candidateHash, candidateHash: evidence.candidateHash,
    assembledProofHash: evidence.assembledProofHash,
    qcRound: args.qcRound ?? 1, approvedAt: new Date().toISOString(),
    planningRoundsRequired: required, planningReviews, renderedReviews,
    audit: evidence, qualitySummary: artifactRef(qualitySummaryPath),
  };
}

export function writePlanningReviewFixtures(
  ctx: AutoEditCtx,
  token: string,
  authority: ReturnType<typeof autoEditAuthoritySnapshot>,
  required: number,
) {
  return Array.from({ length: required }, (_, index) => {
    const round = index + 1;
    const dir = planningRoundDir(ctx.dir, token, round);
    mkdirSync(dir, { recursive: true });
    const gates = { ok: true, errors: [], warnings: [], gates: {
      operatorIntent: {
        gate: "operator_intent", ok: true, errors: [], warnings: [], exit: 0,
      },
      templateUsage: {
        gate: "template_usage", ok: true, errors: [], warnings: [], exit: 0,
        metrics: { snapshotDigest: authority.digest },
      },
    } };
    const packet = writePacketFixture(dir, round, authority, gates);
    const gatesPath = writeQualityJson(path.join(dir, "planning-gates.json"), {
      schemaVersion: 1, stage: "plan-gates", round, inputAuthority: authority,
      inputPacket: packet, gates,
    });
    const reviewPath = writeQualityJson(path.join(dir, "plan-review.json"), {
      schemaVersion: 1, stage: "plan", round, inputAuthority: authority,
      inputPacket: packet, provider: "codex", ms: 1, review: passReview("plan"),
    });
    return {
      round, authorityDigest: authority.digest, planHash: authority.planHash!,
      packet: artifactRef(packet.path), gates: artifactRef(gatesPath), review: artifactRef(reviewPath),
    };
  });
}
