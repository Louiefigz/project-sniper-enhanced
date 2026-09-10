/** Actual cleanup/result/transport, TEMP lease and publications; readiness/tools/native invocation are explicit TEST leaves. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import childProcess from "node:child_process";
import { randomUUID } from "node:crypto";
import test, { type TestContext } from "node:test";
import { CutPreviewProcessError } from "@/app/api/producer/auto-edit/cut-preview-process";
import { SOURCE_COLOR_READBACK_STAGES } from "@/lib/producer/contracts/guided-opening-result-v2";
import { observeHumanCutJob } from "../human-cut-acceptance-store";
import { openingCleanupStoreDependencies } from "../guided-opening-cleanup-store";
import { assertSourceColorReadInvocation } from "../guided-source-color-read-transport";
import { sourceColorReadbackDependencies, verifyCleanedSourceColorOpeningMediaUnderLease,
  assertSourceColorOpeningReadbackMetadata, assertSourceColorOpeningReadbackOwner } from "../guided-source-color-readback";
import { replaceReadIntegrationArchive, sourceColorReadIntegrationFixture,
  type SourceColorReadIntegrationFixture } from "./_guided-source-color-read-integration-fixture";

type InvokeInput = Parameters<typeof sourceColorReadbackDependencies.invoke>[0];

/** Returned schema2 JSON is TEST data; zero timings do not claim Python or native work ran. */
function readback(f: SourceColorReadIntegrationFixture): Record<string, unknown> {
  const { executionClaimSha256, ...completion } = f.media.completion;
  return { ...completion, kind: "guided-opening-media-readback", status: "verified", claimSha256: executionClaimSha256,
    scope: "exact-source-color-held-private-media-not-opening-or-delivery-approval", elapsedMs: 0,
    stages: SOURCE_COLOR_READBACK_STAGES.map(stage => ({ stage, status: "complete", elapsedMs: 0 })),
    sourceColorRecordsReplayed: true, basePictureConsumptionVerified: true, gamutMeasured: false, gradeApplied: false,
    colorQualified: false, processGroupAndDockerCleanup: "requires-separate-owned-server-observation",
    currentJournalAndLease: "requires-separate-owned-server-observation" };
}

/** Keep actual final store/CAS and lease; only declared upstream/native leaves are replaced. */
async function fixture(t: TestContext) {
  t.mock.method(childProcess, "spawn", () => { throw new Error("TEST forbids every native child"); });
  const f = await sourceColorReadIntegrationFixture(t), reply = readback(f), end = performance.now() + 30_000;
  const rangeFiles = Object.freeze({ core: path.join(f.cleanup.held.claim.outputRoot, "core.mp4"),
    review: path.join(f.cleanup.held.claim.outputRoot, "review.mp4") });
  const callbacks = { readiness: () => {}, before: () => {}, settled: () => {}, remaining: () => {} };
  const state = { expired: false, invokes: 0, spawned: 0, failure: undefined as Error | undefined,
    invocation: undefined as InvokeInput | undefined };
  const input = { dir: f.cleanup.job.ctx.dir, lease: f.projectLease, expectedCleanupHash: f.cleanup.cleanupHash,
    remainingMs: () => { callbacks.remaining(); return state.expired ? 0 : Math.max(0, Math.floor(end - performance.now())); } };
  const dependencies = { readiness: () => { callbacks.readiness(); return undefined as unknown as ReturnType<typeof sourceColorReadbackDependencies.readiness>; },
    tools: () => f.media.tools.read,
    invoke: async (value: InvokeInput) => {
      state.invokes++; state.invocation = value; value.remainingMs(); callbacks.before(); value.beforeSpawn?.(); state.spawned++;
      if (state.failure) throw state.failure;
      const result = { stdout: JSON.stringify(reply), stderr: "TEST native read not executed" };
      callbacks.settled(); value.afterSettled?.({ ...result, timedOut: false, groupStopped: true, forcedStop: false });
      return result;
    } };
  return { ...f, originalFixture: f, rangeFiles, reply, callbacks, state, input, dependencies,
    run: () => verifyCleanedSourceColorOpeningMediaUnderLease(input, dependencies) };
}
type Fixture = Awaited<ReturnType<typeof fixture>>;

/** Discover only this service's new TEST attempt records beneath the original claim namespace. */
function attempts(f: Fixture): string[] {
  const root = path.join(path.dirname(f.cleanup.held.claimPath), "readback-attempts");
  return fs.existsSync(root) ? fs.readdirSync(root).map(name => path.join(root, name)) : [];
}

