import { randomUUID } from "node:crypto";
import path from "node:path";
import { canonicalJson, canonicalJsonSha256 as hash } from "../auto-edit-hash";
import { OPENING_APPROVAL_MESSAGE } from "../guided-opening-approval";
import { guidedBodyAuthorityReads } from "../guided-body-authority";
import type { GuidedFrameBindingsV1 } from "../guided-proposal-bindings";

export const BODY_TEST_HASH = "a".repeat(64), BODY_TEST_DIR = "/private/tmp/TEST-ONLY-body-input/producer";
const TIME = "2026-09-06T12:00:00.000Z", SELECTED = "2026-09-06T12:01:00.000Z", APPROVED = "2026-09-06T12:02:00.000Z";
type Row = Record<string, unknown>;
export function bodyTestDocument(value: Row) {
  const bytes = Buffer.from(canonicalJson(value));
  return { value, bytes, sha256: hash(value), sizeBytes: bytes.length };
}

function priorJob() {
  return { token: "TEST-guided", status: "treatment_admitted", nextEventId: 2, updatedAt: SELECTED, events: [], message: "TEST selected",
    ctx: { dir: BODY_TEST_DIR, manifestPath: `${BODY_TEST_DIR}/manifest.json` },
    guidedHandoffV2: { schemaVersion: 2, cutDecisionHash: BODY_TEST_HASH, pictureLockedRevisionHash: BODY_TEST_HASH,
      proposalReadinessHash: BODY_TEST_HASH, treatmentDraftRevisionHash: BODY_TEST_HASH,
      openingCleanupHash: BODY_TEST_HASH, openingMediaSelectionHash: BODY_TEST_HASH } };
}

/** Rich TEST-only candidate/clock metadata: seven opening cards plus one later body occurrence. */
export function bodyMetadataFixture() {
  const target = { mode: "longform", width: 1920, height: 1080, fps: 30 };
  const starts = [0, 200, 400, 600, 800, 1000, 1200, 6000];
  const graphicsTrack = starts.map((start, order) => ({ id: `TEST-graphic-${order}`, kind: "statement-card", anchor: "own-screen",
    outStart: start * 1001 / 30000, outEnd: (start + 180) * 1001 / 30000,
    spec: { headline: `TEST whole-program statement ${order}`, width: 1920, height: 1080 } }));
  const candidate = { planVersion: 1, target, cutTrack: [{ sourceId: "TEST-source", start: 0, end: 311.742, speed: 1 }],
    graphicsTrack, captions: { burn: false }, reframe: { strategy: "none" } };
  const presentation = { schemaVersion: 1, anchor: "own-screen", placement: "full-canvas", compositeMode: "normal",
    baseTreatment: "preserve", rationale: "TEST declared presentation only" } as const;
  const bindings: GuidedFrameBindingsV1 = { schemaVersion: 1, kind: "guided-frame-presentation-bindings",
    scope: "controller-frames-and-declared-presentation-not-rendered-proof", frameRate: "30000/1001", totalFrames: 9346,
    targetHash: hash(target), candidatePlanHash: hash(candidate), occurrenceEvidenceHash: BODY_TEST_HASH,
    graphics: graphicsTrack.map((entry, order) => ({ graphicId: entry.id, order, operationIndex: order,
      startFrame: starts[order], endFrameExclusive: starts[order] + 180, entryHash: hash(entry), presentation })), unboundInheritedGraphicIds: [] };
  return { candidate, bindings };
}

function openingRecord(root: string) {
  return { authority: { candidatePlanHash: BODY_TEST_HASH, clockHash: BODY_TEST_HASH, generationStartedAt: TIME,
    target: { width: 1920, height: 1080 } },
    documents: { candidatePlan: { path: `${BODY_TEST_DIR}/.sniper-authority-v1/objects/plans/${BODY_TEST_HASH}.json`, sha256: BODY_TEST_HASH },
      manifest: { path: `${BODY_TEST_DIR}/manifest.json`, sha256: BODY_TEST_HASH } },
    fullProgram: { fullBasePrepared: true, bodyGraphicsPrepared: false, baseAudibleTrackNotSelected: true,
      base: { path: `${root}/full-program-base/final.mp4`, sha256: BODY_TEST_HASH,
        codec: "h264", frameRate: "30000/1001", frames: 90, height: 1080, width: 1920,
        packetTimelineSha256: BODY_TEST_HASH, sizeBytes: 123456, startPts: 0, timeBase: "1/30000", videoDecodeSucceeded: true },
      fullMasterSelectionEventPath: `${root}/full-program-base/audio/master/selection-event.json`,
      fullMasterSelectionEventSha256: BODY_TEST_HASH } };
}

