import assert from "node:assert/strict";
import test from "node:test";
import { spawnSync } from "node:child_process";
import path from "node:path";
import { parseOpeningCleanupResult } from "../contracts/guided-opening-cleanup-v1";
import { parseGradeBatchCleanupResult, parseCurrentOpeningCleanupResult, parseCurrentOpeningCleanupStdout }
  from "../contracts/guided-opening-cleanup-v2";

/** Closed TEST metadata; names are not real reserved containers and no claim/daemon is authenticated. */
function batch() {
  return { schemaVersion: 1, kind: "grade-batch-cleanup-result", scope: "reserved-name-cleanup-not-process-settlement-work-or-approval",
    cleanupVerified: true, elapsedMs: 3010, stableAbsenceMs: 3000, passes: 14,
    jobs: ["00000000000040008000000000000001", "00000000000040008000000000000002"].map(id => ({
      containerName: `sniper-grade-observation-${id}`, inspections: 28, removalAttempts: 14, successfulRemovalResponses: 0,
      lastObservation: "absent", canonicalAbsenceProved: true })) };
}
function fixture() {
  const names = ["cleanup-claim-and-controls", "source-color-reservation-read", "reconcile-graphic-2",
    "cleanup-controls-after", "reconcile-source-color-batch", "source-color-reservation-after"];
  return { schemaVersion: 2, kind: "guided-opening-cleanup-result", claimPath: "/private/tmp/TEST/execution-claim.json",
    claimSha256: "a".repeat(64), inputSha256: "b".repeat(64), outputRoot: "/private/tmp/TEST/media-output",
    executionId: "00000000-0000-4000-8000-000000000001", cleanupVerified: true,
    graphics: [{ order: 2, state: "not-initialized", containerNames: [], cleanupVerified: true }], elapsedMs: 4000,
    stages: names.map(stage => ({ stage, status: "complete", elapsedMs: stage === "reconcile-source-color-batch" ? 3015 : 20 })),
    budgetScope: "separate-protected-cleanup-not-render-allowance", processGroupStopped: "requires-owned-server-observation",
    openingApproved: false, sourceColor: { reservation: { path: "/private/tmp/TEST/.sniper-color-resource/active.json",
      sha256: "c".repeat(64), sizeBytes: 2000 }, sourceColorHash: "d".repeat(64), batch: batch() } };
}

test("new complete cleanup metadata preserves exact batch and graphics without weakening legacy V1", () => {
  const value = fixture(); assert.equal(parseCurrentOpeningCleanupResult(value), value);
  assert.deepEqual(parseCurrentOpeningCleanupStdout(JSON.stringify(value)), value);
  assert.throws(() => parseOpeningCleanupResult(value));
  const { sourceColor: _color, stages, ...base } = value; void _color;
  const legacy = { ...base, schemaVersion: 1, stages: [stages[0], stages[2], stages[3]] };
  assert.equal(parseCurrentOpeningCleanupResult(legacy), legacy);
  assert.throws(() => parseCurrentOpeningCleanupResult({ ...legacy, sourceColor: value.sourceColor }));
});

test("all-name cleanup requires stable canonical absence rather than removal responses", () => {
  const value = batch(); assert.equal(parseGradeBatchCleanupResult(value), value);
  for (const patch of [{ cleanupVerified: false }, { stableAbsenceMs: 2999 }, { elapsedMs: 2999 },
    { elapsedMs: 300001 }, { stableAbsenceMs: 4000 }, { passes: 1 }, { passes: 1.5 }, { passes: "14" },
    { approved: true }, { jobs: [] }, { jobs: Array(129).fill(value.jobs[0]) }]) {
    assert.throws(() => parseGradeBatchCleanupResult({ ...value, ...patch }));
  }
  for (const patch of [{ canonicalAbsenceProved: false }, { lastObservation: "present" }, { lastObservation: "unknown" },
    { inspections: 27 }, { removalAttempts: 13 }, { successfulRemovalResponses: 15 }, { successfulRemovalResponses: -1 },
    { containerName: "sniper-grade-observation-*" }, { containerName: "sniper-render-00000000000040008000000000000001" },
    { containerName: "sniper-grade-observation-00000000000010008000000000000001" }, { approved: true }]) {
    assert.throws(() => parseGradeBatchCleanupResult({ ...value, jobs: [{ ...value.jobs[0], ...patch }] }));
  }
  assert.throws(() => parseGradeBatchCleanupResult({ ...value, jobs: [value.jobs[0], value.jobs[0]] }));
  // The real coordinator needs an initial interval, a later check and an extra confirmation sweep.
  // Its250ms polling interval also prevents arbitrarily many passes inside a3s report.
  for (const passes of [2, 1_000_000]) {
    assert.throws(() => parseGradeBatchCleanupResult({ ...value, passes,
      jobs: value.jobs.map(row => ({ ...row, inspections: passes * 2, removalAttempts: passes })) }));
  }
});

