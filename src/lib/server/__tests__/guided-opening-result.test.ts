import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { test } from "node:test";
import { parseOpeningMediaCompletion, parseOpeningMediaReadback } from "@/lib/producer/contracts/guided-opening-result-v1";

const HASH = "a".repeat(64);
function completion() {
  return { schemaVersion: 1, kind: "guided-opening-media-completion", status: "complete", executionId: randomUUID(),
    inputSha256: HASH, executionInputHash: HASH, executionClaimSha256: HASH, receiptPath: "/private/tmp/TEST-only/media-output/media-result.json",
    receiptSha256: HASH, receiptHash: HASH, openingApproved: false, deliveryApproved: false };
}
function readback() {
  const { executionClaimSha256: _claim, ...base } = completion(); void _claim;
  const stages = ["held-result", "held-claim", "current-input-and-sources", "exact-profile-and-frames", "current-code-and-tools",
    "held-whole-master-and-excerpts", "exact-graphic-artifacts", "actual-range-media-readback", "final-source-result-recheck"];
  return { ...base, kind: "guided-opening-media-readback", status: "verified", scope: "exact-held-private-media-not-opening-or-delivery-approval",
    claimSha256: HASH, elapsedMs: 100, stages: stages.map((stage) => ({ stage, status: "complete", elapsedMs: 10 })),
    processGroupAndDockerCleanup: "requires-separate-owned-server-observation", currentJournalAndLease: "requires-separate-owned-server-observation" };
}

test("completion schemas accept only one closed actual-protocol object; these fixtures assert no invocation or media success", () => {
  const value = completion(); assert.deepEqual(parseOpeningMediaCompletion(JSON.stringify(value)), value);
  for (const output of [`${JSON.stringify(value)}\n${JSON.stringify(value)}`, `{"status":"done"}\n${JSON.stringify(value)}`,
    JSON.stringify([value]), "null", `${JSON.stringify(value)}\u0000`, " ".repeat(128 * 1024 + 1)]) {
    assert.throws(() => parseOpeningMediaCompletion(output));
  }
  for (const patch of [{ status: "verified" }, { openingApproved: true }, { finalApproved: false }, { executionId: "../outside" },
    { executionClaimSha256: null }, { receiptPath: "/private/tmp//outside" }, { schemaVersion: 2 }]) {
    assert.throws(() => parseOpeningMediaCompletion(JSON.stringify({ ...value, ...patch })));
  }
});

test("readback never absorbs separate process/daemon/journal/lease authority and requires every completed stage", () => {
  const value = readback(); assert.deepEqual(parseOpeningMediaReadback(JSON.stringify(value)), value);
  for (const patch of [{ processGroupAndDockerCleanup: "verified" }, { currentJournalAndLease: true }, { deliveryApproved: true },
    { claimSha256: "" }, { elapsedMs: -1 }, { elapsedMs: 1500001 }, { sourceApproved: true },
    { stages: value.stages.slice(1) }, { stages: [...value.stages].reverse() },
    { stages: value.stages.map((row) => ({ ...row, status: "failed" })) },
    { stages: value.stages.map((row) => ({ ...row, elapsedMs: 101 })) },
    { stages: value.stages.map((row) => ({ ...row, skipped: false })) }]) {
    assert.throws(() => parseOpeningMediaReadback(JSON.stringify({ ...value, ...patch })));
  }
  assert.throws(() => parseOpeningMediaReadback(`${JSON.stringify(value)}\n{"status":"done"}`));
  assert.throws(() => parseOpeningMediaReadback(JSON.stringify(completion())));
});