/** A rejected read cannot select media, release the held project lease or repeat cleanup. */
function assertUnselected(f: Fixture): void {
  assert.equal(observeHumanCutJob(f.input.dir).sha256, f.cleanup.sha256);
  f.assertProject(); assert.equal(f.calls.length, 1);
}

/** The only additional writable fault target is the exact original TEMP media result, never its code/tool inventory. */
function replaceResult(f: Fixture): void {
  const file = f.media.file, root = fs.realpathSync(f.staging.root);
  assert.equal(file, path.join(f.cleanup.held.claim.outputRoot, "media-result.json")); assert(file.startsWith(root + path.sep));
  assert.equal(fs.realpathSync(file), file); assert.equal(fs.realpathSync(path.dirname(file)), path.dirname(file));
  const info = fs.lstatSync(file); assert(info.isFile()); assert.equal(info.nlink, 1); assert.equal(info.uid, process.getuid!());
  const temporary = path.join(path.dirname(file), `TEST-readback-result-${randomUUID()}.json`);
  fs.writeFileSync(temporary, fs.readFileSync(file), { flag: "wx", mode: 0o600 }); fs.renameSync(temporary, file);
}

/** Write only this literal inert TEST script, never an inventory-selected or installed tool path. */
function replaceInertReadScript(f: Fixture): void {
  const root = fs.realpathSync(f.staging.root);
  const file = path.join(root, "TEST-original-pipeline/scripts/producer/guided_opening_read.py");
  assert.equal(file, f.media.tools.read.script); assert.equal(fs.realpathSync(file), file);
  assert.equal(fs.realpathSync(path.dirname(file)), path.dirname(file));
  const stat = fs.lstatSync(file); assert(stat.isFile()); assert.equal(stat.nlink, 1); assert.equal(stat.uid, process.getuid!());
  assert.equal(fs.readFileSync(file, "utf8"), "# TEST inert read worker; never executed\n");
  fs.writeFileSync(file, "# TEST replaced after native stub; never executed\n", { flag: "w" });
}

/** Only the two literal pre-captured inert range files can be replaced, never a dependency inventory target. */
function replaceRange(f: Fixture, role: "core" | "review"): void {
  const file = f.rangeFiles[role], root = fs.realpathSync(f.staging.root);
  assert.equal(file, path.join(path.dirname(f.media.file), `${role}.mp4`)); assert(file.startsWith(root + path.sep));
  assert.equal(fs.realpathSync(file), file); assert.equal(fs.realpathSync(path.dirname(file)), path.dirname(file));
  const stat = fs.lstatSync(file); assert(stat.isFile()); assert.equal(stat.nlink, 1); assert.equal(stat.uid, process.getuid!());
  const bytes = fs.readFileSync(file); assert.equal(bytes.toString(), `TEST inert ${role === "core" ? 30 : 60}-frame private range; never decoded\n`);
  const temporary = path.join(path.dirname(file), `TEST-range-replacement-${randomUUID()}.mp4`);
  fs.writeFileSync(temporary, bytes, { flag: "wx", mode: 0o600 }); fs.renameSync(temporary, file);
}

test("actual schema2 service binds final cleanup, ordered stages and private unselected records", async t => {
  const f = await fixture(t), verified = await f.run();
  assert.equal(f.state.invokes, 1); assert.equal(f.state.spawned, 1); assertUnselected(f);
  assert.equal(verified.result.schemaVersion, 2); assert.equal(verified.result.elapsedMs, 0);
  assert.deepEqual(verified.result.stages.map(row => row.stage), [...SOURCE_COLOR_READBACK_STAGES]);
  assert.equal(verified.result.colorQualified, false); assert.equal(verified.mediaSelected, false);
  assert.equal(verified.openingApproved, false); assert.equal(verified.deliveryApproved, false);
  assert.equal(verified.receipt.value.outputSha256, verified.output.sha256);
  assert.deepEqual(verified.result.sourceColorEvidence, f.selected.completion.sourceColorEvidence);
  assertSourceColorOpeningReadbackMetadata(verified);
  assertSourceColorReadInvocation(f.state.invocation!.sourceColorRead!, verified.observed.held);
  assert.equal(f.state.invocation!.tools.script, f.media.tools.read.script);
  assert.equal(attempts(f).length, 1); assert(!fs.existsSync(path.join(attempts(f)[0], "failure.json")));
});

