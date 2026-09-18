/** Actual metadata/lease staging only; all source/admission/runtime/clock semantics are TEST fixtures. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { execFileSync } from "node:child_process";
import { GUIDED_SOURCE_COLOR_TS_FILES, stageGuidedSourceColor } from "../guided-source-color-staging";
import { canonicalJsonSha256 } from "../auto-edit-hash";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { sourceColorStagingFixture } from "./_guided-source-color-staging-fixture";
import { mutateOwned } from "./_guided-source-color-expectations-fixture";

const activePath = (f: ReturnType<typeof sourceColorStagingFixture>) => path.join(f.resource.resource, "active.json");
const stagingDir = (f: ReturnType<typeof sourceColorStagingFixture>) => path.join(path.dirname(f.opening.claimPath), "source-color");
function record(file: string) { return readCutPreviewObject(file).value; }

test("mixed all-source jobs retain exact opening, raw inventories and explicit profiles without launching", t => {
  const f = sourceColorStagingFixture(t), held = stageGuidedSourceColor(f);
  held.assertCurrent();
  assert.deepEqual(held.jobs.map(row => row.sourceId), ["raw-b", "raw-a"]);
  assert.equal(held.executable, false); assert.equal(held.gradeApplicable, false); assert.equal(held.deliveryApproved, false);
  assert(Object.isFrozen(held)); assert(Object.isFrozen(held.jobs));
  const sidecar = record(held.input.path), reservation = record(held.reservation.path);
  assert.equal(sidecar.scope, "private-source-observation-not-transform-or-approval");
  assert.deepEqual(sidecar.sourceColor, f.sourceColor); assert.deepEqual(sidecar.expected, f.expectations.parents);
  assert.equal(reservation.sidecarPath, held.input.path); assert.deepEqual(sidecar.reservation, held.reservation);
  assert.equal(reservation.sourceColorHash, canonicalJsonSha256(f.sourceColor));
  assert.deepEqual(reservation.runtime, f.opening.claim.runtime);
  assert.deepEqual(sidecar.opening, reservation.opening);
  assert.equal((sidecar.opening as Record<string, unknown>).clockHash, f.opening.claim.clockHash);
  assert.equal((sidecar.opening as Record<string, unknown>).claimSha256, f.opening.claimSha256);
  for (const job of held.jobs) {
    const input = record(job.input.path), claim = record(job.launchClaim.path), v2 = job.sourceId === "raw-b";
    assert.equal(input.schemaVersion, v2 ? 2 : 1); assert.equal(Object.keys(input).length, v2 ? 10 : 9);
    assert.equal(input.ownerPid, process.pid); assert.equal(input.implementationSha256, job.implementation.sha256);
    assert.deepEqual(input.declaration, f.sourceColor.declarations[job.sourceId].declaration);
    assert.equal(Object.keys(claim).length, 15); assert.equal(claim.inputSha256, job.input.sha256);
    assert.equal(claim.profile, f.sourceColor.declarations[job.sourceId].profile);
    assert.equal(claim.containerName, `sniper-grade-observation-${job.jobId.replaceAll("-", "")}`);
    assert.throws(() => fs.lstatSync(job.executionDir), { code: "ENOENT" });
    assert.equal(fs.lstatSync(job.input.path).mode & 0o777, 0o400);
  }
  assert.equal(held.jobs[0].implementation.sha256, held.jobs[1].implementation.sha256);
  assert.notEqual(fs.lstatSync(held.jobs[0].implementation.path).ino, fs.lstatSync(held.jobs[1].implementation.path).ino);
  assert.equal(fs.lstatSync(held.jobs[0].implementation.path).nlink, 1);
  f.expectations.sources.forEach(source => assert.throws(() => fs.lstatSync(source.sourcePath), { code: "ENOENT" }));
  f.resource.assertResource();
});

test("actual Python reader accepts each staged version, profile, raw input and live parent PID", t => {
  const f = sourceColorStagingFixture(t), held = stageGuidedSourceColor(f);
  const requests = held.jobs.map(job => ({ path: job.input.path, sha: job.input.sha256,
    profile: f.sourceColor.declarations[job.sourceId].profile }));
  // Pure actual input reader only. No implementation admission, runtime, source or decoder is stubbed as successful.
  const script = "import json,sys\nfrom pathlib import Path\nfrom color.grade_project_input import read_grade_project_input\n"
    + "from color.grade_observation_profile import project_profile\n"
    + "from guided_source_color_staging_contract import validate_source_color_staging\n"
    + "payload=json.load(sys.stdin)\nrows=payload['jobs']\n"
    + "assert validate_source_color_staging(payload['sidecar'],payload['reservation']) == payload['sidecar']\n"
    + "values=[read_grade_project_input(Path(r['path']),r['sha'],r['profile']) for r in rows]\n"
    + "print(json.dumps([project_profile(v).version for v in values]))\n";
  const stdout = execFileSync(path.resolve(".venv/bin/python3"), ["-B", "-c", script], {
    cwd: path.resolve("scripts/producer"), input: JSON.stringify({ jobs: requests,
      sidecar: record(held.input.path), reservation: record(held.reservation.path) }), encoding: "utf8", timeout: 5000,
    env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1", PYTHONPATH: path.resolve("scripts/producer") },
  });
  assert.deepEqual(JSON.parse(stdout), [2, 1]); held.assertCurrent();
});

test("durable reservation enumerates every name before any prospective job directory exists", t => {
  const f = sourceColorStagingFixture(t); let witnessed = false;
  f.onGuard(() => {
    if (witnessed || !fs.existsSync(activePath(f))) return;
    const jobs = record(activePath(f)).jobs as Array<{ directory: string; containerName: string }>;
    assert.equal(jobs.length, 2); assert.equal(new Set(jobs.map(row => row.containerName)).size, 2);
    jobs.forEach(row => assert.throws(() => fs.lstatSync(row.directory), { code: "ENOENT" }));
    witnessed = true;
  });
  stageGuidedSourceColor(f); assert(witnessed);
});

test("partial staging retains complete reservation, created metadata and the caller resource lease", t => {
  const f = sourceColorStagingFixture(t), failure = new Error("TEST original budget expired after first job input");
  let interrupted = false;
  f.onGuard(() => {
    if (interrupted || !fs.existsSync(activePath(f))) return;
    const jobs = record(activePath(f)).jobs as Array<{ inputPath: string }>;
    if (fs.existsSync(jobs[0].inputPath)) { interrupted = true; throw failure; }
  });
  assert.throws(() => stageGuidedSourceColor(f), error => error === failure);
  assert(interrupted); f.resource.assertResource();
  const jobs = record(activePath(f)).jobs as Array<{ inputPath: string; executionDir: string }>;
  assert.equal(jobs.length, 2); assert(fs.existsSync(jobs[0].inputPath)); assert(!fs.existsSync(jobs[1].inputPath));
  assert(!fs.existsSync(path.join(stagingDir(f), "input.json")));
  jobs.forEach(row => assert.throws(() => fs.lstatSync(row.executionDir), { code: "ENOENT" }));
});

test("expired original guard makes no reservation or new job directories", t => {
  const f = sourceColorStagingFixture(t);
  f.onGuard(() => { throw new Error("TEST original clock expired"); });
  assert.throws(() => stageGuidedSourceColor(f), /original clock expired/);
  assert(!fs.existsSync(activePath(f))); assert(!fs.existsSync(stagingDir(f)));
  assert(!fs.existsSync(path.join(f.producerDir, ".sniper-grade-observations"))); f.resource.assertResource();
});

test("existing reservation is never overwritten or interpreted as proof of cleanup", t => {
  const f = sourceColorStagingFixture(t), target = activePath(f), bytes = "TEST malformed prior unresolved reservation\n";
  fs.writeFileSync(target, bytes, { flag: "wx", mode: 0o400 }); const original = fs.lstatSync(target);
  assert.throws(() => stageGuidedSourceColor(f), { code: "EEXIST" });
  assert.equal(fs.readFileSync(target, "utf8"), bytes); assert.equal(fs.lstatSync(target).ino, original.ino);
  assert(!fs.existsSync(path.join(f.producerDir, ".sniper-grade-observations"))); f.resource.assertResource();
});

test("all declarations must match the actual held expectations before reservation", t => {
  const f = sourceColorStagingFixture(t);
  f.sourceColor.declarations["raw-a"].declaration.cameraProfile = "TEST post-expectation replacement";
  assert.throws(() => stageGuidedSourceColor(f), /changed|differs/); assert(!fs.existsSync(activePath(f)));
});

test("callback cannot replace the original guard or resource lease reference", t => {
  const f = sourceColorStagingFixture(t); let changed = false;
  f.onGuard(() => { if (!changed) { changed = true; f.guard = () => undefined; } });
  assert.throws(() => stageGuidedSourceColor(f), /original staging context changed/); assert(!fs.existsSync(activePath(f)));
});

test("same-byte opening claim inode replacement in the first callback is not adopted", t => {
  const f = sourceColorStagingFixture(t), original = f.opening.claimPath; let changed = false;
  f.onGuard(() => {
    if (changed) return; changed = true;
    const replacement = path.join(path.dirname(original), "TEST-new-claim.json");
    fs.writeFileSync(replacement, fs.readFileSync(original), { flag: "wx" }); fs.renameSync(replacement, original);
  });
  assert.throws(() => stageGuidedSourceColor(f), /staging metadata changed/); assert(!fs.existsSync(activePath(f)));
});

test("held result rejects later raw input mutation and never releases the resource", t => {
  const f = sourceColorStagingFixture(t), held = stageGuidedSourceColor(f), target = held.jobs[0].input.path;
  fs.chmodSync(target, 0o600); mutateOwned(f, target, "{\"TEST\":\"changed metadata\"}\n");
  assert.throws(() => held.assertCurrent(), /staging metadata changed/); f.resource.assertResource();
  assert(fs.existsSync(activePath(f)));
});

test("a dangling prospective execution entry is rejected instead of treated as absence", t => {
  const f = sourceColorStagingFixture(t); let inserted = false;
  f.onGuard(() => {
    if (inserted || !fs.existsSync(activePath(f))) return;
    const jobs = record(activePath(f)).jobs as Array<{ directory: string; executionDir: string; launchClaimPath: string }>;
    if (!fs.existsSync(jobs[0].launchClaimPath)) return;
    fs.symlinkSync(path.join(f.root, "TEST-absent-execution"), jobs[0].executionDir); inserted = true;
  });
  assert.throws(() => stageGuidedSourceColor(f), /execution was created before/);
  assert(inserted); assert(!fs.existsSync(path.join(stagingDir(f), "input.json"))); f.resource.assertResource();
});

test("staged records are exclusive; a second attempt cannot create a second set of jobs", t => {
  const f = sourceColorStagingFixture(t), held = stageGuidedSourceColor(f);
  const before = fs.readdirSync(path.join(f.producerDir, ".sniper-grade-observations"));
  assert.throws(() => stageGuidedSourceColor(f), { code: "EEXIST" });
  assert.deepEqual(fs.readdirSync(path.join(f.producerDir, ".sniper-grade-observations")), before);
  held.assertCurrent(); f.resource.assertResource();
});

test("the last expectations callback cannot release the resource after its final lease check", t => {
  const f = sourceColorStagingFixture(t); let released = false;
  f.onGuard(() => {
    if (released || !fs.existsSync(path.join(stagingDir(f), "input.json"))) return;
    released = true; f.resource.lease.release();
  });
  assert.throws(() => stageGuidedSourceColor(f), /lease|lock|ENOENT|mutation/i);
  assert(released); assert(fs.existsSync(activePath(f)));
});

test("a later job callback cannot create an earlier prospective execution before staging returns", t => {
  const f = sourceColorStagingFixture(t); let inserted = false;
  f.onGuard(() => {
    if (inserted || !fs.existsSync(activePath(f))) return;
    const jobs = record(activePath(f)).jobs as Array<{ executionDir: string; launchClaimPath: string }>;
    if (!fs.existsSync(jobs[1].launchClaimPath)) return;
    fs.symlinkSync(path.join(f.root, "TEST-absent-earlier-execution"), jobs[0].executionDir); inserted = true;
  });
  assert.throws(() => stageGuidedSourceColor(f), /execution was created before/);
  assert(inserted); f.resource.assertResource(); assert(fs.existsSync(activePath(f)));
});

test("prospective-state check is explicit and distinct from metadata lifetime after handoff", t => {
  const f = sourceColorStagingFixture(t), held = stageGuidedSourceColor(f);
  held.assertUnstarted(); fs.mkdirSync(held.jobs[0].executionDir, { mode: 0o700 });
  assert.throws(() => held.assertUnstarted(), /execution was created before/);
  held.assertCurrent(); // Metadata only: the TEST mkdir is NOT actual owned execution or success.
  f.resource.assertResource();
});

test("new staging and contract pins come from the executed snapshot and remain held", t => {
  const f = sourceColorStagingFixture(t), held = stageGuidedSourceColor(f);
  const files = record(held.jobs[0].implementation.path).files as Array<{ path: string; sha256: string }>;
  const paths = files.map(row => row.path);
  assert.equal(new Set(paths).size, paths.length); assert.deepEqual(paths, [...paths].sort());
  GUIDED_SOURCE_COLOR_TS_FILES.forEach(relative => assert(paths.includes(path.join(f.context.opening.input.pipeline.snapshotRoot, relative))));
  const target = path.join(f.root, "src/lib/producer/contracts/guided-source-color-v1.ts");
  mutateOwned(f, target, "// TEST changed fixture-only transport pin\n");
  assert.throws(() => held.assertCurrent(), /staging metadata changed/); f.resource.assertResource();
});

test("an old snapshot missing a required source-color module rejects before any reservation", t => {
  const f = sourceColorStagingFixture(t), target = path.join(f.root, "src/lib/server/guided-source-color-staging-hold.ts");
  assert.equal(fs.realpathSync(target), target); assert.equal(fs.lstatSync(target).nlink, 1); fs.unlinkSync(target);
  assert.throws(() => stageGuidedSourceColor(f), { code: "ENOENT" });
  assert(!fs.existsSync(activePath(f))); assert(!fs.existsSync(stagingDir(f))); f.resource.assertResource();
});
