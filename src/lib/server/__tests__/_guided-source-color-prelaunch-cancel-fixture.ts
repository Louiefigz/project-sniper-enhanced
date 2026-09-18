/** Exact TEMP fault targets only. No dependency/source/tool inventory path is ever a writable target. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import type { TestContext } from "node:test";
import { prelaunchFixture, prelaunchJobs } from "./_guided-source-color-prelaunch-fixture";
import { beginSourceColorPrelaunchCancellation } from "../guided-source-color-prelaunch-cancel";

export type CancellationStage = "none" | "reservation" | "partial" | "full";

/** Actual original controller/claim, actual metadata stager, actual two leases; no child dispatch.
 * Failed work callbacks stay failed: cancellation must not reuse or renew their allowance.
 * The fixed cancellation directory is never created by this fixture constructor.
 */
export function cancellationFixture(t: TestContext, stage: CancellationStage = "none") {
  const f = prelaunchFixture(t), owner = f.hold(), failure = new Error(`TEST retained ${stage} staging`);
  if (stage === "reservation" || stage === "partial") {
    f.staging.onGuard(() => {
      if (!fs.existsSync(f.active)) return;
      if (stage === "reservation" || fs.existsSync(prelaunchJobs(f)[0].inputPath)) throw failure;
    });
    assert.throws(() => f.stage(owner), error => error === failure);
  }
  if (stage === "full") f.stage(owner);
  const bytes = fs.existsSync(f.active) ? fs.readFileSync(f.active) : undefined;
  const root = path.dirname(f.entered.bound.claimPath), directory = path.join(root, "source-color-cancellation");
  return { ...f, owner, bytes, root, directory, begin: () => beginSourceColorPrelaunchCancellation(owner) };
}
export type CancellationFixture = ReturnType<typeof cancellationFixture>;

/** Fixed literal record allowlist beneath this fixture's original execution only. */
export function cancellationTarget(f: CancellationFixture, role: "archive" | "intent" | "ack"): string {
  const name = { archive: "reservation.json", intent: "intent.json", ack: "ack.json" }[role];
  const file = path.join(f.directory, name), root = fs.realpathSync(f.staging.root);
  assert.equal(f.directory, path.join(path.dirname(f.entered.bound.claimPath), "source-color-cancellation"));
  assert(file.startsWith(root + path.sep)); assert.equal(fs.realpathSync(path.dirname(file)), path.dirname(file));
  return file;
}

/** Same-byte inode replacement is restricted to three original cancellation records. */
export function replaceCancellationFile(f: CancellationFixture, role: "archive" | "intent" | "ack"): void {
  const file = cancellationTarget(f, role), row = fs.lstatSync(file);
  assert.equal(fs.realpathSync(file), file); assert(row.isFile()); assert.equal(row.nlink, 1); assert.equal(row.uid, process.getuid!());
  const temporary = path.join(f.directory, `TEST-${role}-replacement.json`);
  fs.writeFileSync(temporary, fs.readFileSync(file), { flag: "wx", mode: 0o600 }); fs.renameSync(temporary, file);
}

/** New-only contradictory metadata is confined to this fixture's exact original execution. */
export function contradictoryCancellationRecord(f: CancellationFixture,
  name: "media-process-intent.json" | "media-process-result.json" | "owned-process-ledger.media.jsonl"): void {
  assert.equal(fs.realpathSync(f.root), f.root); assert(f.root.startsWith(fs.realpathSync(f.staging.root) + path.sep));
  const file = path.join(f.root, name); fs.writeFileSync(file, "TEST inert contradictory metadata\n", { flag: "wx", mode: 0o600 });
}