for (const change of ["schema1", "evidence", "stages", "elapsed"] as const) {
  test(`actual service refuses ${change} child output and retains unselected failure`, async t => {
    const f = await fixture(t);
    if (change === "schema1") f.reply.schemaVersion = 1;
    if (change === "evidence") f.reply.sourceColorEvidence = { ...f.media.completion.sourceColorEvidence, sha256: "0".repeat(64) };
    if (change === "stages") f.reply.stages = SOURCE_COLOR_READBACK_STAGES.slice(1).map(stage => ({ stage, status: "complete", elapsedMs: 0 }));
    if (change === "elapsed") f.reply.elapsedMs = 1_500_000;
    await assert.rejects(f.run); assertUnselected(f);
    assert.equal(f.state.invokes, 1); assert(!fs.existsSync(path.join(attempts(f)[0], "verified.json")));
    const failed = JSON.parse(fs.readFileSync(path.join(attempts(f)[0], "failure.json"), "utf8"));
    assert.equal(failed.schemaVersion, 2); assert.equal(failed.mediaSelected, false);
  });
}

test("forced TEST invocation failure preserves actual stop facts without selecting media", async t => {
  const f = await fixture(t), details = { timedOut: true, groupStopped: true, forcedStop: true, stdout: "TEST partial", stderr: "TEST forced" };
  f.state.failure = new CutPreviewProcessError("TEST forced native failure; no actual process", details);
  await assert.rejects(f.run, /TEST forced native failure/); assertUnselected(f);
  const failed = JSON.parse(fs.readFileSync(path.join(attempts(f)[0], "failure.json"), "utf8"));
  for (const [key, value] of Object.entries(details)) assert.equal(failed[key], value);
  assert.equal(failed.deliveryApproved, false); assert.equal(f.state.invokes, 1);
});

test("readiness cannot replace the original request cleanup hash before invocation", async t => {
  const f = await fixture(t); f.callbacks.readiness = () => { f.input.expectedCleanupHash = "0".repeat(64); };
  await assert.rejects(f.run, /original request/); assert.equal(f.state.invokes, 0);
  assert.equal(attempts(f).length, 0); assertUnselected(f);
});

test("readiness cannot replace the original remaining callback", async t => {
  const f = await fixture(t); f.callbacks.readiness = () => { f.input.remainingMs = () => 30_000; };
  await assert.rejects(f.run, /original request/); assert.equal(f.state.invokes, 0); assertUnselected(f);
});

for (const frontier of ["before", "settled"] as const) {
  test(`same-byte final archive replacement at ${frontier} frontier refuses`, async t => {
    const f = await fixture(t); f.callbacks[frontier] = () => replaceReadIntegrationArchive(f.originalFixture);
    await assert.rejects(f.run, /identity|metadata|changed/); assertUnselected(f);
    assert.equal(f.state.spawned, frontier === "before" ? 0 : 1);
    assert(fs.existsSync(path.join(attempts(f)[0], "failure.json")));
  });
  test(`same-byte selected media result replacement at ${frontier} frontier refuses`, async t => {
    const f = await fixture(t); f.callbacks[frontier] = () => replaceResult(f);
    await assert.rejects(f.run, /identity|metadata|changed/); assertUnselected(f);
    assert.equal(f.state.spawned, frontier === "before" ? 0 : 1);
  });
}

test("expired original allowance stops before the TEST spawn frontier", async t => {
  const f = await fixture(t); f.callbacks.before = () => { f.state.expired = true; };
  await assert.rejects(f.run, /remainder|deadline/); assert.equal(f.state.spawned, 0); assertUnselected(f);
});

test("last original callback cannot replace the archive after verified publication", async t => {
  const f = await fixture(t); let changed = false;
  f.callbacks.remaining = () => {
    if (!changed && attempts(f).some(dir => fs.existsSync(path.join(dir, "verified.json")))) {
      changed = true; replaceReadIntegrationArchive(f.originalFixture);
    }
  };
  await assert.rejects(f.run, /identity|metadata|changed/); assert(changed); assertUnselected(f);
  assert(fs.existsSync(path.join(attempts(f)[0], "failure.json")));
});

test("metadata verification refuses cloned return capabilities", async t => {
  const f = await fixture(t), verified = await f.run();
  assert.throws(() => assertSourceColorOpeningReadbackMetadata({ ...verified }), /actual original/);
  assertSourceColorOpeningReadbackMetadata(verified); assertUnselected(f);
});

