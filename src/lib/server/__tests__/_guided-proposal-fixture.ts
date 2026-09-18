import { randomUUID } from "node:crypto";
import path from "node:path";
import { writeFileSync } from "node:fs";
import { CutPreviewProcessError } from "@/app/api/producer/auto-edit/cut-preview-process";
import { parseGuidedWorkflowV2, parseGuidedCutSubmissionV2 } from "@/lib/producer/contracts/guided-workflow-v2";
import { parseRawTreatmentSubmissionV1, parseTreatmentCompileSubmissionV1 } from "@/lib/producer/contracts/raw-treatment-v1";
import { parseProposalReadinessSubmission, parseProposalReadinessReview } from "@/lib/producer/contracts/proposal-readiness-v1";
import { createHumanCutFixture, type SyntheticProgram } from "./_human-cut-fixture";
import { acceptGuidedCutV2, readGuidedCutV2 } from "../guided-cut-v2";
import { admitRawTreatment } from "../guided-raw-treatment";
import { readRawTreatmentAdmission } from "../guided-raw-treatment-store";
import { compileGuidedTreatmentProposal } from "../guided-proposal";
import { readGuidedTreatmentProposal } from "../guided-proposal-store";
import { canonicalJsonSha256 } from "../auto-edit-hash";
import { observeHumanCutJob } from "../human-cut-acceptance-store";
import { buildProposalReadinessPrompt } from "../guided-proposal-review-packet";
import type { ProposalReadinessBrainInput } from "../guided-proposal-review-brain";
import type { ProposalBrainInput } from "../guided-proposal-compiler";
import { guidedProposalOutput } from "./_readiness-gate-stub";
import type { NativeReferenceSelection } from "../guided-native-references";
import { nativeDirectorTestBrain } from "./_native-director-fixture";
import type { DirectorBrain } from "../native-director-store";

/** Real synthetic bytes/pinned advisors; admission decode/image facts and every creative/critic reply are TEST stubs. */
export async function createGuidedProposalFixture(options: { workspace?: string; rawIntent?: string; output?: (input: ProposalBrainInput) => unknown;
  sourceCanvas?: "160x90" | "1920x1080"; retainFailure?: boolean; program?: SyntheticProgram; captionIntent?: "auto";
  proposalVersion?: 4 | 5 | 6 | 7 | 8 | 9 | 10; graphicsOff?: boolean; presentationAsset?: "admitted-silent-video";
  nativeReferences?: NativeReferenceSelection[]; directorBrain?: DirectorBrain } = {}) {
  const workflow = parseGuidedWorkflowV2({ schemaVersion: 2, mode: "guided", afterCut: "treatment-then-intro", approvalPolicy: "explicit-human" });
  const fixture = await createHumanCutFixture({ workflowV2: workflow, workspace: options.workspace, sourceCanvas: options.sourceCanvas,
    program: options.program, captionIntent: options.captionIntent, graphicsOff: options.graphicsOff,
    presentationAsset: options.presentationAsset, nativeShort: options.proposalVersion === 9 || options.proposalVersion === 10 });
  if (options.retainFailure) process.stderr.write(`TEST fixture retained root: ${fixture.root}\n`);
  try {
    const { attestation: _old, ...base } = fixture.submission; void _old;
    await acceptGuidedCutV2({ dir: fixture.ctx.dir, submission: parseGuidedCutSubmissionV2({ ...base,
      schemaVersion: 2, operation: "accept-cut-await-treatment", expectedJournalHash: observeHumanCutJob(fixture.ctx.dir).sha256,
      attestation: { watched: true, listened: true, acceptsExactCut: true, understandsTreatmentPending: true } }) });
    const cut = readGuidedCutV2(fixture.ctx.dir), rawIntent = options.rawIntent ?? "Preserve the accepted cut exactly.";
    await admitRawTreatment({ dir: fixture.ctx.dir, submission: parseRawTreatmentSubmissionV1({ schemaVersion: 1,
      operation: "propose-post-cut-treatment", requestId: randomUUID(), idempotencyKey: randomUUID(), expectedToken: cut.job.token,
      expectedJournalHash: cut.sha256, cutDecisionHash: cut.pointer.cutDecisionHash, parentRevisionHash: cut.pointer.pictureLockedRevisionHash, rawIntent }) });
    const admitted = readRawTreatmentAdmission(fixture.ctx.dir);
    const submission = parseTreatmentCompileSubmissionV1({ schemaVersion: 1, operation: "compile-post-cut-proposal", idempotencyKey: randomUUID(),
      expectedToken: admitted.job.token, expectedJournalHash: admitted.sha256, treatmentAdmissionHash: admitted.pointer.treatmentAdmissionHash });
    await compileGuidedTreatmentProposal({ dir: fixture.ctx.dir, submission }, { proposalVersion: options.proposalVersion,
      nativeReferences: options.nativeReferences,
      ...(options.proposalVersion === 9 || options.proposalVersion === 10 ? { directorBrain: options.directorBrain ?? nativeDirectorTestBrain } : {}), brain: async (input) => {
      return { output: options.output ? options.output(input) : guidedProposalOutput(input, rawIntent),
      provider: "codex", model: "TEST-ONLY-provider", effort: "xhigh", elapsedMs: 1, promptHash: canonicalJsonSha256(input.prompt) };
    } });
    return fixture;
  } catch (error) {
    if (options.retainFailure) writeFileSync(path.join(fixture.root, "TEST-SETUP-FAILURE.json"), JSON.stringify({
      scope: "TEST-only-failed-setup-not-media-or-editorial-approval", error: String(error).slice(0, 2000),
      cause: error instanceof Error ? String(error.cause ?? "").slice(0, 2000) : "",
      ...(error instanceof CutPreviewProcessError ? { ...error.details,
        stdout: error.details.stdout.slice(0, 262144), stderr: error.details.stderr.slice(0, 262144) } : {}),
    }), { flag: "wx", mode: 0o600 });
    else fixture.cleanup();
    throw error;
  }
}

