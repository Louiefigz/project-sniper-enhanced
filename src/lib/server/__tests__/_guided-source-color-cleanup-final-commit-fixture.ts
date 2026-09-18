/** Actual TEMP two-CAS/retirement path; only original native, tool and claim admission are TEST leaves. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
import type { TestContext } from "node:test";
import { autoEditJobPath } from "../auto-edit-job-persistence";
import { observeHumanCutJob } from "../human-cut-acceptance-store";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { parseFinalSourceColorCleanupFact } from "../../producer/contracts/guided-source-color-cleanup-facts";
import { readRetainedSourceColorCleanupPending } from "../guided-source-color-cleanup-pending-read";
import { cleanupPendingReadLeaves } from "./_guided-source-color-cleanup-pending-read-fixture";
import { sourceColorRetirementFixture } from "./_guided-source-color-reservation-retirement-fixture";

/** Preserve actual pending bytes before actual unlink, then retain the same original clock for history. */
export async function cleanupFinalCommitFixture(t: TestContext) {
  const f = await sourceColorRetirementFixture(t), pendingBefore = observeHumanCutJob(f.before.job.ctx.dir), retired = f.retire();
  const objects = path.join(f.before.job.ctx.dir, ".sniper-authority-v1/objects/receipts"), names = fs.readdirSync(objects).sort();
  const controls = { history: (input: Parameters<typeof readRetainedSourceColorCleanupPending>[0], hash: string) =>
    readRetainedSourceColorCleanupPending(input, hash, cleanupPendingReadLeaves(f)) };
  const files = { journal: autoEditJobPath(f.before.job.ctx.dir), ack: f.files.ack, media: f.files.media,
    output: path.join(f.directory, "output.json"), pendingSnapshot: path.join(f.before.job.ctx.dir,
      "human-cut-job-snapshots", `${pendingBefore.sha256}.json`) };
  return { ...f, retired, pendingBefore, objects, names, finalControls: controls, finalFiles: files };
}
export type CleanupFinalCommitFixture = Awaited<ReturnType<typeof cleanupFinalCommitFixture>>;

/** Select one actual newly published final fact only within the bounded original TEST object directory. */
export function finalCommitFactFile(f: CleanupFinalCommitFixture): string {
  const names = fs.readdirSync(f.objects); assert(names.length <= 256);
  const fresh = names.filter(name => !f.names.includes(name)); assert.equal(fresh.length, 1);
  assert.match(fresh[0], /^[0-9a-f]{64}\.json$/);
  const file = path.join(f.objects, fresh[0]); checkedFinalFile(f, file);
  const raw = readCutPreviewObject(file), fact = parseFinalSourceColorCleanupFact(raw.value);
  assert.equal(`${raw.sha256}.json`, fresh[0]); assert.equal(fact.pendingJournalHash, f.pendingBefore.sha256);
  assert.equal(fact.preparedFactHash, f.recorded.factHash); assert.deepEqual(fact.retirementAck, f.retired.reference);
  return file;
}

/** The selected file must be an exact canonical single-link user-owned TEST file before any write. */
function checkedFinalFile(f: CleanupFinalCommitFixture, file: string): void {
  const root = fs.realpathSync(f.staging.root); assert(file.startsWith(root + path.sep));
  assert.equal(fs.realpathSync(file), file); assert.equal(fs.realpathSync(path.dirname(file)), path.dirname(file));
  const stat = fs.lstatSync(file); assert(stat.isFile()); assert.equal(stat.nlink, 1); assert.equal(stat.uid, process.getuid!());
}

/** No arbitrary target or dependency path: five fixed artifacts plus the validated newly published fact. */
export function replaceFinalCommitFile(f: CleanupFinalCommitFixture, name: keyof CleanupFinalCommitFixture["finalFiles"] | "fact"): void {
  const file = name === "fact" ? finalCommitFactFile(f) : f.finalFiles[name]; checkedFinalFile(f, file);
  const temporary = path.join(path.dirname(file), `TEST-final-replacement-${randomUUID()}.json`);
  fs.writeFileSync(temporary, fs.readFileSync(file), { flag: "wx", mode: 0o600 }); fs.renameSync(temporary, file);
}

/** No failure retroactively erases cleanup, acknowledgement or the journal phase already committed. */
export function assertFinalCommitRetained(f: CleanupFinalCommitFixture, final: boolean): void {
  const current = observeHumanCutJob(f.before.job.ctx.dir), pointer = current.job.guidedHandoffV2!;
  assert.equal(Object.hasOwn(pointer, "openingExecutionClaimHash"), !final);
  assert.equal(Object.hasOwn(pointer, "openingProcessOutcomeHash"), !final);
  if (!final) assert.equal(current.sha256, f.pendingBefore.sha256);
  assert(!fs.existsSync(f.files.active)); assert(fs.existsSync(f.files.ack)); assert(fs.existsSync(f.files.archive));
  assert(!fs.existsSync(path.join(f.directory, "failure.json"))); assert.equal(f.calls.length, 1);
}
