import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { test } from "node:test";
import { parseGuidedOpeningExecutionClaim, parseOpeningRuntimeControl } from "@/lib/producer/contracts/guided-opening-claim-v1";
import { parseGuidedHandoffPointerV2 } from "@/lib/producer/contracts/guided-workflow-v2";

const HASH = "a".repeat(64);
function claim() {
  const requestId = randomUUID(), executionId = randomUUID();
  const root = `/private/tmp/TEST-ONLY/producer/guided-v2-operations/${requestId}/executions/${executionId}`;
  return { schemaVersion: 1, kind: "guided-opening-execution-claim", scope: "private-opening-owned-execution-not-approval",
    requestId, executionId, beforeJournalHash: HASH, inputPath: `${root}/media-input/input.json`, inputSha256: HASH,
    executionInputHash: HASH, outputRoot: `${root}/media-output`, clockHash: HASH, generationStartedAt: "2026-09-06T12:00:00.000Z",
    budgetAdmissionHash: HASH, selectedGraphicOrders: [0, 2], runtime: { dockerPath: "/private/tmp/TEST-ONLY/docker", dockerSha256: HASH,
      dockerSocketPath: "/private/tmp/TEST-ONLY/docker.sock", dockerSocketDevice: "1", dockerSocketInode: "2", imageId: `sha256:${HASH}`,
      userId: "1000:1000", imageApprovalPath: "/private/tmp/TEST-ONLY/pinned/render_image_approval.json", imageApprovalSha256: HASH,
      runtimeRepoRoot: "/private/tmp/TEST-ONLY/repo" } };
}

test("opening claim is closed exact ownership metadata, never absence, media or approval", () => {
  const value = claim(); assert.deepEqual(parseGuidedOpeningExecutionClaim(value), value);
  for (const patch of [{ approved: true }, { resourceAbsence: "proved" }, { scope: "delivery" }, { requestId: "../../outside" },
    { executionId: false }, { inputSha256: "" }, { generationStartedAt: "2026-09-06" }, { outputRoot: "/private/tmp//outside" }]) {
    assert.throws(() => parseGuidedOpeningExecutionClaim({ ...value, ...patch }));
  }
  for (const orders of [[2, 0], [0, 0], [-1], [0.5], [128], [true], Array.from({ length: 9 }, (_, index) => index)]) {
    assert.throws(() => parseGuidedOpeningExecutionClaim({ ...value, selectedGraphicOrders: orders }));
  }
  assert.deepEqual(parseGuidedOpeningExecutionClaim({ ...value, selectedGraphicOrders: [] }).selectedGraphicOrders, []);
});

test("held runtime controls cannot select a tag/root user/path alias or claim success", () => {
  const value = claim().runtime; assert.deepEqual(parseOpeningRuntimeControl(value), value);
  for (const patch of [{ imageId: "latest" }, { userId: "0:0" }, { dockerPath: "/usr/bin/../bin/docker" },
    { dockerSocketInode: 3 }, { dockerSocketDevice: "01" }, { dockerSocketInode: "-1" }, { dockerSha256: "changed" },
    { imageApprovalSha256: "" }, { runtimeRepoRoot: "/" }, { containersRemoved: true }]) {
    assert.throws(() => parseOpeningRuntimeControl({ ...value, ...patch }));
  }
});

test("durable pointer accepts ownership only after an actual draft and preserves unsupported receipt identity", () => {
  const base = { schemaVersion: 2, cutDecisionHash: HASH, cutActivationHash: HASH, pictureLockedRevisionHash: HASH };
  assert.throws(() => parseGuidedHandoffPointerV2({ ...base, openingExecutionClaimHash: HASH }), /exact isolated treatment draft/);
  const ready = { ...base, treatmentAdmissionHash: HASH, treatmentProposalHash: HASH, proposalReadinessHash: HASH,
    treatmentDraftRevisionHash: HASH, openingPreparationHash: HASH };
  assert.deepEqual(parseGuidedHandoffPointerV2(ready), ready);
  assert.deepEqual(parseGuidedHandoffPointerV2({ ...ready, openingExecutionClaimHash: HASH }), { ...ready, openingExecutionClaimHash: HASH });
  assert.throws(() => parseGuidedHandoffPointerV2({ ...ready, openingExecutionClaimHash: "../../outside" }));
  assert.throws(() => parseGuidedHandoffPointerV2({ ...ready, openingApproved: true }));
});