test("source-color proof must retain a closed bounded reservation and original semantic request hash", () => {
  const value = fixture(), color = value.sourceColor;
  for (const sourceColor of [null, {}, { ...color, sourceColorHash: "bad" }, { ...color, cleanupVerified: true },
    { ...color, reservation: { ...color.reservation, path: "/private/tmp/TEST/active.json" } },
    { ...color, reservation: { ...color.reservation, sha256: "bad" } },
    { ...color, reservation: { ...color.reservation, path: "/private/tmp//TEST/.sniper-color-resource/active.json" } }]) {
    assert.throws(() => parseCurrentOpeningCleanupResult({ ...value, sourceColor }));
  }
  for (const sizeBytes of [0, -1, 8 * 1024 * 1024 + 1, "1", true]) {
    assert.throws(() => parseCurrentOpeningCleanupResult({ ...value,
      sourceColor: { ...color, reservation: { ...color.reservation, sizeBytes } } }));
  }
});

test("all cleanup stages are ordered and complete under the one protected allowance", () => {
  const value = fixture();
  for (const stages of [value.stages.slice(1), [...value.stages].reverse(), [...value.stages, value.stages[0]],
    value.stages.map(row => ({ ...row, status: "failed" })), value.stages.map(row => ({ ...row, elapsedMs: 4001 }))]) {
    assert.throws(() => parseCurrentOpeningCleanupResult({ ...value, stages }));
  }
  const stages = structuredClone(value.stages); stages.at(-2)!.elapsedMs = 3009;
  assert.throws(() => parseCurrentOpeningCleanupResult({ ...value, stages }), /timing exceeds/);
  for (const patch of [{ approved: true }, { processGroupStopped: true }, { schemaVersion: 3 }, { openingApproved: true },
    { graphics: [{ ...value.graphics[0], containerNames: ["TEST-hidden-name"] }] }, { elapsedMs: 300001 }]) {
    assert.throws(() => parseCurrentOpeningCleanupResult({ ...value, ...patch }));
  }
});

test("whole stdout rejects progress, duplicated completions, NUL and over-budget bytes", () => {
  const text = JSON.stringify(fixture());
  for (const stdout of [`${text}\n${text}`, `progress\n${text}`, `${text}\u0000`, " ".repeat(128 * 1024 + 1), "null", "[]"]) {
    assert.throws(() => parseCurrentOpeningCleanupStdout(stdout));
  }
});

test("actual Python coordinator metadata for 2 and 128 names parses with virtual daemon and virtual 3s window", () => {
  const source = [
    "import json", "from _grade_batch_cleanup_fixture import GradeBatchCleanupFixture", "rows = []",
    "for count in (2, 128):", "    fixture = GradeBatchCleanupFixture(count)",
    "    try:", "        rows.append(fixture.run())", "    finally:", "        fixture.close()", "print(json.dumps(rows))",
  ].join("\n");
  const result = spawnSync(path.resolve(".venv/bin/python3"), ["-B", "-c", source], {
    cwd: process.cwd(), env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1", PYTHONPATH: "scripts:scripts/producer:scripts/producer/tests" },
    timeout: 20_000, encoding: "utf8" });
  assert.equal(result.status, 0, result.stderr);
  const rows = JSON.parse(result.stdout); assert.equal(rows.length, 2);
  rows.forEach((row: unknown, index: number) => {
    const value = parseGradeBatchCleanupResult(row); assert.equal(value.jobs.length, index === 0 ? 2 : 128);
    assert.equal(value.stableAbsenceMs, 3000);
  });
});
