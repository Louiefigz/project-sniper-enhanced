import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { test } from "node:test";
import { parseOpeningCleanupResult, parseOpeningCleanupStdout } from "@/lib/producer/contracts/guided-opening-cleanup-v1";
import { parseGuidedHandoffPointerV2 } from "@/lib/producer/contracts/guided-workflow-v2";
import { assertCleanupOwnershipFresh, assertLegacyOpeningCleanup, assertOpeningCleanupIdentity, cleanupPointerAfterStop } from "../guided-opening-cleanup";

const HASH = "a".repeat(64), NAME = `sniper-render-${"b".repeat(32)}`;

test("legacy cleanup never downgrades a retained source-color request to graphics-only completion", () => {
  const original = { submission: { schemaVersion: 1 } } as Parameters<typeof assertLegacyOpeningCleanup>[0];
  assert.doesNotThrow(() => assertLegacyOpeningCleanup(original));
  const sourceColor = { submission: { schemaVersion: 2 } } as Parameters<typeof assertLegacyOpeningCleanup>[0];
  assert.throws(() => assertLegacyOpeningCleanup(sourceColor), /retain the full claim without graphics-only cleanup/);
});

function fixture() {
  const result = { schemaVersion: 1, kind: "guided-opening-cleanup-result", claimPath: "/private/tmp/TEST-ONLY/execution-claim.json",
    claimSha256: HASH, inputSha256: HASH, outputRoot: "/private/tmp/TEST-ONLY/media-output", executionId: randomUUID(), cleanupVerified: true,
    graphics: [{ order: 2, state: "reconciled-absence", containerNames: [NAME], reconciliation: [{ containerRef: NAME,
      canonicalAbsenceProved: true, method: "late-create-reconciliation" }], absence: [{ containerRef: NAME, canonicalAbsenceProved: true,
      method: "docker-force-remove-plus-exact-inspect-absence" }], cleanupVerified: true }], elapsedMs: 100,
    stages: [{ stage: "cleanup-claim-and-controls", status: "complete", elapsedMs: 10 },
      { stage: "reconcile-graphic-2", status: "complete", elapsedMs: 70 }, { stage: "cleanup-controls-after", status: "complete", elapsedMs: 10 }],
    budgetScope: "separate-protected-cleanup-not-render-allowance", processGroupStopped: "requires-owned-server-observation", openingApproved: false };
  return result;
}

test("cleanup schema is bounded exact resource metadata, never proof of actual invocation or media", () => {
  const value = fixture(); assert.deepEqual(parseOpeningCleanupResult(value), value);
  assert.deepEqual(parseOpeningCleanupStdout(`\n${JSON.stringify(value)}\n`), value);
  for (const patch of [{ approved: true }, { openingApproved: true }, { processGroupStopped: true }, { cleanupVerified: false },
    { elapsedMs: 300001 }, { elapsedMs: -1 }, { claimPath: "/private/tmp//claim" }, { executionId: "../outside" }, { status: "complete" }]) {
    assert.throws(() => parseOpeningCleanupResult({ ...value, ...patch }));
  }
  assert.throws(() => parseOpeningCleanupStdout(`${JSON.stringify(value)}\n${JSON.stringify(value)}`));
  assert.throws(() => parseOpeningCleanupStdout(`{"status":"done"}\n${JSON.stringify(value)}`));
  assert.throws(() => parseOpeningCleanupStdout(" ".repeat(128 * 1024 + 1)));
});

test("every selected resource needs exact same-name absence and complete phase coverage", () => {
  const value = fixture(), row = value.graphics[0];
  for (const patch of [{ containerNames: [] }, { containerNames: [NAME, NAME] }, { absence: [] },
    { absence: [{ ...row.absence[0], canonicalAbsenceProved: false }] },
    { absence: [{ ...row.absence[0], containerRef: `sniper-render-${"c".repeat(32)}` }] },
    { absence: [{ ...row.absence[0], method: "assumed-from-removal" }] },
    { reconciliation: [{ ...row.reconciliation[0], method: "docker-force-remove-plus-exact-inspect-absence" }] }, { order: 128 }]) {
    assert.throws(() => parseOpeningCleanupResult({ ...value, graphics: [{ ...row, ...patch }] }));
  }
  for (const stages of [value.stages.slice(1), [...value.stages].reverse(), value.stages.map((row) => ({ ...row, status: "failed" }))]) {
    assert.throws(() => parseOpeningCleanupResult({ ...value, stages }));
  }
  assert.deepEqual(parseOpeningCleanupResult({ ...value, graphics: [{ ...row, reconciliation: [] }] }).graphics[0].state, "reconciled-absence");
});

test("unarmed rows cannot hide registered names or unknown armed ledgers", () => {
  const value = fixture();
  for (const state of ["not-initialized", "initialized-unarmed"]) {
    const row = { order: 2, state, containerNames: [], cleanupVerified: true };
    assert.deepEqual(parseOpeningCleanupResult({ ...value, graphics: [row] }).graphics, [row]);
    assert.throws(() => parseOpeningCleanupResult({ ...value, graphics: [{ ...row, containerNames: [NAME] }] }));
    assert.throws(() => parseOpeningCleanupResult({ ...value, graphics: [{ ...row, reconciliation: [] }] }));
  }
  assert.throws(() => parseOpeningCleanupResult({ ...value, graphics: [{ order: 2, state: "unknown", containerNames: [], cleanupVerified: true }] }));
});

