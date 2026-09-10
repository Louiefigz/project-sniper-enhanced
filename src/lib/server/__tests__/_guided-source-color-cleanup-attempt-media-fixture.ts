/** Exact TEMP media-proof files; their journal/native provenance is explicitly TEST-stubbed. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { createHash, randomUUID } from "node:crypto";
import type { CleanupMediaReference, CaptureCleanupMediaReference } from "../guided-source-color-cleanup-attempt-media";
import type { sourceColorCleanupProcessFixture } from "./_guided-source-color-cleanup-process-fixture";

/** New fixture-owned metadata only; never writes an existing dependency or installed executable. */
function leaf(root: string, file: string, value: unknown): string {
  assert.equal(fs.realpathSync(root), root); assert(file.startsWith(root + path.sep));
  fs.mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 });
  assert.equal(fs.realpathSync(path.dirname(file)), path.dirname(file));
  const bytes = Buffer.from(typeof value === "string" ? value : JSON.stringify(value));
  fs.writeFileSync(file, bytes, { flag: "wx", mode: 0o600 });
  return createHash("sha256").update(bytes).digest("hex");
}

/** This provider bypasses only media activation admission; the reader actually hashes/holds all five files. */
export function cleanupAttemptMediaFixture(f: ReturnType<typeof sourceColorCleanupProcessFixture>) {
  const root = f.staging.root, held = f.input.held, execution = path.dirname(held.claimPath), producer = held.job.ctx.dir;
  const files: CleanupMediaReference[] = [];
  const add = (role: CleanupMediaReference["role"], file: string, value: unknown) => {
    const sha256 = leaf(root, file, value); files.push({ role, path: file, sha256 }); return sha256;
  };
  const priorBytes = JSON.stringify({ scope: "TEST original journal admission stub" });
  const priorSha = createHash("sha256").update(priorBytes).digest("hex");
  add("priorJournal", path.join(producer, "human-cut-job-snapshots", `${priorSha}.json`), priorBytes);
  const script = path.join(held.job.ctx.pipeline!.snapshotRoot, "scripts/producer/guided_opening_media.py");
  const ledger = ["worker-started", "worker-finished"].map((event, index) => JSON.stringify({ event, pid: process.pid, argv0: script, at: 1000 + index })).join("\n") + "\n";
  f.actual.receipt.ledgerSha256 = add("ledger", path.join(execution, "owned-process-ledger.media.jsonl"), ledger);
  f.actual.intentHash = add("intent", path.join(execution, "media-process-intent.json"), { scope: "TEST original intent admission stub", sourceColor: f.actual.sourceColor });
  f.actual.receipt.intentHash = f.actual.intentHash;
  f.actual.receiptSha256 = add("outcome", path.join(execution, "media-process-result.json"), f.actual.receipt);
  const activation = { scope: "TEST original activation admission stub", beforeJournalHash: priorSha,
    intentSha256: f.actual.intentHash, outcomeSha256: f.actual.receiptSha256 };
  const hash = createHash("sha256").update(JSON.stringify(activation)).digest("hex");
  add("activation", path.join(producer, ".sniper-authority-v1/objects/receipts", `${hash}.json`), activation);
  held.job.guidedHandoffV2 = { ...held.job.guidedHandoffV2, openingProcessOutcomeHash: hash } as typeof held.job.guidedHandoffV2;
  const provider = (original: typeof held, capture: CaptureCleanupMediaReference) => {
    assert.equal(original, held); for (const ref of files) capture(ref);
  };
  return { files, provider, root };
}

/** Replacement is limited to the five explicit original TEMP files; equal bytes still change identity. */
export function replaceAttemptMediaFile(f: ReturnType<typeof cleanupAttemptMediaFixture>, role: CleanupMediaReference["role"]): void {
  const file = f.files.find(row => row.role === role)!.path;
  assert(file.startsWith(f.root + path.sep)); assert.equal(fs.realpathSync(file), file);
  const stat = fs.lstatSync(file); assert(stat.isFile()); assert.equal(stat.nlink, 1); assert.equal(stat.uid, process.getuid!());
  const temporary = path.join(path.dirname(file), `TEST-media-replacement-${randomUUID()}.json`);
  fs.writeFileSync(temporary, fs.readFileSync(file), { flag: "wx", mode: 0o600 }); fs.renameSync(temporary, file);
}
