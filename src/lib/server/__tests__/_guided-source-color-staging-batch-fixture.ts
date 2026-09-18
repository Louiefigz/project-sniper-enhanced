/** Exact TEMP-only faults around the actual staging batch; no native or source admission. */
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import type { TestContext } from "node:test";
import { SourceColorStagingRead } from "../guided-source-color-staging-hold";
import { GUIDED_SOURCE_COLOR_TS_FILES, stageGuidedSourceColor } from "../guided-source-color-staging";
import { sourceColorStagingFixture } from "./_guided-source-color-staging-fixture";
import { prelaunchFixture } from "./_guided-source-color-prelaunch-fixture";

const FIRST = "src/lib/server/guided-source-color-staging.ts";
const LAST = "src/lib/server/template-usage-history.ts";
export type BatchBoundary = "early" | "later" | "middle" | "end";

/** Existing genuine live-owner hooks are optional; no replacement owner/clock is constructed. */
export function stagingBatchFixture(t: TestContext, hooks: boolean) {
  const live = hooks ? prelaunchFixture(t) : undefined, context = live?.staging ?? sourceColorStagingFixture(t);
  const owner = live?.hold(), original = SourceColorStagingRead.prototype.holdCodeBatch;
  const state = { inside: false, calls: 0, reader: undefined as SourceColorStagingRead | undefined, fired: false };
  assert.equal(GUIDED_SOURCE_COLOR_TS_FILES[0], FIRST); assert.equal(GUIDED_SOURCE_COLOR_TS_FILES.at(-1), LAST);
  t.mock.method(SourceColorStagingRead.prototype, "holdCodeBatch", function(this: SourceColorStagingRead, files: readonly string[]) {
    state.inside = true; state.reader = this;
    try { return original.call(this, files); } finally { state.inside = false; }
  });
  const boundaries = { early: 1, later: 10, middle: 4 * GUIDED_SOURCE_COLOR_TS_FILES.length,
    end: 8 * GUIDED_SOURCE_COLOR_TS_FILES.length + 2 };
  const at = (boundary: BatchBoundary, action: () => void) => context.onGuard(() => {
    if (!state.inside) return; state.calls++;
    if (state.calls === boundaries[boundary]) { state.fired = true; action(); }
  });
  return { context, live, owner, state, at, stage: () => stageGuidedSourceColor(context, owner),
    first: path.join(context.root, FIRST), last: path.join(context.root, LAST) };
}
export type StagingBatchFixture = ReturnType<typeof stagingBatchFixture>;

/** Only these two literal fixture-created inert pins may be faulted, never an observed dependency path. */
function pin(f: StagingBatchFixture, role: "first" | "last"): string {
  const root = fs.realpathSync(f.context.root), file = path.join(root, role === "first" ? FIRST : LAST);
  assert.equal(path.dirname(root), fs.realpathSync(os.tmpdir()));
  assert(path.basename(root).startsWith("source-color-expectations-")); assert.equal(fs.realpathSync(file), file);
  const stat = fs.lstatSync(file); assert(stat.isFile()); assert.equal(stat.nlink, 1); assert.equal(stat.uid, process.getuid!());
  assert.equal(file, f[role]); return file;
}
/** Same bytes, distinct original inode; no mutation of actual code/tool/source inventories. */
export function replaceBatchPin(f: StagingBatchFixture, role: "first" | "last"): void {
  const file = pin(f, role), replacement = path.join(path.dirname(file), `TEST-batch-${role}.ts`);
  fs.writeFileSync(replacement, fs.readFileSync(file), { flag: "wx", mode: 0o600 }); fs.renameSync(replacement, file);
}
/** Restoring content on the same inode still cannot restore its original ctime identity. */
export function rewriteThenRestoreBatchPin(f: StagingBatchFixture): void {
  const file = pin(f, "first"), original = fs.readFileSync(file);
  fs.writeFileSync(file, "// TEST changed and restored\n"); fs.writeFileSync(file, original);
}
/** A fixed fixture-owned server directory is the only allowed recursive copy target. */
export function replaceBatchParent(f: StagingBatchFixture): void {
  pin(f, "first"); pin(f, "last");
  const directory = path.join(fs.realpathSync(f.context.root), "src/lib/server");
  assert.equal(fs.realpathSync(directory), directory); assert(fs.lstatSync(directory).isDirectory());
  const entries = fs.readdirSync(directory); assert(entries.length < 4000);
  for (const name of entries) {
    const file = path.join(directory, name), stat = fs.lstatSync(file);
    assert(stat.isFile()); assert.equal(stat.nlink, 1); assert.equal(fs.realpathSync(file), file);
  }
  const retained = path.join(path.dirname(directory), "TEST-original-server");
  fs.renameSync(directory, retained); fs.cpSync(retained, directory, { recursive: true, errorOnExist: true, force: false });
}
/** Every batch fault precedes reservations, all job directories, and the final sidecar directory. */
export function assertBatchUnpublished(f: StagingBatchFixture): void {
  assert(f.state.fired, "The intended original callback must actually run");
  const c = f.context;
  for (const file of [path.join(c.resource.resource, "active.json"), path.join(c.producerDir, ".sniper-grade-observations"),
    path.join(path.dirname(c.opening.claimPath), "source-color"), path.join(c.root, "TEST-forbidden-publication.json")]) {
    assert.throws(() => fs.lstatSync(file), { code: "ENOENT" });
  }
  c.resource.assertResource(); f.live?.parent.guard();
}
