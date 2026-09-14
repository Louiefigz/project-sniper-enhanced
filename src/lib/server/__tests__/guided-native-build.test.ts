/** Internal structural entry seams only; no real accepted lineage, lease or media process is invented. */
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { buildGuidedNativeProject } from "../guided-native-build";
import { canonicalJsonSha256 } from "../auto-edit-hash";
import { writeGuidedNativeProject } from "../guided-native-project-store";
import { readNativeShortProject } from "../native-short-project";
import { guidedBindingFixture } from "./_guided-native-binding-fixture";

function fixture() {
  const f = guidedBindingFixture(), at = Date.now();
  Object.assign(f.proposal, { sha256: "b".repeat(64), clock: { hash: "a".repeat(64) }, generationStartedAt: new Date(at).toISOString() });
  f.proposal.job.token = "TEST-current-token";
  let wall = at, mono = 0, journalHash = f.proposal.sha256, guards = 0, releases = 0, writes = 0;
  const acquisitions: unknown[] = [], lease = { release: () => { releases++; } };
  const input = { dir: f.producerDir, visual: { candidateHash: canonicalJsonSha256(f.proposal.result.candidate), project: f.input, assetResolutions: f.mappings } };
  const dependencies = { canonicalDir: () => f.producerDir, proposal: () => f.proposal,
    observeJob: () => ({ ...f.proposal, sha256: journalHash }),
    acquire: async (dir: string, capability: unknown) => { acquisitions.push({ dir, capability }); return lease; },
    leaseGuard: (_dir: string, held: typeof lease) => { assert.equal(held, lease); return () => { guards++; }; },
    clocks: { wall: () => wall, monotonic: () => mono },
    write: async (...args: Parameters<typeof writeGuidedNativeProject>) => {
      writes++; return writeGuidedNativeProject(args[0], args[1], args[2], { ...f.dependencies, prepareCaptionGroups: async () => f.input.canvas.captionGroups });
    } };
  const results = () => readdirSync(path.join(f.producerDir, "native-build-attempts")).map(id =>
    JSON.parse(readFileSync(path.join(f.producerDir, "native-build-attempts", id, "result.json"), "utf8")));
  return { ...f, input, dependencies, acquisitions, results, counters: () => ({ guards, releases, writes }),
    advance: (ms: number) => { wall += ms; mono += ms; }, changeJournal: () => { journalHash = "e".repeat(64); } };
}

test("leased entry derives exact checkpoint capability and returns only a native QC candidate", async () => {
  const f = fixture();
  try {
    const result = await buildGuidedNativeProject(f.input, f.dependencies);
    assert.deepEqual(f.acquisitions, [{ dir: f.producerDir, capability: { workflowVersion: 2, action: "compile-post-cut-proposal",
      expectedStatus: "treatment_admitted", expectedToken: "TEST-current-token", expectedJournalHash: "b".repeat(64) } }]);
    assert.equal(result.status, "ready-for-native-qc"); assert.equal(result.publicationApproved, false);
    assert.equal(result.providerCalls, 0); assert.equal(result.renderStarted, false);
    assert.equal(readNativeShortProject(result.directory, { readGuidedProposal: () => f.proposal }).guidedBinding?.proposalVersion, 10);
    assert.equal(f.counters().releases, 1); assert.ok(f.counters().guards > 5);
    assert.equal(f.results()[0].status, "ready-for-native-qc");
  } finally { f.cleanup(); }
});

test("lease denial and changed journal never reach the project writer", async () => {
  for (const mode of ["denied", "changed"] as const) {
    const f = fixture();
    try {
      const acquire = f.dependencies.acquire;
      f.dependencies.acquire = async (...args) => {
        if (mode === "denied") throw new Error("TEST held by another owner");
        const held = await acquire(...args); f.changeJournal(); return held;
      };
      await assert.rejects(buildGuidedNativeProject(f.input, f.dependencies), /another owner|journal changed/);
      assert.equal(f.counters().writes, 0); assert.equal(f.counters().releases, mode === "denied" ? 0 : 1);
    } finally { f.cleanup(); }
  }
});

test("source/request inspection time and expired original generation clock do not get renewed", async () => {
  for (const mode of ["inspection", "expired-origin"] as const) {
    const f = fixture();
    try {
      if (mode === "inspection") f.dependencies.proposal = () => { f.advance(120_001); return f.proposal; };
      else f.proposal.generationStartedAt = new Date(Date.now() - 121 * 60_000).toISOString();
      await assert.rejects(buildGuidedNativeProject(f.input, f.dependencies), /deadline-exceeded|not-admitted/);
      assert.equal(f.counters().writes, 0); assert.equal(f.counters().releases, 1);
      assert.equal(f.results()[0].status, "failed-or-incomplete");
    } finally { f.cleanup(); }
  }
});

test("local caption/assembly failure retains evidence and releases the actual held lease object", async () => {
  const f = fixture();
  try {
    f.dependencies.write = async () => { throw new Error("TEST caption process failure with retained diagnostics"); };
    await assert.rejects(buildGuidedNativeProject(f.input, f.dependencies), /caption process failure/);
    assert.equal(f.counters().releases, 1);
    assert.match(f.results()[0].error, /retained diagnostics/);
    assert.equal(f.results()[0].publicationApproved, false);
  } finally { f.cleanup(); }
});

test("journal turnover during project work fails the final guard and preserves the candidate as unapproved", async () => {
  const f = fixture();
  try {
    const write = f.dependencies.write;
    f.dependencies.write = async (...args) => { const result = await write(...args); f.changeJournal(); return result; };
    await assert.rejects(buildGuidedNativeProject(f.input, f.dependencies), /journal changed/);
    assert.equal(f.counters().releases, 1); assert.equal(f.results()[0].projectMayExist, true);
  } finally { f.cleanup(); }
});

test("transport cannot inject a budget, provider, dependency or approval into the build service", async () => {
  const f = fixture();
  try {
    for (const key of ["deadlineMs", "provider", "dependencies", "approval", "destination"]) {
      await assert.rejects(buildGuidedNativeProject({ ...f.input, visual: { ...f.input.visual, [key]: true } }, f.dependencies), /unsupported|unknown|extra|fields/);
    }
    assert.equal(f.acquisitions.length, 0); assert.equal(f.counters().writes, 0);
  } finally { f.cleanup(); }
});

test("final success observation cannot expire after the preceding remaining check passed", async () => {
  const f = fixture(); let finished = false, postWriteReads = 0;
  try {
    const write = f.dependencies.write, wall = f.dependencies.clocks.wall;
    f.dependencies.write = async (...args) => { const result = await write(...args); finished = true; return result; };
    f.dependencies.clocks.wall = () => wall() + (finished && ++postWriteReads >= 2 ? 120_001 : 0);
    await assert.rejects(buildGuidedNativeProject(f.input, f.dependencies), /deadline-exceeded before its success receipt/);
    assert.equal(postWriteReads, 2); assert.equal(f.counters().releases, 1);
    assert.equal(f.results()[0].status, "failed-or-incomplete"); assert.equal(f.results()[0].publicationApproved, false);
  } finally { f.cleanup(); }
});
