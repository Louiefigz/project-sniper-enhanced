/** Actual held stop/result parsers and cleanup/readback routing over TEMP records. No source, worker or media qualification. */
import assert from "node:assert/strict";
import childProcess from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import test, { type TestContext } from "node:test";
import { canonicalJson, canonicalJsonSha256 } from "../auto-edit-hash";
import { writeGuidedObject } from "../guided-cut-v2-store";
import { readStoppedOpeningProcess } from "../guided-opening-process";
import { readHeldOpeningResult, assertOpeningReadbackIdentity, openingReadbackReceiptArguments } from "../guided-opening-result";
import { verifyCleanedOpeningMediaUnderLease } from "../guided-opening-readback";
import { openingCleanupStoreDependencies } from "../guided-opening-cleanup-store";
import { readFinalSourceColorCleanupForJournal } from "../guided-source-color-cleanup-final-read";
import { cleanupFinalReadFixture } from "./_guided-source-color-cleanup-final-read-fixture";
import { openingProcessFixture } from "./_guided-opening-process-fixture";

const HASH = "a".repeat(64), REFUSAL = /source-color.*schema.?2.*not implemented/i;

/** Publish opaque TEST receipt bytes: success below proves only the actual completion/byte protocol, not media content. */
function resultFixture(t: TestContext, processVersion: number, completionVersion = 1) {
  const f = openingProcessFixture({ status: "complete", error: "" }, processVersion); t.after(f.cleanup);
  f.held.claimSha256 = HASH; f.held.claim.executionInputHash = HASH;
  const directory = f.held.claim.outputRoot;
  assert(directory.startsWith(f.root + path.sep)); assert.equal(fs.realpathSync(f.root), f.root);
  fs.mkdirSync(directory, { mode: 0o700 });
  const body = { schemaVersion: 1, kind: "guided-opening-media-result", TEST: "opaque receipt, not media evidence" };
  const record = { ...body, receiptHash: canonicalJsonSha256(body) }, file = path.join(directory, "media-result.json");
  fs.writeFileSync(file, canonicalJson(record), { flag: "wx", mode: 0o600 });
  const completion = { schemaVersion: completionVersion, kind: "guided-opening-media-completion", status: "complete",
    executionId: f.held.claim.executionId, inputSha256: HASH, executionInputHash: HASH, executionClaimSha256: HASH,
    receiptPath: file, receiptSha256: canonicalJsonSha256(record), receiptHash: record.receiptHash,
    openingApproved: false, deliveryApproved: false };
  f.outcome.stdout = JSON.stringify(completion); f.activation.outcomeSha256 = canonicalJsonSha256(f.outcome);
  f.held.job.guidedHandoffV2!.openingProcessOutcomeHash = writeGuidedObject(f.held.job.ctx.dir, f.activation); f.write();
  return { ...f, completion };
}

/** This is schema-only readback text, never a fake native invocation result. */
function readback(completion: ReturnType<typeof resultFixture>["completion"]) {
  const { executionClaimSha256, ...base } = completion;
  const stages = ["held-result", "held-claim", "current-input-and-sources", "exact-profile-and-frames", "current-code-and-tools",
    "held-whole-master-and-excerpts", "exact-graphic-artifacts", "actual-range-media-readback", "final-source-result-recheck"];
  return JSON.stringify({ ...base, kind: "guided-opening-media-readback", status: "verified",
    scope: "exact-held-private-media-not-opening-or-delivery-approval", claimSha256: executionClaimSha256, elapsedMs: 100,
    stages: stages.map(stage => ({ stage, status: "complete", elapsedMs: 1 })),
    processGroupAndDockerCleanup: "requires-separate-owned-server-observation",
    currentJournalAndLease: "requires-separate-owned-server-observation" });
}

for (const version of [1, 2]) test(`legacy V${version} stopped process retains its unchanged schema1 byte/readback path`, t => {
  const f = resultFixture(t, version), result = readHeldOpeningResult(f.held);
  assert.deepEqual(result.completion, f.completion); assert.equal(result.sourceBytesObserved, false);
  assert.equal(result.mediaBytesObserved, false); assert.equal(result.mediaSelected, false);
  assert.deepEqual(openingReadbackReceiptArguments(result), ["--receipt-sha256", f.completion.receiptSha256, "--receipt-hash", f.completion.receiptHash]);
  assert.equal(assertOpeningReadbackIdentity(readback(f.completion), { held: f.held, selected: result }).openingApproved, false);
});

for (const version of [1, 2]) test(`actual V3 source-color process cannot borrow schema${version} completion`, t => {
  const f = resultFixture(t, 3, version), stopped = readStoppedOpeningProcess(f.held);
  assert.equal(stopped.receipt.schemaVersion, 3); assert(stopped.sourceColor);
  assert.throws(() => readHeldOpeningResult(f.held), REFUSAL);
});

for (const version of [1, 2]) test(`legacy V${version} process still rejects newer completion schema2`, t => {
  const f = resultFixture(t, version, 2); assert.throws(() => readHeldOpeningResult(f.held), /not private unapproved evidence/);
});

test("retained result substitution cannot route V3 through readback argv or schema1 identity validation", t => {
  const legacy = resultFixture(t, 2), color = resultFixture(t, 3), selected = readHeldOpeningResult(legacy.held);
  selected.process = readStoppedOpeningProcess(color.held);
  assert.throws(() => openingReadbackReceiptArguments(selected), REFUSAL);
  assert.throws(() => assertOpeningReadbackIdentity(readback(legacy.completion), { held: color.held, selected }), REFUSAL);
});

test("actual final source-color cleanup refuses readback before tools, attempt publication or native spawn", async t => {
  const f = await cleanupFinalReadFixture(t); let reads = 0, spawns = 0;
  t.mock.method(openingCleanupStoreDependencies, "final", (input: Parameters<typeof readFinalSourceColorCleanupForJournal>[0]) => {
    reads++; return readFinalSourceColorCleanupForJournal(input, f.readDependencies);
  });
  t.mock.method(childProcess, "spawn", () => { spawns++; throw new Error("TEST forbidden native spawn"); });
  const attempts = path.join(path.dirname(f.input.held.claimPath), "readback-attempts"); assert(!fs.existsSync(attempts));
  await assert.rejects(verifyCleanedOpeningMediaUnderLease({ dir: f.readInput.dir, lease: f.projectLease,
    expectedCleanupHash: f.committed.cleanupHash, remainingMs: () => 30_000 }), REFUSAL);
  assert.equal(reads, 1); assert.equal(spawns, 0); assert.equal(f.calls.length, 1); assert(!fs.existsSync(attempts));
});