function readbackResult(claim: Row, record: ReturnType<typeof bodyTestDocument>, root: string) {
  const stages = ["held-result", "held-claim", "current-input-and-sources", "exact-profile-and-frames", "current-code-and-tools",
    "held-whole-master-and-excerpts", "exact-graphic-artifacts", "actual-range-media-readback", "final-source-result-recheck"];
  return { schemaVersion: 1, kind: "guided-opening-media-readback", status: "verified", scope: "exact-held-private-media-not-opening-or-delivery-approval",
    executionId: claim.executionId, inputSha256: BODY_TEST_HASH, executionInputHash: BODY_TEST_HASH, claimSha256: BODY_TEST_HASH,
    receiptPath: `${root}/media-result.json`, receiptSha256: record.sha256, receiptHash: BODY_TEST_HASH,
    elapsedMs: 10, stages: stages.map((stage) => ({ stage, status: "complete", elapsedMs: 1 })),
    processGroupAndDockerCleanup: "requires-separate-owned-server-observation", currentJournalAndLease: "requires-separate-owned-server-observation",
    openingApproved: false, deliveryApproved: false };
}

function readbackRecords(input: { claim: Row; beforeHash: string; recordHash: string; result: Row }) {
  const { claim, beforeHash, recordHash, result } = input;
  const common = { beforeJournalHash: beforeHash, cleanupHash: BODY_TEST_HASH, claimHash: BODY_TEST_HASH,
    clockHash: BODY_TEST_HASH, generationStartedAt: TIME };
  const start = bodyTestDocument({ schemaVersion: 1, kind: "guided-opening-readback-start", ...common, executionId: claim.executionId,
    receiptSha256: recordHash, tools: { script: "/TEST/pinned-read.py", scriptHash: BODY_TEST_HASH }, startedAt: "2026-09-06T12:01:01.000Z" });
  const output = bodyTestDocument({ schemaVersion: 1, kind: "guided-opening-readback-owned-output", stdout: JSON.stringify(result), stderr: "",
    processGroupStopped: true, observedAt: "2026-09-06T12:01:02.000Z", elapsedMs: 12 });
  const receipt = bodyTestDocument({ schemaVersion: 1, kind: "guided-opening-owned-readback", scope: "actual-current-readback-not-selected-or-approved",
    ...common, startSha256: start.sha256, outputSha256: output.sha256, result, createdAt: "2026-09-06T12:01:03.000Z",
    mediaSelected: false, openingApproved: false, deliveryApproved: false });
  return { start, output, receipt };
}

/** TEST-ONLY coherent protocol objects. No generated media, approval or source-byte proof. */
export function bodyAuthorityFixture() {
  const dir = BODY_TEST_DIR, root = `${dir}/TEST-execution/media-output`, before = bodyTestDocument(priorJob());
  const claim = { executionId: randomUUID(), inputSha256: BODY_TEST_HASH, executionInputHash: BODY_TEST_HASH, clockHash: BODY_TEST_HASH,
    generationStartedAt: TIME, outputRoot: root }, record = bodyTestDocument(openingRecord(root));
  const resultValue = readbackResult(claim, record, root), records = readbackRecords({ claim, beforeHash: before.sha256, recordHash: record.sha256, result: resultValue });
  const approvalRoot = `${dir}/TEST-execution/readback-attempts/${randomUUID()}`;
  const held = { claim, claimHash: BODY_TEST_HASH, claimSha256: BODY_TEST_HASH, claimPath: `${dir}/TEST-execution/execution-claim.json` };
  const selected = { held, selectionHash: BODY_TEST_HASH, selectionQualifiedAt: SELECTED, fact: { schemaVersion: 1, cleanupHash: BODY_TEST_HASH },
    rows: { core: { mediaSha256: BODY_TEST_HASH }, review: { mediaSha256: BODY_TEST_HASH } }, observed: { sha256: "" } };
  const result = { record, completion: { ...resultValue, executionClaimSha256: BODY_TEST_HASH },
    process: { receipt: { schemaVersion: 1 }, sourceColor: null } }; // TEST legacy discriminator only, not an actual stopped process.
  const decision = { schemaVersion: 1, operation: "approve-guided-opening", idempotencyKey: randomUUID(), expectedToken: "TEST-guided",
    expectedJournalHash: before.sha256, selectionHash: BODY_TEST_HASH, coreMediaSha256: BODY_TEST_HASH, reviewMediaSha256: BODY_TEST_HASH,
    attestation: { watchedOpening: true, watchedBodyTransition: true, listened: true, approvesOpening: true, understandsBodyPending: true } };
  const fact: Row = { schemaVersion: 1, kind: "guided-opening-approval", scope: "human-opening-approval-not-body-or-delivery-approval", actor: "local-operator",
    decision, decisionHash: hash(decision), selectionHash: BODY_TEST_HASH, claimHash: BODY_TEST_HASH, executionId: claim.executionId,
    cleanupHash: BODY_TEST_HASH, mediaResultSha256: record.sha256, receiptHash: BODY_TEST_HASH,
    coreMediaSha256: BODY_TEST_HASH, reviewMediaSha256: BODY_TEST_HASH, beforeJournalHash: before.sha256,
    clockHash: BODY_TEST_HASH, generationStartedAt: TIME, approvedAt: APPROVED, openingApproved: true, bodyGenerated: false, deliveryApproved: false,
    requalification: { readbackReceiptSha256: records.receipt.sha256, readbackOutputSha256: records.output.sha256,
      readbackDirectory: path.basename(approvalRoot), elapsedMs: 12 } };
  return finishFixture({ dir, root, before, held, selected, result, fact, records, resultValue, approvalRoot });
}