export function readinessRequest(dir: string) {
  const proposal = readGuidedTreatmentProposal(dir);
  return parseProposalReadinessSubmission({ schemaVersion: 1, operation: "review-post-cut-proposal", idempotencyKey: randomUUID(),
    expectedToken: proposal.job.token, expectedJournalHash: proposal.sha256, proposalHash: proposal.proposalHash });
}

export function passingReadinessResult(input: ProposalReadinessBrainInput) {
  // Coverage requires each story-beat check to cite an occurrence inside that beat's own frame range.
  const evidence = input.packet.evidence as { anchors: number[]; occurrences: Array<readonly [number, number, number, number, number, ...unknown[]]> };
  const inBeat = (beat: { startAnchor: number; endAnchorExclusive: number }) => {
    const start = evidence.anchors[beat.startAnchor], end = evidence.anchors[beat.endAnchorExclusive];
    const index = evidence.occurrences.findIndex((row) => row[3] < end && row[4] > start);
    return index < 0 ? [0] : [index];
  };
  const checks = [...input.packet.proposal.clauses.map((_, index) => ({ kind: "clause", index, occurrenceIds: [0] })),
    ...input.packet.proposal.beats.map((beat, index) => ({ kind: "beat", index, occurrenceIds: inBeat(beat) }))].map((row) => ({ ...row,
    verdict: "pass", reason: "TEST ONLY occurrence-grounded contract fixture, not creative judgment." }));
  return { criticIndex: input.criticIndex, packetHash: canonicalJsonSha256(input.packet),
    promptHash: canonicalJsonSha256(buildProposalReadinessPrompt(input.packet, input.criticIndex)),
    provider: "codex" as const, model: "TEST-ONLY-critic", effort: "medium", elapsedMs: 1,
    review: parseProposalReadinessReview({ schemaVersion: 1, stage: "proposal-readiness", verdict: "pass",
      summary: `TEST ONLY independent fixture${input.criticIndex}`, checks, materialIssues: [], findings: [] }) };
}
