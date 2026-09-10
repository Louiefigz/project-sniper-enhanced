/** Inert real-file request history and code pins only; no renderer, controller, provider or source admission. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { parsePrepareGuidedOpening } from "@/lib/producer/contracts/guided-opening-v1";
import { canonicalJson, canonicalJsonSha256 } from "../auto-edit-hash";
import { createOpeningLaunchRecord, readOpeningLaunchIntent, openingControllerFiles } from "../guided-opening-launch-store";
import { assertOpeningSubmission } from "../guided-opening-authority";
import { guidedOperation, readGuidedExecution } from "../guided-cut-v2-store";
import { writeGuidedOpeningMediaInput } from "../guided-opening-media-input";
import { claimGuidedOpeningExecution } from "../guided-opening-claim";
import { acquireProjectMutationLease } from "../project-mutation-lease";
import { sourceColorIntentFixture, replaceIntentFixtureFile, rawSha,
  LEGACY_CONTROLLER_NAMES, SOURCE_COLOR_CONTROLLER_NAMES } from "./_guided-opening-source-color-intent-fixture";

test("V2 intent retains the exact full declaration and raw bytes; identical publication remains exclusive", t => {
  const f = sourceColorIntentFixture(t), value = f.intent(), root = f.launchRoot();
  const hash = createOpeningLaunchRecord(root, "intent.json", value), bytes = fs.readFileSync(path.join(root, "intent.json"));
  const held = readOpeningLaunchIntent(f.root, f.current.expectedJournalHash)!;
  assert.equal(held.hash, hash); assert.equal(hash, rawSha(bytes)); assert.deepEqual(held.intent, value);
  assert.equal(held.intent.schemaVersion, 2); assert.equal(held.intent.submission.schemaVersion, 2);
  assert.equal(canonicalJsonSha256(held.intent.submission), canonicalJsonSha256(f.current));
  assert.throws(() => createOpeningLaunchRecord(root, "intent.json", value), { code: "EEXIST" });
  assert.deepEqual(fs.readFileSync(path.join(root, "intent.json")), bytes);
  assert.deepEqual(fs.readdirSync(root), ["intent.json"]);
});

test("legacy intent preserves exact five-file closure and its closed V1 request parser", t => {
  const f = sourceColorIntentFixture(t), value = f.intent(1);
  createOpeningLaunchRecord(f.launchRoot(), "intent.json", value);
  const held = readOpeningLaunchIntent(f.root, f.legacy.expectedJournalHash)!;
  assert.deepEqual(held.intent, value); assert.equal(held.intent.controllerFiles.length, 5);
  assert.throws(() => parsePrepareGuidedOpening(f.current));
});

test("intent and request versions cannot cross-label source declarations or downgrade the required pins", t => {
  for (const kind of ["intent1", "request1", "pins1", "extra", "unknown", "boolean", "missing-selection"]) {
    const f = sourceColorIntentFixture(t), value: Record<string, unknown> = f.intent();
    if (kind === "intent1") value.schemaVersion = 1;
    if (kind === "request1") value.submission = f.legacy;
    if (kind === "pins1") value.controllerFiles = f.intent(1).controllerFiles;
    if (kind === "extra") value.approved = true;
    if (kind === "unknown") value.schemaVersion = 3;
    if (kind === "boolean") value.schemaVersion = true;
    if (kind === "missing-selection") value.submission = { ...f.legacy, schemaVersion: 2 };
    createOpeningLaunchRecord(f.launchRoot(), "intent.json", value);
    assert.throws(() => readOpeningLaunchIntent(f.root, f.current.expectedJournalHash));
  }
});

test("V2 controller closure requires every exact current pin; V1 remains five", t => {
  const f = sourceColorIntentFixture(t, true), old = openingControllerFiles(f.proposal), current = openingControllerFiles(f.proposal, 2);
  assert.deepEqual(old.map(row => row.path), LEGACY_CONTROLLER_NAMES);
  assert.deepEqual(current.map(row => row.path), SOURCE_COLOR_CONTROLLER_NAMES);
  assert.equal(current.length, new Set(SOURCE_COLOR_CONTROLLER_NAMES).size); assert(current.length > 28);
  assert(current.every(row => row.sha256 === f.pipeline!.files.find(file => file.path === row.path)!.hash));
  assert.throws(() => openingControllerFiles(f.proposal, 3 as 2), /Unsupported/);
});

test("missing new pin or changed pinned bytes rejects without borrowing or mutating current code", t => {
  const f = sourceColorIntentFixture(t, true), name = "src/lib/server/generation-clock-history.ts";
  const index = f.pipeline!.files.findIndex(row => row.path === name), removed = f.pipeline!.files.splice(index, 1)[0];
  assert.throws(() => openingControllerFiles(f.proposal, 2), /predates required/);
  assert.equal(openingControllerFiles(f.proposal).length, 5); f.pipeline!.files.splice(index, 0, removed);
  const pinned = path.join(f.pipeline!.snapshotRoot, name), actual = fs.readFileSync(path.join(process.cwd(), name));
  replaceIntentFixtureFile(f.root, pinned, "// TEST-only changed captured bytes\n");
  assert.throws(() => openingControllerFiles(f.proposal, 2), /differs from pinned/);
  removed.hash = rawSha(fs.readFileSync(pinned));
  assert.throws(() => openingControllerFiles(f.proposal, 2), /differs from pinned/);
  assert.deepEqual(fs.readFileSync(path.join(process.cwd(), name)), actual);
});

test("shared submission bindings remain exact for V2 without granting source-color authority", t => {
  const f = sourceColorIntentFixture(t); assert.doesNotThrow(() => assertOpeningSubmission(f.proposal, f.current));
  assert.doesNotThrow(() => assertOpeningSubmission(f.proposal, f.legacy));
  for (const field of ["expectedToken", "expectedJournalHash", "proposalReadinessHash", "treatmentDraftRevisionHash"] as const) {
    assert.throws(() => assertOpeningSubmission(f.proposal, { ...f.current, [field]: "f".repeat(64) }), /stale or blocked/);
  }
});

test("real immutable operation history hashes the full V2 request and exact replay retains first intake", t => {
  const f = sourceColorIntentFixture(t), input = { dir: f.root, id: f.current.idempotencyKey, submission: f.current, receivedAt: f.receivedAt };
  const first = guidedOperation(input), file = path.join(first.directory, "submission.json"), bytes = fs.readFileSync(file);
  const startPath = path.join(first.execution, "start.json"), start = readGuidedExecution({ dir: f.root, id: input.id,
    executionId: first.executionId, hash: rawSha(fs.readFileSync(startPath)) });
  assert.equal(start.submissionHash, canonicalJsonSha256(f.current));
  assert.notEqual(start.submissionHash, canonicalJsonSha256(f.legacy));
  const replay = guidedOperation(input); assert.deepEqual(replay.record, first.record); assert.notEqual(replay.executionId, first.executionId);
  assert.deepEqual(fs.readFileSync(file), bytes);
  const changed = structuredClone(f.current); changed.sourceColor.declarations["test-source"].declaration.lightingGroups[0].description += " changed";
  const executions = fs.readdirSync(path.dirname(first.execution));
  assert.throws(() => guidedOperation({ ...input, submission: changed }), /conflicts with retained full request/);
  assert.deepEqual(fs.readdirSync(path.dirname(first.execution)), executions); assert.deepEqual(fs.readFileSync(file), bytes);
});

test("rehashing changed raw intake declarations cannot satisfy an original execution start", t => {
  const f = sourceColorIntentFixture(t), operation = guidedOperation({ dir: f.root, id: f.current.idempotencyKey,
    submission: f.current, receivedAt: f.receivedAt });
  const file = path.join(operation.directory, "submission.json"), changed = structuredClone(operation.record);
  const request = changed.submission as typeof f.current; request.sourceColor.declarations["test-source"].declaration.cameraProfile = "TEST new explicit camera";
  changed.submissionHash = canonicalJsonSha256(request); replaceIntentFixtureFile(f.root, file, canonicalJson(changed));
  const start = path.join(operation.execution, "start.json");
  assert.throws(() => readGuidedExecution({ dir: f.root, id: f.current.idempotencyKey, executionId: operation.executionId,
    hash: rawSha(fs.readFileSync(start)) }), /start\/intake changed/);
});

test("input and claim boundaries reject changed in-memory V2 declarations before any media document or claim write", t => {
  const f = sourceColorIntentFixture(t), operation = guidedOperation({ dir: f.root, id: f.current.idempotencyKey,
    submission: f.current, receivedAt: f.receivedAt });
  const acquired = acquireProjectMutationLease(f.root, "TEST source-color request mismatch only"); assert(acquired.lease);
  try {
    const request = operation.record.submission as typeof f.current;
    request.sourceColor.declarations["test-source"].declaration.lightingGroups[0].description += " changed";
    const common = { proposal: f.proposal, operation, lease: acquired.lease, remainingMs: () => 1 };
    assert.throws(() => writeGuidedOpeningMediaInput(common), /entire retained prepare request/);
    // Deliberately incomplete invocation: the request mismatch must reject before any invocation/runtime admission.
    assert.throws(() => claimGuidedOpeningExecution({ ...common, invocation: {} as ReturnType<typeof writeGuidedOpeningMediaInput>,
      budgetAdmissionHash: "a".repeat(64) }), /entire retained prepare request/);
    assert.equal(fs.existsSync(path.join(operation.execution, "media-input")), false);
    assert.equal(fs.existsSync(path.join(operation.execution, "execution-claim.json")), false);
  } finally { acquired.lease.release(); }
});
