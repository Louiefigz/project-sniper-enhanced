/** TEST-only retained protocol records. No actual claim, source, runtime or media authority. */
import { createHash, randomUUID } from "node:crypto";
import { mkdtempSync, mkdirSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { autoEditRequestKey, canonicalJson, canonicalJsonSha256 } from "../auto-edit-hash";
import type { HeldOpeningClaim } from "../guided-opening-process";
import { writeGuidedObject } from "../guided-cut-v2-store";
import { guidedFixture } from "@/lib/producer/__tests__/_guided-cut-fixture";

const HASH = "a".repeat(64), TIME = "2026-09-06T12:00:00.000Z";

function sourceColorProtocol(root: string, claim: { requestId: string; beforeJournalHash: string }) {
  const sourceColor = { schemaVersion: 1, declarations: { TEST_source: { profile: null, declaration: {
    schemaVersion: 1, sourceId: "TEST_source", sourceProfile: "bt709-sdr", cameraProfile: "TEST statement only",
    historyState: "known", transformHistory: [], lightingGroups: [{ id: "TEST_group", startFrame: 0, endFrame: 24,
      intent: "neutral", description: "TEST synthetic declaration, not verified footage" }] } } } };
  return {
    submission: { schemaVersion: 2, operation: "prepare-guided-opening", idempotencyKey: claim.requestId,
      expectedJournalHash: claim.beforeJournalHash, expectedToken: "TEST", proposalReadinessHash: HASH,
      treatmentDraftRevisionHash: HASH, sourceColor },
    reference: { schemaVersion: 1, kind: "guided-opening-source-color-process-input",
      scope: "explicit-staged-input-not-observation-cleanup-or-approval",
      input: { path: path.join(root, "source-color/input.json"), sha256: HASH, sizeBytes: 123 },
      reservation: { path: path.join(root, ".sniper-color-resource/active.json"), sha256: HASH, sizeBytes: 456 },
      sourceColorHash: canonicalJsonSha256(sourceColor) },
  };
}
function testJob(root: string) {
  const fixture = guidedFixture(root, { schemaVersion: 2, mode: "guided", afterCut: "treatment-then-intro", approvalPolicy: "explicit-human" });
  const job = fixture.run.job;
  job.ctx.pipeline = { schemaVersion: 1, runId: "TEST", digest: HASH, snapshotRoot: path.join(root, "pinned"),
    lockPath: path.join(root, "TEST-lock.json"), files: [{ path: "scripts/producer/guided_opening_media.py", hash: HASH }] };
  job.requestKey = autoEditRequestKey(job.ctx);
  const core = { schemaVersion: 1 as const, requestKey: job.requestKey, planHash: HASH, authorityDigest: HASH, cutAuthorityDigest: HASH,
    cutApprovalReceiptHash: HASH, cutReviewApprovalReceiptHash: HASH, pictureLockHash: HASH, timelineMapHash: HASH, projectionReceiptHash: HASH, createdAt: TIME };
  Object.assign(job, { status: "treatment_admitted", checkpoint: "cut_reviewed", updatedAt: TIME, cutApprovalWaitStartedAt: TIME,
    cutApprovalRequest: { ...core, requestHash: canonicalJsonSha256(core) }, cutPreview: { executionKey: HASH, receiptHash: HASH },
    guidedHandoffV2: { schemaVersion: 2, cutDecisionHash: HASH, cutActivationHash: HASH, pictureLockedRevisionHash: HASH,
      treatmentAdmissionHash: HASH, treatmentProposalHash: HASH, proposalReadinessHash: HASH, treatmentDraftRevisionHash: HASH, openingExecutionClaimHash: HASH } });
  return job;
}

export function openingProcessFixture(outcomePatch: Record<string, unknown> = {}, version = 1) {
  const root = realpathSync(mkdtempSync(path.join(os.tmpdir(), "sniper-opening-stop-protocol-")));
  const script = path.join(root, "pinned/scripts/producer/guided_opening_media.py");
  mkdirSync(path.dirname(script), { recursive: true });
  const executionId = randomUUID(), claim = { executionId, inputSha256: HASH, clockHash: HASH, generationStartedAt: TIME,
    requestId: randomUUID(), beforeJournalHash: HASH, outputRoot: path.join(root, "media-output") };
  const colors = sourceColorProtocol(root, claim);
  const job = testJob(root);
  if (version >= 2) job.ctx.pipeline!.files.push({ path: "scripts/producer/headless/process_runner.py", hash: HASH });
  const priorHash = canonicalJsonSha256(job);
  const snapshots = path.join(job.ctx.dir, "human-cut-job-snapshots"); mkdirSync(snapshots, { recursive: true });
  writeFileSync(path.join(snapshots, `${priorHash}.json`), canonicalJson(job));
  const held = { claim, claimHash: HASH, claimPath: path.join(root, "execution-claim.json"), sha256: HASH, job,
    ...(version === 3 ? { submission: colors.submission } : {}) } as unknown as HeldOpeningClaim;
  const intent = { schemaVersion: version, kind: "guided-opening-process-intent", claimHash: HASH, inputSha256: HASH, executionId,
    journalHash: priorHash, clockHash: HASH, generationStartedAt: TIME, startedAt: "2026-09-06T12:00:01.000Z",
    ...(version === 3 ? { sourceColor: colors.reference } : {}),
    tools: { script, scriptHash: HASH, python: "/private/tmp/TEST-venv/bin/python", pythonResolved: "/private/tmp/TEST-python", pythonHash: HASH,
      venvRoot: "/private/tmp/TEST-venv", venvConfig: "/private/tmp/TEST-venv/pyvenv.cfg", venvConfigHash: HASH,
      ...(version >= 2 ? { runnerScript: path.join(root, "pinned/scripts/producer/headless/process_runner.py"), runnerScriptHash: HASH } : {}) } };
  const ledgerBytes = version >= 2 ? ["worker-started", "worker-finished"].map((event, i) =>
    JSON.stringify({ event, pid: 123456, argv0: script, at: 100 + i })).join("\n") + "\n" : ["intent", "spawned", "reaped"].map((event, i) =>
    JSON.stringify({ event, pid: event === "intent" ? null : 123456, argv0: "/TEST/protocol-only-child", at: 100 + i })).join("\n") + "\n";
  writeFileSync(path.join(root, "owned-process-ledger.media.jsonl"), ledgerBytes);
  const outcome = { schemaVersion: version, kind: "guided-opening-process-outcome", scope: "owned-process-stop-not-media-or-delivery-approval",
    intentHash: canonicalJsonSha256(intent), claimHash: HASH, inputSha256: HASH, executionId, startedAt: intent.startedAt,
    finishedAt: "2026-09-06T12:00:02.000Z", elapsedMs: 1000, status: "failed", error: "TEST protocol failure", timedOut: false,
    groupStopped: true, forcedStop: false, stdout: "", stderr: "TEST protocol only, no real media or Docker",
    ...(version >= 2 ? { ledgerSha256: createHash("sha256").update(ledgerBytes).digest("hex") } : {}), ...outcomePatch };
  const write = (i = intent, o = outcome) => {
    writeFileSync(path.join(root, "media-process-intent.json"), canonicalJson(i));
    writeFileSync(path.join(root, "media-process-result.json"), canonicalJson(o));
  };
  const activation = { schemaVersion: version === 3 ? 2 : 1, kind: "guided-opening-process-activation", scope: "actual-owned-process-outcome-not-media-or-delivery-approval",
    claimHash: HASH, beforeJournalHash: priorHash, executionId, inputSha256: HASH, intentSha256: canonicalJsonSha256(intent),
    outcomeSha256: canonicalJsonSha256(outcome), clockHash: HASH, generationStartedAt: TIME, createdAt: "2026-09-06T12:00:03.000Z" };
  job.guidedHandoffV2!.openingProcessOutcomeHash = writeGuidedObject(job.ctx.dir, activation); job.updatedAt = String(activation.createdAt);
  return { root, held, intent, outcome, activation, colors, write, cleanup: () => rmSync(root, { recursive: true, force: true }) };
}