test("readback owner preserves exact live fields without invoking remaining or native callbacks", async t => {
  const f = await fixture(t), verified = await f.run(); let remainingCalls = 0;
  const forbiddenRemaining = () => { remainingCalls++; throw new Error("TEST owner check must not invoke remaining"); };
  f.callbacks.remaining = forbiddenRemaining;
  assertSourceColorOpeningReadbackOwner(verified, f.input);
  assertSourceColorOpeningReadbackOwner(verified, { ...f.input });
  const variants: [string, typeof f.input][] = [
    ["directory", { ...f.input, dir: path.join(f.input.dir, "TEST-other-directory") }],
    ["cloned lease", { ...f.input, lease: { ...f.input.lease } }],
    ["remaining callback", { ...f.input, remainingMs: forbiddenRemaining }],
    ["cleanup hash", { ...f.input, expectedCleanupHash: "0".repeat(64) }],
  ];
  for (const [name, input] of variants) {
    assert.throws(() => assertSourceColorOpeningReadbackOwner(verified, input), /different live request owner/, name);
  }
  assert.throws(() => assertSourceColorOpeningReadbackOwner({ ...verified }, f.input), /actual original/);
  assert.equal(remainingCalls, 0); assert.equal(f.state.invokes, 1); assert.equal(f.state.spawned, 1); assertUnselected(f);
});

test("initial actual cleanup-store callback cannot replace the original service allowance", async t => {
  const f = await fixture(t), actual = openingCleanupStoreDependencies.final;
  t.mock.method(openingCleanupStoreDependencies, "final", (input: Parameters<typeof actual>[0]) => {
    f.input.remainingMs = () => 30_000; return actual(input);
  });
  await assert.rejects(f.run, /original request/); assert.equal(f.state.invokes, 0); assertUnselected(f);
});

test("final original callback cannot replace the literal inert TEST read tool", async t => {
  const f = await fixture(t); let changed = false;
  f.callbacks.remaining = () => {
    if (!changed && attempts(f).some(dir => fs.existsSync(path.join(dir, "verified.json")))) {
      changed = true; replaceInertReadScript(f);
    }
  };
  await assert.rejects(f.run, /tool identity changed/); assert(changed); assertUnselected(f);
});

test("failed held metadata records only the original generation-clock lineage", async t => {
  const f = await fixture(t), original = f.cleanup.held.claim.clockHash, changed = "0".repeat(64);
  f.callbacks.settled = () => { f.state.invocation!.held.claim.clockHash = changed; };
  await assert.rejects(f.run, /original|metadata|changed/); assert.notEqual(original, changed);
  assert(!fs.existsSync(path.join(f.input.dir, "generation-clock-observations", changed)));
  assert(fs.existsSync(path.join(f.input.dir, "generation-clock-observations", original)));
  assertUnselected(f);
});

test("outer final metadata cannot consume the original remaining allowance and escape", async t => {
  const f = await fixture(t); let now = performance.now(), checks = 0, advanced = false, verifiedPath: string | undefined;
  const end = now + 30_000, actualStat = fs.lstatSync;
  t.mock.method(performance, "now", () => now);
  f.input.remainingMs = () => {
    const directory = attempts(f).find(dir => fs.existsSync(path.join(dir, "verified.json")));
    if (directory) { checks++; verifiedPath = path.join(directory, "verified.json"); }
    return Math.floor(end - now);
  };
  t.mock.method(fs, "lstatSync", (...args: Parameters<typeof fs.lstatSync>) => {
    const value = Reflect.apply(actualStat, fs, args) as ReturnType<typeof fs.lstatSync>;
    if (!advanced && checks >= 2 && typeof args[0] === "string" && args[0] === verifiedPath) {
      advanced = true; now = end + 1;
    }
    return value;
  });
  await assert.rejects(f.run, /exhausted|remainder/); assert(advanced); assert.equal(now, end + 1); assertUnselected(f);
});

for (const target of ["result", "receipt", "output"] as const) {
  test(`returned ${target} metadata cannot be altered after verification`, async t => {
    const f = await fixture(t), verified = await f.run();
    assert.throws(() => {
      if (target === "result") verified.result.elapsedMs = 1;
      else verified[target].value.TEST_modified = true;
      assertSourceColorOpeningReadbackMetadata(verified);
    });
    assertUnselected(f);
  });
}

for (const [frontier, role] of [["settled", "core"], ["final", "review"], ["returned", "core"]] as const) {
  test(`original inert ${role} range replacement at ${frontier} frontier remains refused`, async t => {
    const f = await fixture(t); let changed = false;
    const change = () => { if (!changed) { changed = true; replaceRange(f, role); } };
    if (frontier === "settled") f.callbacks.settled = change;
    if (frontier === "final") f.callbacks.remaining = () => {
      if (attempts(f).some(dir => fs.existsSync(path.join(dir, "verified.json")))) change();
    };
    if (frontier === "returned") {
      const verified = await f.run(); change(); assert.throws(() => assertSourceColorOpeningReadbackMetadata(verified), /metadata changed/);
    } else await assert.rejects(f.run, /metadata changed/);
    assert(changed); assert.equal(f.state.spawned, 1); assertUnselected(f);
  });
}
