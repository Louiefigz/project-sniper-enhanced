import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { existsSync, readFileSync, readdirSync, renameSync, writeFileSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { parseGuidedWorkflowV2, parseGuidedCutSubmissionV2 } from "@/lib/producer/contracts/guided-workflow-v2";
import { parseTreatmentHandoffSubmissionV1 } from "@/lib/producer/contracts/treatment-handoff-v1";
import { prepareRequest } from "@/app/api/producer/auto-edit/request";
import { parseProjectRevision } from "@/lib/producer/contracts/project-revision";
import { parseRenderGraphV1 } from "@/lib/producer/contracts/render-graph";
import { acceptGuidedCutV2, readGuidedCutV2 } from "../guided-cut-v2";
import { admitTreatmentV2, readTreatmentAdmissionV2 } from "../guided-treatment-v2";
import { observeHumanCutJob } from "../human-cut-acceptance-store";
import { acceptGuidedCut } from "../human-cut-acceptance";
import { readGuidedObject, writeGuidedObject } from "../guided-cut-v2-store";
import { autoEditRequestKey, canonicalJsonSha256 } from "../auto-edit-hash";
import { startAutoEditJob } from "../auto-edit-job-store";
import { createHumanCutFixture } from "./_human-cut-fixture";

const workflow = parseGuidedWorkflowV2({ schemaVersion: 2, mode: "guided", afterCut: "treatment-then-intro", approvalPolicy: "explicit-human" });
type Fixture = Awaited<ReturnType<typeof createHumanCutFixture>>;

function submission(fixture: Fixture) {
  const observed = observeHumanCutJob(fixture.ctx.dir);
  const { attestation: _v1, ...base } = fixture.submission; void _v1;
  return parseGuidedCutSubmissionV2({ ...base, schemaVersion: 2, operation: "accept-cut-await-treatment",
    expectedJournalHash: observed.sha256, attestation: { watched: true, listened: true, acceptsExactCut: true, understandsTreatmentPending: true } });
}
function treatment(fixture: Fixture) {
  const cut = readGuidedCutV2(fixture.ctx.dir), clauseId = randomUUID();
  return parseTreatmentHandoffSubmissionV1({ schemaVersion: 1, operation: "admit-post-cut-treatment",
    expectedToken: cut.job.token, expectedJournalHash: cut.sha256, cutDecisionHash: cut.pointer.cutDecisionHash,
    request: { schemaVersion: 1, requestId: randomUUID(), idempotencyKey: randomUUID(), parentRevisionHash: cut.pointer.pictureLockedRevisionHash,
      workflow: "cut-first", rawIntent: "Keep the accepted cut exactly and give it a warm grade.", submittedAt: new Date().toISOString(),
      clauses: [{ schemaVersion: 1, clauseId, text: "Give the unchanged cut a warm grade.", state: "compiled",
        disposition: "explicit treatment-only grade control", blockingClauseIds: [] }] },
    bindings: [{ clauseId, operationId: randomUUID(), disposition: "treatment-only",
      action: { schemaVersion: 1, operation: "grade.set", expectedGrade: "none", grade: "warm" } }],
    confirmation: { preservesAcceptedCut: true, matchesRequestedTreatment: true } });
}
function assertNoDelivery(fixture: Fixture): void {
  for (const name of ["final.mp4", ".sniper-qc-approved.json", ".sniper-template-usage-approved.json", ".render-graph-v1/ACTIVE.json",
    ".sniper-authority-v1/APPROVED_HEAD"]) assert.equal(existsSync(path.join(fixture.ctx.dir, name)), false, name);
}

test("v2 opt-in and decisions are closed and cannot enter the public v1 path", async () => {
  for (const patch of [{ mode: "autopilot" }, { schemaVersion: 1 }, { approvalPolicy: "trust-me" }, { extra: true }]) {
    assert.throws(() => parseGuidedWorkflowV2({ ...workflow, ...patch }));
  }
  const fixture = await createHumanCutFixture({ workflowV2: workflow });
  try {
    const { workflowV2: _v2, ...legacy } = fixture.ctx; void _v2;
    assert.notEqual(autoEditRequestKey(fixture.ctx), autoEditRequestKey(legacy));
    await assert.rejects(acceptGuidedCut({ dir: fixture.ctx.dir, submission: fixture.submission }), /V2 requires/);
    assert.throws(() => prepareRequest({ dir: fixture.ctx.dir, workflowV2: workflow }), /not publicly available/);
    for (const patch of [{ extra: true }, { operation: "accept" }, { expectedJournalHash: "nope" },
      { attestation: { watched: true, listened: false, acceptsExactCut: true, understandsTreatmentPending: true } }]) {
      assert.throws(() => parseGuidedCutSubmissionV2({ ...submission(fixture), ...patch }));
    }
    assert.equal(observeHumanCutJob(fixture.ctx.dir).job.status, "awaiting_cut_approval"); assertNoDelivery(fixture);
    const journal = readFileSync(fixture.jobPath), legacyJob = JSON.parse(journal.toString());
    legacyJob.ctx = legacy; legacyJob.requestKey = autoEditRequestKey(legacy); legacyJob.status = "failed";
    writeFileSync(fixture.jobPath, JSON.stringify(legacyJob));
    const before = readFileSync(fixture.jobPath);
    assert.throws(() => startAutoEditJob({ ctx: fixture.ctx, token: "v2-upgrade", snapshots: 0 }), /upgrading or replacing/);
    assert.deepEqual(readFileSync(fixture.jobPath), before);
    writeFileSync(fixture.jobPath, journal);
  } finally { fixture.cleanup(); }
});

test("actual v2 cut creates real unapproved V2 revision objects, then admits but never executes a new brief", async () => {
  const fixture = await createHumanCutFixture({ workflowV2: workflow });
  try {
    const originalPlan = readFileSync(fixture.ctx.planPath), project = readFileSync(path.join(fixture.root, "project.json"));
    const decision = submission(fixture);
    await (async () => {
      const accepted = await acceptGuidedCutV2({ dir: fixture.ctx.dir, submission: decision });
      assert.equal(accepted.job.status, "awaiting_treatment_brief"); assert.equal(accepted.job.workerPid, undefined);
      const cut = readGuidedCutV2(fixture.ctx.dir), root = path.join(fixture.ctx.dir, ".sniper-authority-v1/objects");
      const revision = parseProjectRevision(JSON.parse(readFileSync(path.join(root, "revisions", `${cut.pointer.pictureLockedRevisionHash}.json`), "utf8")));
      assert.equal(revision.schemaVersion, 2); assert.equal(revision.workflowState, "PICTURE_LOCKED");
      assert.equal(revision.sourceSnapshotSetHash, fixture.receipt.sourceSetDigest);
      assert.ok(existsSync(path.join(root, "plans", `${revision.schemaVersion === 2 && revision.planObjectHash}.json`)));
      const graph = parseRenderGraphV1(JSON.parse(readFileSync(path.join(root, "graphs", `${revision.renderGraphHash}.json`), "utf8")));
      assert.equal(graph.nodes.find((node) => node.nodeId === graph.rootNodeId)!.outputArtifactHash, null);
      assert.equal(graph.nodes.some((node) => node.kind === "final-export"), false);
      assert.equal((await acceptGuidedCutV2({ dir: fixture.ctx.dir, submission: decision })).replayed, true);
      const brief = treatment(fixture), result = await admitTreatmentV2({ dir: fixture.ctx.dir, submission: brief });
      assert.equal(result.job.status, "treatment_admitted"); assert.equal(result.available, false);
      const admitted = readTreatmentAdmissionV2(fixture.ctx.dir);
      assert.equal(admitted.submission.request.rawIntent, brief.request.rawIntent);
      assert.equal(admitted.submission.request.clauses[0].state, "compiled");
      assert.equal(admitted.pointer.pictureLockedRevisionHash, cut.pointer.pictureLockedRevisionHash);
      assert.equal((await admitTreatmentV2({ dir: fixture.ctx.dir, submission: brief })).generationStartedAt, result.generationStartedAt);
      assert.throws(() => startAutoEditJob({ ctx: fixture.ctx, token: "bypass", snapshots: 0 }), /v2 guided workflow/);
    })();
    assert.deepEqual(readFileSync(fixture.ctx.planPath), originalPlan); assert.deepEqual(readFileSync(path.join(fixture.root, "project.json")), project);
    assertNoDelivery(fixture);
  } finally { fixture.cleanup(); }
});

test("v2 source/cut drift blocks admission and preserves the immutable initial generation clock on retry", async () => {
  const fixture = await createHumanCutFixture({ workflowV2: workflow });
  try {
    await (async () => {
      const initial = readFileSync(fixture.jobPath), decision = submission(fixture);
      await assert.rejects(acceptGuidedCutV2({ dir: fixture.ctx.dir, submission: decision }, {
        verifySources: async ({ lease }) => { lease.release(); },
      }), /ENOENT|lease/);
      assert.deepEqual(readFileSync(fixture.jobPath), initial);
      await acceptGuidedCutV2({ dir: fixture.ctx.dir, submission: decision });
      const brief = treatment(fixture), manifest = JSON.parse(readFileSync(fixture.ctx.manifestPath, "utf8"));
      const waitingBytes = readFileSync(fixture.jobPath);
      await assert.rejects(admitTreatmentV2({ dir: fixture.ctx.dir, submission: brief }, {
        verifySources: async () => {
          const external = JSON.parse(waitingBytes.toString()); external.message = "TEST ONLY concurrent journal change";
          writeFileSync(fixture.jobPath, JSON.stringify(external));
        },
      }), /checkpoint changed/);
      assert.equal(JSON.parse(readFileSync(fixture.jobPath, "utf8")).message, "TEST ONLY concurrent journal change");
      writeFileSync(fixture.jobPath, waitingBytes);
      const silent = manifest.sources.find((row: { id: string }) => row.id === "silent").path;
      const original = readFileSync(silent), changed = Buffer.from(original); changed[Math.floor(changed.length / 2)] ^= 1;
      writeFileSync(silent, changed);
      await assert.rejects(admitTreatmentV2({ dir: fixture.ctx.dir, submission: brief }), /exited/);
      assert.equal(observeHumanCutJob(fixture.ctx.dir).job.status, "awaiting_treatment_brief");
      const clockFile = path.join(fixture.ctx.dir, "guided-v2-operations", `generation-${brief.cutDecisionHash}.json`);
      const clockBytes = readFileSync(clockFile), clock = JSON.parse(clockBytes.toString());
      const first = readGuidedObject(fixture.ctx.dir, clock.clockHash).startedAt;
      writeFileSync(silent, original);
      const planBytes = readFileSync(fixture.ctx.planPath), plan = JSON.parse(planBytes.toString()); plan.cutTrack[0].end -= 0.1;
      writeFileSync(fixture.ctx.planPath, JSON.stringify(plan));
      await assert.rejects(admitTreatmentV2({ dir: fixture.ctx.dir, submission: brief }), /authority changed/);
      writeFileSync(fixture.ctx.planPath, planBytes);
      const accepted = await admitTreatmentV2({ dir: fixture.ctx.dir, submission: brief });
      assert.equal(accepted.generationStartedAt, first); assert.deepEqual(readFileSync(clockFile), clockBytes);
    })(); assertNoDelivery(fixture);
  } finally { fixture.cleanup(); }
});

test("orphan v2 genesis/activation replay uses the same cut decision and cannot replace it with a competing decision", async () => {
  const fixture = await createHumanCutFixture({ workflowV2: workflow });
  try {
    await (async () => {
      const decision = submission(fixture), before = observeHumanCutJob(fixture.ctx.dir);
      await assert.rejects(acceptGuidedCutV2({ dir: fixture.ctx.dir, submission: decision }, {
        fault: (point) => { if (point === "after-genesis") throw new Error("injected after-genesis crash"); },
      }), /injected/);
      assert.equal(observeHumanCutJob(fixture.ctx.dir).sha256, before.sha256);
      await assert.rejects(acceptGuidedCutV2({ dir: fixture.ctx.dir, submission: { ...decision, idempotencyKey: randomUUID() } }), /conflicts with existing revision/);
      const accepted = await acceptGuidedCutV2({ dir: fixture.ctx.dir, submission: decision });
      assert.equal(accepted.job.status, "awaiting_treatment_brief");
      const activated = readGuidedCutV2(fixture.ctx.dir);
      assert.equal(activated.activation.decisionSubmittedAt, activated.fact.submittedAt);
      assert.ok(String(activated.activation.executionReceivedAt) > activated.fact.submittedAt);
      const acceptedEvent = activated.job.events.find((event) => event.payload.event === "guided_cut_accepted_v2")!;
      assert.equal(acceptedEvent.payload.userWaitEndedAt, activated.fact.submittedAt);
      assert.equal(acceptedEvent.payload.retryGapClassification, "unclassified-not-human-wait");
      const brief = treatment(fixture);
      await assert.rejects(admitTreatmentV2({ dir: fixture.ctx.dir, submission: brief }, {
        fault: (point) => { if (point === "after-admission") throw new Error("injected admission crash"); },
      }), /injected/);
      assert.equal(observeHumanCutJob(fixture.ctx.dir).job.status, "awaiting_treatment_brief");
      await admitTreatmentV2({ dir: fixture.ctx.dir, submission: brief });
      await assert.rejects(admitTreatmentV2({ dir: fixture.ctx.dir, submission: { ...brief,
        request: { ...brief.request, rawIntent: "silently replace intent" } } }), /different treatment request/);
    })(); assertNoDelivery(fixture);
  } finally { fixture.cleanup(); }
});

test("unsupported/unresolved/cut clauses stay blocked with their complete intake preserved", async () => {
  const fixture = await createHumanCutFixture({ workflowV2: workflow });
  try {
    await (async () => {
      await acceptGuidedCutV2({ dir: fixture.ctx.dir, submission: submission(fixture) });
      const invalid = { ...treatment(fixture), confirmation: { preservesAcceptedCut: false, matchesRequestedTreatment: true } };
      await assert.rejects(admitTreatmentV2({ dir: fixture.ctx.dir, submission: invalid }), /explicit confirmation/);
      assert.equal(existsSync(path.join(fixture.ctx.dir, "guided-v2-operations", `generation-${invalid.cutDecisionHash}.json`)), false);
      const brief = treatment(fixture), unsupported = { ...brief, request: { ...brief.request,
        rawIntent: "Add music; do not discard this request.", clauses: brief.request.clauses.map((clause) => ({ ...clause, text: "Add music.", state: "unsupported" })) } };
      await assert.rejects(admitTreatmentV2({ dir: fixture.ctx.dir, submission: unsupported }), /unresolved treatment clauses/);
      const retained = JSON.parse(readFileSync(path.join(fixture.ctx.dir, "guided-v2-operations", brief.request.idempotencyKey, "submission.json"), "utf8"));
      assert.deepEqual(retained.submission, unsupported); assert.equal(retained.submissionHash, canonicalJsonSha256(unsupported));
      assert.equal(observeHumanCutJob(fixture.ctx.dir).job.status, "awaiting_treatment_brief");
      const actions = [{ operation: "music.set" }, { operation: "cut.restoreSpeech" }];
      for (const action of actions) assert.throws(() => parseTreatmentHandoffSubmissionV1({ ...brief,
        bindings: [{ ...brief.bindings[0], action: { schemaVersion: 1, ...action } }] }));
      assert.ok(readdirSync(path.join(fixture.ctx.dir, "guided-v2-operations", brief.request.idempotencyKey, "executions")).length);
      const replacement = treatment(fixture);
      await assert.rejects(admitTreatmentV2({ dir: fixture.ctx.dir, submission: replacement }), /Earlier treatment clauses/);
      const explicit = treatment(fixture);
      explicit.request.rawIntent = "I changed my mind: replace the earlier music request with a warm grade.";
      explicit.request.clauses[0].supersedesClauseId = unsupported.request.clauses[0].clauseId;
      const admitted = await admitTreatmentV2({ dir: fixture.ctx.dir, submission: explicit });
      const firstIntake = JSON.parse(readFileSync(path.join(fixture.ctx.dir, "guided-v2-operations", brief.request.idempotencyKey, "submission.json"), "utf8"));
      assert.equal(admitted.generationStartedAt, firstIntake.receivedAt);
      assert.equal(readTreatmentAdmissionV2(fixture.ctx.dir).submission.request.clauses[0].state, "compiled");
    })(); assertNoDelivery(fixture);
  } finally { fixture.cleanup(); }
});

test("accepted parent fails closed when required graph/projection/ledger/source objects disappear or change", async () => {
  const fixture = await createHumanCutFixture({ workflowV2: workflow });
  try {
    await acceptGuidedCutV2({ dir: fixture.ctx.dir, submission: submission(fixture) });
    const cut = readGuidedCutV2(fixture.ctx.dir), objects = path.join(fixture.ctx.dir, ".sniper-authority-v1/objects");
    const references = [["graphs", cut.revision.renderGraphHash], ["projections", cut.revision.projectionReceiptHash],
      ["requests", cut.revision.requestLedgerHash], ["receipts", cut.revision.authoritativeSidecars.sourceSetSnapshot],
      ["receipts", cut.revision.authoritativeSidecars.manifestSnapshot], ["receipts", cut.revision.canvasProfileHash]];
    for (const [kind, hash] of references) {
      assert.equal(typeof hash, "string"); assert.ok(kind);
      const file = path.join(objects, kind, `${hash}.json`), backup = `${file}.held`, original = readFileSync(file);
      renameSync(file, backup);
      try { assert.throws(() => readGuidedCutV2(fixture.ctx.dir)); } finally { renameSync(backup, file); }
      writeFileSync(file, "{}");
      try { assert.throws(() => readGuidedCutV2(fixture.ctx.dir), /closure changed/); } finally { writeFileSync(file, original); }
    }
    assert.equal(readGuidedCutV2(fixture.ctx.dir).job.status, "awaiting_treatment_brief"); assertNoDelivery(fixture);
  } finally { fixture.cleanup(); }
});

function resealAdmission(fixture: Fixture, admission: Record<string, unknown>, jobBytes: Buffer): void {
  const job = JSON.parse(jobBytes.toString());
  job.guidedHandoffV2.treatmentAdmissionHash = writeGuidedObject(fixture.ctx.dir, admission);
  writeFileSync(fixture.jobPath, JSON.stringify(job));
}

test("resealed cross-cut/future clocks and invalid execution paths cannot reset or forge admission evidence", async () => {
  const fixture = await createHumanCutFixture({ workflowV2: workflow });
  try {
    await acceptGuidedCutV2({ dir: fixture.ctx.dir, submission: submission(fixture) });
    await admitTreatmentV2({ dir: fixture.ctx.dir, submission: treatment(fixture) });
    const accepted = readTreatmentAdmissionV2(fixture.ctx.dir), jobBytes = readFileSync(fixture.jobPath);
    const index = path.join(fixture.ctx.dir, "guided-v2-operations", `generation-${accepted.pointer.cutDecisionHash}.json`);
    const indexBytes = readFileSync(index), clock = readGuidedObject(fixture.ctx.dir, String(accepted.admission.clockHash));
    for (const patch of [{ cutDecisionHash: "f".repeat(64) }, { runId: "another-run" }, { startedAt: "2099-01-01T00:00:00.000Z" },
      { schemaVersion: 1 }, { scope: "after-compilation" }, { extra: true }, { firstRequestHash: "e".repeat(64) }]) {
      const clockHash = writeGuidedObject(fixture.ctx.dir, { ...clock, ...patch });
      resealAdmission(fixture, { ...accepted.admission, clockHash }, jobBytes);
      writeFileSync(index, JSON.stringify({ clockHash }));
      try { assert.throws(() => readTreatmentAdmissionV2(fixture.ctx.dir)); }
      finally { writeFileSync(index, indexBytes); writeFileSync(fixture.jobPath, jobBytes); }
    }
    for (const executionId of ["../outside", "/private/tmp", "bad-id"]) {
      resealAdmission(fixture, { ...accepted.admission, executionId }, jobBytes);
      try { assert.throws(() => readTreatmentAdmissionV2(fixture.ctx.dir), /executionId/); }
      finally { writeFileSync(fixture.jobPath, jobBytes); }
    }
    assert.equal(readTreatmentAdmissionV2(fixture.ctx.dir).generationStartedAt, accepted.generationStartedAt); assertNoDelivery(fixture);
  } finally { fixture.cleanup(); }
});
