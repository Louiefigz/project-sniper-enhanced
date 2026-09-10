/** Original lifetime/adversarial record faults, limited to explicit named TEMP metadata. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { readSourceColorCleanupAttempt, assertSourceColorCleanupAttemptMetadata } from "../guided-source-color-cleanup-attempt-read";
import { cleanupAttemptReadFixture, mutateAttemptRecord, replaceAttemptFile,
  attemptFaultFile } from "./_guided-source-color-cleanup-attempt-read-fixture";

for (const name of ["start.json", "invocation.json", "output.json", "reservation.json", "owned-process-ledger.cleanup.jsonl"]) {
  test(`original ${name} identity is captured before the first caller callback`, async t => {
    const f = await cleanupAttemptReadFixture(t); let changed = false;
    f.callbacks.guard = () => { if (!changed) { changed = true; replaceAttemptFile(f, name); } };
    assert.throws(f.read, /file identity/);
  });
}

for (const role of ["held", "fact", "guard", "remaining"] as const) {
  test(`the first clock callback cannot rebaseline original ${role}`, async t => {
    const f = await cleanupAttemptReadFixture(t);
    f.callbacks.remaining = () => {
      if (role === "held") f.readInput.held = structuredClone(f.readInput.held);
      if (role === "fact") f.readInput.fact = structuredClone(f.readInput.fact);
      if (role === "guard") f.readInput.guard = () => {};
      if (role === "remaining") f.readInput.remainingMs = () => 300_000;
      return 300_000;
    };
    assert.throws(f.read, /caller identity/);
  });
}

test("a final actual ledger/descendant return cannot mutate earlier original input metadata", async t => {
  const f = await cleanupAttemptReadFixture(t);
  const dependencies = { ...f.readerDependencies, descendants: (...args: Parameters<typeof f.readerDependencies.descendants>) => {
    const result = f.readerDependencies.descendants(...args); f.fact.beforeJournalHash = "4".repeat(64); return result;
  } };
  assert.throws(() => readSourceColorCleanupAttempt(f.readInput, dependencies), /context metadata/);
});

test("a final actual ledger return cannot replace earlier invocation bytes", async t => {
  const f = await cleanupAttemptReadFixture(t);
  const dependencies = { ...f.readerDependencies, descendants: (...args: Parameters<typeof f.readerDependencies.descendants>) => {
    const result = f.readerDependencies.descendants(...args); replaceAttemptFile(f, "invocation.json"); return result;
  } };
  assert.throws(() => readSourceColorCleanupAttempt(f.readInput, dependencies), /file identity/);
});

test("same original protected remainder covers the last metadata and settlement bookkeeping", async t => {
  const f = await cleanupAttemptReadFixture(t); let now = 1000;
  t.mock.method(performance, "now", () => now); f.callbacks.remaining = () => 500;
  const dependencies = { ...f.readerDependencies, descendants: (...args: Parameters<typeof f.readerDependencies.descendants>) => {
    const result = f.readerDependencies.descendants(...args); now += 501; return result;
  } };
  assert.throws(() => readSourceColorCleanupAttempt(f.readInput, dependencies), /protected deadline expired/);
});

test("retained assertCurrent preserves original refs and does not mint a later replacement baseline", async t => {
  const f = await cleanupAttemptReadFixture(t), value = f.read(); replaceAttemptFile(f, "output.json");
  assert.throws(value.assertCurrent, /file identity/);
  assert.throws(() => assertSourceColorCleanupAttemptMetadata(value), /file identity/);
});

test("retained failure markers prevent a success history from being returned", async t => {
  const f = await cleanupAttemptReadFixture(t), failure = path.join(f.directory, "failure.json");
  assert(failure.startsWith(f.staging.root + path.sep)); assert.equal(fs.realpathSync(f.directory), f.directory);
  fs.writeFileSync(failure, "TEST retained failure\n", { flag: "wx", mode: 0o600 });
  assert.throws(f.read, /retained failure/);
});

test("actual malformed cleanup ledger cannot be laundered with a matching output SHA", async t => {
  const f = await cleanupAttemptReadFixture(t), ledger = attemptFaultFile(f, "owned-process-ledger.cleanup.jsonl");
  const first = fs.readFileSync(ledger, "utf8").split("\n")[0] + "\n";
  const hash = replaceAttemptFile(f, "owned-process-ledger.cleanup.jsonl", Buffer.from(first));
  mutateAttemptRecord(f, "output", row => { (row.ledger as { sha256: string }).sha256 = hash; });
  assert.throws(f.read, /worker.*finish|lifecycle|incomplete/i);
});

const badTools: [string, (tools: Record<string, unknown>) => void][] = [
  ["unpinned script", tools => { tools.scriptHash = "4".repeat(64); }],
  ["unpinned runner", tools => { tools.runnerScriptHash = "4".repeat(64); }],
  ["cross-snapshot script", tools => { tools.script = "/TEST/other/scripts/producer/guided_opening_cleanup.py"; }],
  ["relative Python", tools => { tools.pythonResolved = "python"; }],
  ["missing Python config", tools => { delete tools.venvConfig; }],
];
for (const [name, mutation] of badTools) {
  test(`historical invocation rejects ${name} without resampling installed tools`, async t => {
    const f = await cleanupAttemptReadFixture(t);
    mutateAttemptRecord(f, "invocation", row => mutation(row.tools as Record<string, unknown>));
    mutateAttemptRecord(f, "output", row => { row.invocationSha256 = f.fact.cleanupInvocationSha256; });
    assert.throws(f.read, /original script|absolute|missing|fields/);
  });
}
