/** CLI transport only; fake service result is never native, retirement or media qualification. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { test, type TestContext } from "node:test";
import { executeOpeningCommand, openingCommandServices, readOpeningCleanupCommandRequest }
  from "../../../../scripts/producer/guided-opening";
import { parseRecoverGuidedOpeningCleanup } from "../../producer/contracts/guided-opening-v1";

const request = { schemaVersion: 1, operation: "recover-guided-opening-cleanup", expectedToken: "TEST-cleanup",
  expectedJournalHash: "a".repeat(64), claimHash: "b".repeat(64) };

function fixture(t: TestContext) {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "sniper cleanup command TEST ")));
  t.after(() => fs.rmSync(root, { recursive: true }));
  const file = path.join(root, "request's.json"); fs.writeFileSync(file, JSON.stringify(request), { flag: "wx", mode: 0o600 });
  const calls: string[] = [], inputs: Parameters<typeof openingCommandServices.recoverCleanup>[0][] = [];
  const clock = openingCommandServices.cleanupClock();
  const result = { cleanupHash: "c".repeat(64), journalHash: "d".repeat(64), claimHash: request.claimHash,
    executionId: "00000000-0000-4000-8000-000000000001", claimRetained: false as const, resourceCleanup: "verified" as const,
    mediaSelected: false as const, openingApproved: false as const, deliveryApproved: false as const };
  const services = { ...openingCommandServices,
    canonicalDir: (dir: unknown) => { assert.equal(typeof dir, "string"); calls.push("canonical"); return dir as string; },
    cleanupClock: () => { calls.push("clock"); return clock; },
    recoverCleanup: async (input: typeof inputs[number]) => { calls.push("recover"); inputs.push(input); return result; },
    launch: async () => { throw new Error("TEST recovery must not launch"); },
    approve: async () => { throw new Error("TEST recovery must not approve"); },
  };
  return { root, file, clock, calls, inputs, services, result };
}

test("closed recovery request preserves exact checkpoint and rejects every extra authority field", () => {
  assert.deepEqual(parseRecoverGuidedOpeningCleanup(request), request);
  for (const key of ["deadlineMs", "remainingMs", "clock", "retry", "force", "idempotencyKey", "cleanupSucceeded",
    "groupStopped", "resourcePath", "openingApproved", "deliveryApproved", "sourceColor", "schemaVersion2"]) {
    assert.throws(() => parseRecoverGuidedOpeningCleanup({ ...request, [key]: true }));
  }
  for (const [key, value] of [["schemaVersion", 2], ["operation", "prepare-guided-opening"], ["expectedToken", ""],
    ["expectedJournalHash", "a"], ["claimHash", "B".repeat(64)]]) {
    assert.throws(() => parseRecoverGuidedOpeningCleanup({ ...request, [key]: value }));
  }
});

test("explicit recovery uses one original clock before canonicalization and request file parsing", async t => {
  const f = fixture(t), result = await executeOpeningCommand(["recover-cleanup", f.root, f.file], f.services);
  assert.deepEqual(f.calls, ["clock", "canonical", "recover"]); assert.equal(f.inputs.length, 1);
  assert.deepEqual(f.inputs[0], { dir: f.root, expectedToken: request.expectedToken,
    expectedJournalHash: request.expectedJournalHash, expectedClaimHash: request.claimHash, clock: f.clock });
  assert.equal(f.inputs[0].clock, f.clock); assert.equal(result, f.result);
  assert.equal(result.openingApproved, false); assert.equal(result.deliveryApproved, false);
});

test("ambiguous recovery never retries, falls back to native cleanup, refreshes a request or reports success", async t => {
  const f = fixture(t), original = fs.readFileSync(f.file);
  f.services.recoverCleanup = async () => { f.calls.push("recover"); throw new Error("TEST retained uncertain recovery"); };
  await assert.rejects(executeOpeningCommand(["recover-cleanup", f.root, f.file], f.services), /retained uncertain/);
  assert.deepEqual(f.calls, ["clock", "canonical", "recover"]); assert.deepEqual(fs.readFileSync(f.file), original);
});

test("invalid recovery grammar/help never create a clock or touch any project", async t => {
  const f = fixture(t);
  for (const args of [["recover-cleanup", f.root], ["cleanup-status", f.root, f.file],
    ["recover-cleanup", f.root, f.file, "--force"], ["cleanup-status"], ["recover-cleanup"]]) {
    await assert.rejects(executeOpeningCommand(args, f.services));
  }
  const help = await executeOpeningCommand(["--help"], f.services);
  assert.match(JSON.stringify(help), /recover-cleanup/); assert.match(JSON.stringify(help), /never retries/);
  assert.deepEqual(f.calls, []);
});

test("malformed recovery bytes are bounded and no-follow with no service call", async t => {
  const f = fixture(t), alias = path.join(f.root, "alias.json"); fs.symlinkSync(f.file, alias);
  for (const file of [alias, f.root, path.join(f.root, "missing.json")]) assert.throws(() => readOpeningCleanupCommandRequest(file));
  for (const bytes of [Buffer.from([0xff]), Buffer.alloc(16_385, 32), Buffer.from("{}"), Buffer.from(""),
    Buffer.from(JSON.stringify({ ...request, openingApproved: true }))]) {
    fs.writeFileSync(f.file, bytes);
    await assert.rejects(executeOpeningCommand(["recover-cleanup", f.root, f.file], f.services));
  }
  assert.equal(f.inputs.length, 0); assert(!f.calls.includes("recover"));
});

test("request parse does not mutate or manufacture identity from the current project", async t => {
  const f = fixture(t);
  const missing = { ...request } as Record<string, unknown>; delete missing.expectedJournalHash;
  fs.writeFileSync(f.file, JSON.stringify(missing));
  await assert.rejects(executeOpeningCommand(["recover-cleanup", f.root, f.file], f.services));
  assert.equal(f.inputs.length, 0); assert.deepEqual(JSON.parse(fs.readFileSync(f.file, "utf8")), missing);
});