test("schema success cannot target another held claim or omit an exact claimed order", () => {
  const result = parseOpeningCleanupResult(fixture());
  const held = { claimHash: HASH, claimSha256: HASH, claimPath: result.claimPath,
    claim: { inputSha256: HASH, outputRoot: result.outputRoot, executionId: result.executionId, selectedGraphicOrders: [2] } };
  const typed = held as Parameters<typeof assertOpeningCleanupIdentity>[1];
  assert.doesNotThrow(() => assertOpeningCleanupIdentity(result, typed));
  for (const patch of [{ claimSha256: "b".repeat(64) }, { inputSha256: "b".repeat(64) }, { executionId: randomUUID() },
    { outputRoot: "/private/tmp/OTHER/media-output" }, { graphics: [] }]) {
    assert.throws(() => assertOpeningCleanupIdentity({ ...result, ...patch }, typed));
  }
});

test("cleanup pointer is historical resource-only metadata, never opening media or cut approval", () => {
  const base = { schemaVersion: 2, cutDecisionHash: HASH, cutActivationHash: HASH, pictureLockedRevisionHash: HASH };
  assert.throws(() => parseGuidedHandoffPointerV2({ ...base, openingCleanupHash: HASH }));
  const draft = { ...base, treatmentAdmissionHash: HASH, treatmentProposalHash: HASH, proposalReadinessHash: HASH, treatmentDraftRevisionHash: HASH };
  assert.deepEqual(parseGuidedHandoffPointerV2({ ...draft, openingCleanupHash: HASH }), { ...draft, openingCleanupHash: HASH });
  assert.throws(() => parseGuidedHandoffPointerV2({ ...draft, openingApproved: true }));
});

test("exact resource cleanup after a forced outer stop retains claim and outcome pointers; a normal return clears them", () => {
  const pointer = { schemaVersion: 2 as const, cutDecisionHash: HASH, cutActivationHash: HASH, pictureLockedRevisionHash: HASH,
    treatmentAdmissionHash: HASH, treatmentProposalHash: HASH, proposalReadinessHash: HASH, treatmentDraftRevisionHash: HASH,
    openingExecutionClaimHash: "b".repeat(64), openingProcessOutcomeHash: "c".repeat(64) };
  const forced = cleanupPointerAfterStop(pointer, "d".repeat(64), { receipt: { forcedStop: true } });
  assert.equal(forced.claimRetained, true);
  assert.equal(forced.pointer.openingExecutionClaimHash, "b".repeat(64)); assert.equal(forced.pointer.openingProcessOutcomeHash, "c".repeat(64));
  assert.equal(forced.pointer.openingCleanupHash, "d".repeat(64)); parseGuidedHandoffPointerV2(forced.pointer);
  const normal = cleanupPointerAfterStop(pointer, "d".repeat(64), { receipt: { forcedStop: false }, nestedOwnership: "resolved-by-normal-return" });
  assert.equal(normal.claimRetained, false); assert.equal("openingExecutionClaimHash" in normal.pointer, false);
  assert.equal("openingProcessOutcomeHash" in normal.pointer, false); parseGuidedHandoffPointerV2(normal.pointer);
  const unknownNested = cleanupPointerAfterStop(pointer, "d".repeat(64), { receipt: { forcedStop: false }, nestedOwnership: "unresolved-unknown-descendant" });
  assert.equal(unknownNested.claimRetained, true);
  const liveNested = cleanupPointerAfterStop(pointer, "d".repeat(64), { receipt: { forcedStop: false }, nestedOwnership: "unresolved-live-recorded-descendant" });
  assert.equal(liveNested.claimRetained, true); assert.equal("openingExecutionClaimHash" in liveNested.pointer, true);
  const unknown = cleanupPointerAfterStop(pointer, "d".repeat(64), { receipt: { forcedStop: "true" } });
  assert.equal(unknown.claimRetained, true); // Only explicit complete ownership observation permits removing the claim.
  assert.equal(cleanupPointerAfterStop(pointer, "d".repeat(64), { receipt: { forcedStop: false } }).claimRetained, true);
});

test("a resolved initial observation cannot clear ownership after either final CAS observation becomes uncertain", () => {
  const resolved = { receipt: { forcedStop: false }, nestedOwnership: "resolved-by-normal-return" };
  for (const nestedOwnership of ["unresolved-unknown-descendant", "unresolved-live-recorded-descendant", "unresolved-unrecorded-spawn", undefined, "bogus"]) {
    const uncertain = { receipt: { forcedStop: false }, nestedOwnership };
    assert.throws(() => assertCleanupOwnershipFresh(resolved, uncertain), /became unresolved/);
    assert.doesNotThrow(() => assertCleanupOwnershipFresh(uncertain, resolved)); // Retains the conservative initial policy.
  }
  assert.doesNotThrow(() => assertCleanupOwnershipFresh(resolved, resolved));
});
