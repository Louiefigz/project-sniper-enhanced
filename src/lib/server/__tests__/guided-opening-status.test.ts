import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { test } from "node:test";
import { readGuidedOpeningStatus, guidedOpeningStatusReads } from "../guided-opening-status";
import { parseGuidedOpeningStatus } from "@/lib/producer/guided-opening-client";

function reads() {
  const job = { sha256: "a".repeat(64), job: { ctx: { workflowV2: { schemaVersion: 2, mode: "guided", afterCut: "treatment-then-intro", approvalPolicy: "explicit-human" } }, guidedHandoffV2: {} } };
  const held = { ...job, claimHash: "b".repeat(64), claim: { requestId: randomUUID(), executionId: randomUUID(), generationStartedAt: "2026-09-06T12:00:00.000Z" } };
  const state = { job: () => job, claim: () => held, stopped: () => { throw new Error("missing stop"); }, cleanup: () => { throw new Error("not committed"); } };
  return { job, held, state: state as unknown as typeof guidedOpeningStatusReads };
}

test("unqualified status never supplies ready media or claims a live process from an unfinished ownership record", () => {
  const f = reads(), first = readGuidedOpeningStatus("TEST", f.state);
  assert.equal(first.state, "unavailable"); assert.equal(first.timing.elapsedStatus, "unavailable"); assert.equal("media" in first, false);
  Object.assign(f.job.job.guidedHandoffV2, { openingExecutionClaimHash: f.held.claimHash });
  const unknown = readGuidedOpeningStatus("TEST", f.state);
  assert.equal(unknown.state, "pending-owned-execution"); assert.match(unknown.detail, /does not prove the worker is running or stopped/);
  assert.equal(unknown.timing.engineElapsedMs, null); assert.equal(unknown.openingApproved, false);
});

test("actual ended interval is labelled completed timing, not final or media approval", () => {
  const f = reads(); Object.assign(f.job.job.guidedHandoffV2, { openingExecutionClaimHash: f.held.claimHash });
  f.state.stopped = (() => ({ receipt: { status: "failed", elapsedMs: 1234, forcedStop: false }, nestedOwnership: "resolved-by-normal-return" })) as unknown as typeof f.state.stopped;
  const observed = readGuidedOpeningStatus("TEST", f.state);
  assert.equal(observed.state, "pending-cleanup"); assert.equal(observed.timing.engineElapsedMs, 1234);
  assert.equal(observed.timing.cleanupElapsedMs, null); assert.equal(observed.timing.elapsedStatus, "completed");
  assert.equal(observed.deliveryApproved, false); assert.equal("media" in observed, false);
});

test("legacy/unknown workflow and an unchanged-token journal race fail status observation", () => {
  const f = reads(); Object.assign(f.job.job.ctx, { workflowV2: undefined });
  assert.throws(() => readGuidedOpeningStatus("TEST", f.state));
  const fresh = reads(); let count = 0;
  fresh.state.job = (() => ({ ...fresh.job, sha256: count++ ? "c".repeat(64) : fresh.job.sha256 })) as unknown as typeof fresh.state.job;
  assert.throws(() => readGuidedOpeningStatus("TEST", fresh.state), /changed during observation/);
});

test("a newer unresolved claim always wins over historical cleanup, without reading or selecting its old media", () => {
  const f = reads(); let cleanupReads = 0, pendingReads = 0;
  Object.assign(f.job.job.guidedHandoffV2, { openingExecutionClaimHash: f.held.claimHash, openingCleanupHash: "d".repeat(64) });
  f.state.cleanup = (() => { cleanupReads += 1; throw new Error("Old cleanup must not be consulted"); }) as typeof f.state.cleanup;
  f.state.pendingCleanup = () => { pendingReads++; throw new Error("Prepared cleanup must not be consulted for a valid current claim"); };
  const unknown = readGuidedOpeningStatus("TEST", f.state);
  assert.equal(unknown.state, "pending-owned-execution"); assert.equal(cleanupReads, 0); assert.equal(pendingReads, 0); assert.equal("media" in unknown, false);
  f.state.stopped = (() => ({ receipt: { status: "complete", elapsedMs: 321, forcedStop: false }, nestedOwnership: "resolved-by-normal-return" })) as unknown as typeof f.state.stopped;
  const stopped = readGuidedOpeningStatus("TEST", f.state);
  assert.equal(stopped.state, "pending-cleanup"); assert.equal(cleanupReads, 0); assert.equal(pendingReads, 0); assert.equal("media" in stopped, false);
});

test("an unobservable recorded child keeps status unresolved (unknown is not absent) and the parser accepts it", () => {
  const f = reads(); Object.assign(f.job.job.guidedHandoffV2, { openingExecutionClaimHash: f.held.claimHash });
  f.state.stopped = (() => ({ receipt: { status: "failed", elapsedMs: 700, forcedStop: false }, nestedOwnership: "unresolved-unknown-descendant",
    liveDescendants: [], unknownDescendants: [{ pid: 4343, argv0: "/TEST/docker", reason: "ps timed out" }], unrecordedSpawns: [] })) as unknown as typeof f.state.stopped;
  const unknown = readGuidedOpeningStatus("TEST", f.state);
  assert.equal(unknown.state, "pending-owned-execution"); assert.match(unknown.detail, /could not be observed/); assert.match(unknown.detail, /pid 4343/);
  assert.deepEqual(parseGuidedOpeningStatus(JSON.parse(JSON.stringify(unknown)), "TEST"), unknown);
});

test("a live recorded nested process keeps status unresolved with the exact pid, and the browser parser accepts it", () => {
  const f = reads(); Object.assign(f.job.job.guidedHandoffV2, { openingExecutionClaimHash: f.held.claimHash });
  f.state.stopped = (() => ({ receipt: { status: "failed", elapsedMs: 700, forcedStop: false }, nestedOwnership: "unresolved-live-recorded-descendant",
    liveDescendants: [{ pid: 4242, argv0: "/TEST/ffprobe", recordedAt: 0 }] })) as unknown as typeof f.state.stopped;
  const live = readGuidedOpeningStatus("TEST", f.state);
  assert.equal(live.state, "pending-owned-execution"); assert.match(live.detail, /pid 4242 \/TEST\/ffprobe/); assert.match(live.detail, /manual resolution/);
  assert.deepEqual(parseGuidedOpeningStatus(JSON.parse(JSON.stringify(live)), "TEST"), live);
});

test("a forced outer stop never advances toward cleanup selection; ownership stays explicitly unresolved", () => {
  const f = reads(); Object.assign(f.job.job.guidedHandoffV2, { openingExecutionClaimHash: f.held.claimHash });
  f.state.stopped = (() => ({ receipt: { status: "failed", elapsedMs: 900, forcedStop: true } })) as unknown as typeof f.state.stopped;
  const forced = readGuidedOpeningStatus("TEST", f.state);
  assert.equal(forced.state, "pending-owned-execution"); assert.match(forced.detail, /force-stopped/); assert.match(forced.detail, /manual resolution/);
  assert.equal(forced.timing.engineElapsedMs, 900); assert.equal("media" in forced, false);
  // The browser parser must accept exactly what the server emits, or the recovery message is hidden behind a parse error.
  assert.deepEqual(parseGuidedOpeningStatus(JSON.parse(JSON.stringify(forced)), "TEST"), forced);
  const unresolvedAfterCleanup = { ...forced, timing: { ...forced.timing, cleanupElapsedMs: 5 } };
  assert.throws(() => parseGuidedOpeningStatus(unresolvedAfterCleanup, "TEST"), /recorded stopped attempt/);
});
