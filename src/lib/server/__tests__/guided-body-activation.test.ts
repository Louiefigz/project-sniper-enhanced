import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { parseGuidedBodyMediaInput, BODY_MEDIA_REFERENCES } from "@/lib/producer/contracts/guided-body-media-v1";
import { parseGuidedBodyExecutionActivation, assertBodyActivationInput } from "@/lib/producer/contracts/guided-body-activation-v1";
import { consumeFreshBodyAdmission, withFreshGuidedBodyAdmission, type FreshBodyAdmission } from "../guided-body-claim";
import { bodyClaimFixture } from "./_guided-body-claim-fixture";
import { cutPreviewLeaseGuard } from "@/app/api/producer/auto-edit/cut-preview-lease";

const H = "a".repeat(64), root = "/private/tmp/TEST-body-contract";
function documents() {
  const runtime = { dockerPath: `${root}/docker`, dockerSha256: H, dockerSocketPath: `${root}/docker.sock`,
    dockerSocketDevice: "1", dockerSocketInode: "2", imageId: `sha256:${H}`, userId: "501:20",
    imageApprovalPath: `${root}/image.json`, imageApprovalSha256: H, runtimeRepoRoot: root };
  const references = Object.fromEntries(BODY_MEDIA_REFERENCES.map((name) => [name, { path: `${root}/${name}.json`, sha256: H }]));
  const input = parseGuidedBodyMediaInput({ schemaVersion: 1, kind: "guided-body-media-input", scope: "private-body-candidate-not-approval",
    profile: "held-source-float-own-screen-body-v1", requestId: randomUUID(), executionId: randomUUID(), references, runtime, selectedGraphicOrders: [0, 1] });
  const ref = { path: `${root}/body-media-input.json`, sha256: H };
  const activation = parseGuidedBodyExecutionActivation({ schemaVersion: 1, kind: "guided-body-execution-activation",
    scope: "private-body-owned-execution-not-approval", requestId: input.requestId, executionId: input.executionId,
    admissionClaimHash: H, beforeJournalHash: H, inputPath: ref.path, inputSha256: ref.sha256, outputRoot: `${root}/body-media-output`,
    clockHash: H, generationStartedAt: "2026-09-07T12:00:00.000Z", budgetAdmissionHash: H, budgetPrecommitHash: H,
    selectedGraphicOrders: [0, 1], runtime, createdAt: "2026-09-07T12:10:00.000Z" });
  return { input, activation, ref };
}

test("body execution documents are closed, complete all-row metadata and distinct from non-executable admission", () => {
  const { input, activation, ref } = documents();
  assert.doesNotThrow(() => assertBodyActivationInput(activation, input, ref));
  for (const patch of [{ executable: true }, { schemaVersion: 2 }, { profile: "legacy" }, { selectedGraphicOrders: [1] },
    { selectedGraphicOrders: [0, 2] }, { selectedGraphicOrders: [0, 0] }, { selectedGraphicOrders: Array.from({ length: 129 }, (_, i) => i) }]) {
    assert.throws(() => parseGuidedBodyMediaInput({ ...input, ...patch }));
  }
  for (const name of BODY_MEDIA_REFERENCES) {
    const references = { ...input.references } as Record<string, unknown>; delete references[name];
    assert.throws(() => parseGuidedBodyMediaInput({ ...input, references }));
  }
  for (const patch of [{ executable: true }, { kind: "guided-body-execution-claim" }, { createdAt: "2026-09-07T11:00:00.000Z" },
    { createdAt: "2026-09-07T12:10:00Z" }, { inputPath: `${root}/../elsewhere` }]) {
    assert.throws(() => parseGuidedBodyExecutionActivation({ ...activation, ...patch }));
  }
});

test("activation cannot replace original references, runtime, input SHA, ids or all-row orders", () => {
  const { input, activation, ref } = documents();
  for (const patch of [{ requestId: randomUUID() }, { executionId: randomUUID() }, { inputSha256: "b".repeat(64) },
    { admissionClaimHash: "b".repeat(64) }, { budgetAdmissionHash: "b".repeat(64) }, { budgetPrecommitHash: "b".repeat(64) },
    { runtime: { ...activation.runtime, dockerSocketInode: "3" } }, { selectedGraphicOrders: [0] }]) {
    assert.throws(() => assertBodyActivationInput({ ...activation, ...patch }, input, ref));
  }
});

test("actual durable admission hands off the same live lease and budget once; replay never executes a callback", async () => {
  const f = bodyClaimFixture(); let calls = 0, handoff: FreshBodyAdmission | undefined;
  try {
    const run = async (value: FreshBodyAdmission) => {
      handoff = value; calls += 1; cutPreviewLeaseGuard(f.dir, value.lease)();
      assert.ok(value.budget.remainingMs() < 55 * 60_000);
      consumeFreshBodyAdmission(value); assert.throws(() => consumeFreshBodyAdmission(value), /unused fresh/);
      return "TEST no media";
    };
    const first = await withFreshGuidedBodyAdmission({ dir: f.dir, submission: f.submission }, run, f.services);
    assert.equal(first.continuation, "TEST no media"); assert.equal(first.admission.executable, false);
    const before = readFileSync(f.base.jobPath);
    const repeat = await withFreshGuidedBodyAdmission({ dir: f.dir, submission: f.submission }, run, f.services);
    assert.equal(repeat.continuation, null); assert.equal(repeat.admission.replayed, true); assert.equal(calls, 1);
    assert.deepEqual(readFileSync(f.base.jobPath), before);
    assert.throws(() => cutPreviewLeaseGuard(f.dir, handoff!.lease));
  } finally { f.cleanup(); }
});

test("failed handoff is revoked and cannot reconstruct an activation; original admission result survives", async () => {
  const f = bodyClaimFixture(); let held: FreshBodyAdmission | undefined;
  try {
    await assert.rejects(withFreshGuidedBodyAdmission({ dir: f.dir, submission: f.submission }, async (value) => {
      held = value; throw new Error("TEST post-admission failure");
    }, f.services), /post-admission/);
    assert.throws(() => consumeFreshBodyAdmission(held!), /unused fresh/);
    assert.throws(() => consumeFreshBodyAdmission({ ...held! }), /unused fresh/);
    const value = JSON.parse(readFileSync(`${held!.operation.execution}/result.json`, "utf8"));
    assert.equal(value.status, "admission-fenced"); assert.equal(value.executable, false);
  } finally { f.cleanup(); }
});
