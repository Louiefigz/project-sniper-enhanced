/** Actual TEMP controller/claim CAS and two leases; source/native/creative admission remain TEST-only. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import childProcess from "node:child_process";
import type { TestContext } from "node:test";
import { autoEditJobPath } from "../auto-edit-job-persistence";
import { holdSourceColorPrelaunch, type SourceColorPrelaunchInput } from "../guided-source-color-prelaunch-owner";
import { stageGuidedSourceColor } from "../guided-source-color-staging";
import { openingControllerPrelaunchFixture } from "./_guided-opening-controller-terminal-fixture";
import { completedMediaFixtureStart, launchOpeningControllerFixture, mockOpeningControllerIdentity } from "./_guided-opening-controller-lifecycle-fixture";

/** All preclaim metadata is original before the claim/staging hold; no sealed parent is rebound. */
export function prelaunchFixture(t: TestContext) {
  mockOpeningControllerIdentity(t);
  t.mock.method(childProcess, "spawn", () => { throw new Error("TEST native subprocess forbidden"); });
  const startedAt = completedMediaFixtureStart();
  const f = openingControllerPrelaunchFixture(t, { start: input => launchOpeningControllerFixture(input.dir, input.before, {
    sourceColor: input.sourceColor, token: input.token, requestId: "a8b9ce05-29ec-4bba-93cf-982d811ed137",
    origin: { clockHash: "a".repeat(64), startedAt },
  }) });
  const input: SourceColorPrelaunchInput = { controller: f.parent.lifecycle, claim: f.entered.bound,
    projectLease: f.parent.lease, staging: f.staging };
  const active = path.join(f.staging.root, ".sniper-color-resource", "active.json");
  const assertLeases = () => { f.parent.guard(); f.staging.resource.assertResource(); };
  return { ...f, input, active, assertLeases, hold: () => holdSourceColorPrelaunch(input),
    stage: (owner: ReturnType<typeof holdSourceColorPrelaunch>) => stageGuidedSourceColor(f.staging, owner) };
}
export type PrelaunchFixture = ReturnType<typeof prelaunchFixture>;

/** Read only the literal fixture reservation; this is TEST observation, never a recovered owner. */
export function prelaunchJobs(f: PrelaunchFixture): Array<{ inputPath: string; executionDir: string }> {
  assert.equal(f.active, path.join(fs.realpathSync(f.staging.root), ".sniper-color-resource", "active.json"));
  return JSON.parse(fs.readFileSync(f.active, "utf8")).jobs;
}

/** A finite exact allowlist forbids mutations derived from tool/code/source inventory records. */
export function replacePrelaunchFile(f: PrelaunchFixture, role: "claim" | "input" | "journal" | "reservation"): void {
  const allowed = { claim: f.entered.bound.claimPath, input: f.entered.bound.claim.inputPath,
    journal: autoEditJobPath(f.staging.producerDir), reservation: f.active };
  const file = allowed[role], root = fs.realpathSync(f.staging.root);
  assert(file.startsWith(root + path.sep)); assert.equal(fs.realpathSync(file), file);
  assert.equal(fs.realpathSync(path.dirname(file)), path.dirname(file));
  const stat = fs.lstatSync(file); assert(stat.isFile()); assert.equal(stat.nlink, 1); assert.equal(stat.uid, process.getuid!());
  const temporary = path.join(path.dirname(file), `TEST-prelaunch-${role}-replacement.json`);
  fs.writeFileSync(temporary, fs.readFileSync(file), { flag: "wx", mode: 0o600 }); fs.renameSync(temporary, file);
}

/** No cancellation side effects are authorized by either phase gate. */
export function assertPrelaunchRetained(f: PrelaunchFixture, original: Buffer): void {
  assert.deepEqual(fs.readFileSync(f.active), original); f.assertLeases();
  for (const job of prelaunchJobs(f)) assert.throws(() => fs.lstatSync(job.executionDir), { code: "ENOENT" });
  for (const name of ["media-process-intent.json", "media-process-result.json", "owned-process-ledger.media.jsonl"]) {
    assert.throws(() => fs.lstatSync(path.join(path.dirname(f.entered.bound.claimPath), name)), { code: "ENOENT" });
  }
}
