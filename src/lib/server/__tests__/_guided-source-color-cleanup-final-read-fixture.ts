/** Actual two-CAS/retirement/record readers. Original claim/media/tool/native admission is explicitly TEST-only. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
import type { TestContext } from "node:test";
import { commitRetiredSourceColorCleanup } from "../guided-source-color-cleanup-final-commit";
import { readFinalSourceColorCleanupForJournal, type SourceColorFinalCleanupReadInput } from "../guided-source-color-cleanup-final-read";
import { observeHumanCutJob, saveHumanCutJobSnapshot } from "../human-cut-acceptance-store";
import { readRetainedSourceColorCleanupPending } from "../guided-source-color-cleanup-pending-read";
import { cleanupPendingReadLeaves } from "./_guided-source-color-cleanup-pending-read-fixture";
import { cleanupFinalCommitFixture } from "./_guided-source-color-cleanup-final-commit-fixture";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { parseAutoEditJobRecord } from "../auto-edit-job-persistence";
import { canonicalJson } from "../auto-edit-hash";
import { writeGuidedObject } from "../guided-cut-v2-store";
import { buildSourceColorCleanupRetiredJob } from "../guided-source-color-cleanup-retired-job";
import type { FinalSourceColorCleanupFact } from "@/lib/producer/contracts/guided-source-color-cleanup-facts";

/** A separate observation clock starts only after the actual cleanup commits; it owns no old lease or work. */
export async function cleanupFinalReadFixture(t: TestContext) {
  const f = await cleanupFinalCommitFixture(t), committed = commitRetiredSourceColorCleanup(f.retired, f.finalControls);
  const current = observeHumanCutJob(f.before.job.ctx.dir); saveHumanCutJobSnapshot(current.job.ctx.dir, current);
  const callbacks = { guard: () => {}, remaining: () => {} }, calls = { guard: 0, remaining: 0, history: 0 };
  const started = performance.now(), remaining = () => 30_000 - (performance.now() - started);
  const input: SourceColorFinalCleanupReadInput = { dir: current.job.ctx.dir,
    journal: { path: f.finalFiles.journal, observed: current }, guard: () => { calls.guard++; callbacks.guard(); },
    remainingMs: () => { calls.remaining++; callbacks.remaining(); return remaining(); } };
  const dependencies = { history: (value: Parameters<typeof readRetainedSourceColorCleanupPending>[0], hash: string) => {
    calls.history++; return readRetainedSourceColorCleanupPending(value, hash, cleanupPendingReadLeaves(f));
  } };
  const objects = f.objects, snapshots = path.join(input.dir, "human-cut-job-snapshots");
  const files = { journal: f.finalFiles.journal, finalSnapshot: path.join(snapshots, `${current.sha256}.json`),
    fact: path.join(objects, `${committed.cleanupHash}.json`), ack: f.finalFiles.ack,
    pending: f.finalFiles.pendingSnapshot, prepared: path.join(objects, `${f.recorded.factHash}.json`),
    result: path.join(objects, `${f.recorded.fact.cleanupResultHash}.json`),
    original: path.join(snapshots, `${f.before.sha256}.json`), media: f.finalFiles.media, output: f.finalFiles.output,
    archive: f.recorded.fact.archive.path };
  return { ...f, committed, current, readInput: input, readDependencies: dependencies, readCallbacks: callbacks,
    readCalls: calls, readFiles: files, read: () => readFinalSourceColorCleanupForJournal(input, dependencies) };
}
export type FinalReadFixture = Awaited<ReturnType<typeof cleanupFinalReadFixture>>;

/** No dependency, source or arbitrary target can be a fault destination. */
export function finalReadFaultFile(f: FinalReadFixture, name: keyof FinalReadFixture["readFiles"]): string {
  const file = f.readFiles[name], root = fs.realpathSync(f.staging.root);
  assert(file.startsWith(root + path.sep)); assert.equal(fs.realpathSync(file), file);
  assert.equal(fs.realpathSync(path.dirname(file)), path.dirname(file));
  const stat = fs.lstatSync(file); assert(stat.isFile()); assert.equal(stat.nlink, 1); assert.equal(stat.uid, process.getuid!());
  return file;
}

/** Retain failures as replacements inside the named TEST namespace; never mutate shared held dependencies. */
export function replaceFinalReadFile(f: FinalReadFixture, name: keyof FinalReadFixture["readFiles"], bytes?: Buffer): void {
  const file = finalReadFaultFile(f, name), temporary = path.join(path.dirname(file), `TEST-final-read-${randomUUID()}.json`);
  fs.writeFileSync(temporary, bytes ?? fs.readFileSync(file), { flag: "wx", mode: 0o600 }); fs.renameSync(temporary, file);
}

/** The supplied historical observation is actual saved bytes, never a clone masquerading as the current journal. */
export function retainedFinalReadInput(f: FinalReadFixture): SourceColorFinalCleanupReadInput {
  const raw = readCutPreviewObject(f.readFiles.finalSnapshot), job = parseAutoEditJobRecord(raw.value);
  return { ...f.readInput, journal: { path: f.readFiles.finalSnapshot, observed: { ...raw, job } } };
}

/** Publish a TEST-forged final parent with exact content hashes to exercise semantic, not trivial hash, refusal. */
export function rebindFinalReadFact(f: FinalReadFixture, fact: FinalSourceColorCleanupFact): void {
  writeGuidedObject(f.readInput.dir, fact);
  const job = buildSourceColorCleanupRetiredJob({ job: f.pending.job, pendingJournalHash: f.pending.pendingJournalHash, prepared: f.pending.fact }, fact);
  replaceFinalReadFile(f, "journal", Buffer.from(canonicalJson(job)));
  f.readInput.journal.observed = observeHumanCutJob(f.readInput.dir);
}