function finishFixture(input: { dir: string; root: string; before: ReturnType<typeof bodyTestDocument>; held: Row;
  selected: Row; result: Row; fact: Row; records: ReturnType<typeof readbackRecords>; resultValue: Row; approvalRoot: string }) {
  const { dir, before, held, selected, result, fact, records, resultValue, approvalRoot } = input;
  const files = new Map<string, ReturnType<typeof bodyTestDocument>>(), hashOfApproval = hash(fact);
  const pointer = object(before.value.guidedHandoffV2), event = { id: 2, at: APPROVED, payload: { event: "opening_approved_by_operator",
    approvalHash: hashOfApproval, selectionHash: BODY_TEST_HASH, executionId: fact.executionId, bodyGenerated: false, deliveryApproved: false } };
  const job = { ...before.value, updatedAt: APPROVED, message: OPENING_APPROVAL_MESSAGE,
    guidedHandoffV2: { ...pointer, openingApprovalHash: hashOfApproval }, nextEventId: 3, events: [event] };
  const current = { ...bodyTestDocument(job), job }, submission = { schemaVersion: 1, operation: "continue-approved-opening", idempotencyKey: randomUUID(),
    expectedToken: "TEST-guided", expectedJournalHash: current.sha256, openingApprovalHash: hashOfApproval, selectionHash: BODY_TEST_HASH,
    proposalReadinessHash: BODY_TEST_HASH, treatmentDraftRevisionHash: BODY_TEST_HASH };
  Object.assign(selected, { observed: { sha256: current.sha256 } });
  const metadata = bodyMetadataFixture();
  const proposal = { sha256: current.sha256, job, pointer: job.guidedHandoffV2, readinessHash: BODY_TEST_HASH, readiness: { verdict: "clean" },
    result: { candidate: metadata.candidate }, draftRevision: {}, readinessReceipt: {}, manifest: { sha256: BODY_TEST_HASH }, clock: { hash: BODY_TEST_HASH }, generationStartedAt: TIME };
  files.set(`${dir}/human-cut-job-snapshots/${before.sha256}.json`, before);
  for (const [name, doc] of Object.entries(records)) files.set(`${approvalRoot}/${name === "receipt" ? "verified" : name}.json`, doc);
  files.set(`${approvalRoot}/approval.json`, bodyTestDocument({ ...fact, approvalHash: hashOfApproval }));
  const verifyRoot = `${dir}/TEST-execution/readback-attempts/${randomUUID()}`;
  const freshStart = bodyTestDocument({ ...records.start.value, beforeJournalHash: current.sha256 });
  files.set(`${verifyRoot}/start.json`, freshStart);
  const verified = { observed: { sha256: current.sha256, cleanupHash: BODY_TEST_HASH, held }, selected: result, result: resultValue,
    receipt: { ...bodyTestDocument({ ...records.receipt.value, beforeJournalHash: current.sha256, startSha256: freshStart.sha256 }), path: `${verifyRoot}/verified.json` },
    output: { ...records.output, path: `${verifyRoot}/output.json` } };
  let verifications = 0, checks = 0;
  const faults = { lease: false, budget: false, verification: false, record: false, failure: false };
  const reads = { canonicalDir: (value: unknown) => { if (value !== dir) throw new Error("TEST invalid canonical project"); return dir; },
    leaseGuard: () => () => { checks += 1; if (faults.lease) throw new Error("TEST replaced lease"); }, job: () => current,
    readiness: () => proposal, selection: () => selected, result: () => result,
    mediaAuthority: () => ({ authority: object(object(result.record).value).authority, bindings: metadata.bindings }),
    verify: async () => { verifications += 1; if (faults.verification) throw new Error("TEST failed actual verifier"); return verified; },
    record: () => { if (faults.record) throw new Error("TEST changed verification record"); },
    approval: { approval: () => ({ approvalHash: hashOfApproval, approvedAt: APPROVED, decisionHash: fact.decisionHash }), object: () => fact,
      file: (file: string) => { const value = files.get(file); if (!value) throw new Error(`TEST missing ${file}`); return value; },
      absent: () => { if (faults.failure) throw new Error("TEST retained failure"); } } } as unknown as typeof guidedBodyAuthorityReads;
  const request = { dir, submission, lease: { release() { throw new Error("Must not release caller lease"); } },
    remainingMs: () => { if (faults.budget) throw new Error("TEST expired caller remainder"); return 60_000; } };
  return { ...input, files, current, proposal, submission, verified, reads, request, faults, counts: () => ({ verifications, checks }) };
}
function object(value: unknown): Row { return value as Row; }
