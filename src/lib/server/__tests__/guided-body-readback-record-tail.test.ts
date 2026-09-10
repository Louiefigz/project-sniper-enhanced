/** Actual source2 candidate protocol; one exact TEST-owned verification inode fault, never native/source/tool mutation. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { createHash } from "node:crypto";
import test from "node:test";
import { autoEditJobPath } from "../auto-edit-job-persistence";
import { observeHumanCutJob } from "../human-cut-acceptance-store";
import { OWNED_PROCESS_LEDGER_ENV } from "../guided-opening-process-ledger";
import { bodySourceReadbackFixture } from "./_guided-body-source-color-readback-fixture";

type Fixture = Awaited<ReturnType<typeof bodySourceReadbackFixture>>;
type ReadbackRun = Parameters<Parameters<Fixture["run"]>[0]>[0];
type RecordHold = ReturnType<typeof originalVerified>;

/** Resolve only the already observed TEST read invocation and its literal verified.json sibling. */
function originalVerified(root: string, f: ReadbackRun) {
  assert.equal(f.calls.length, 1);
  const ledger = f.calls[0].env[OWNED_PROCESS_LEDGER_ENV]; assert.equal(typeof ledger, "string");
  const directory = path.dirname(ledger!), parent = path.join(f.context.operation.execution, "body-readback-attempts");
  assert(parent.startsWith(root + path.sep)); assert.equal(fs.realpathSync(parent), parent);
  assert.equal(path.dirname(directory), parent);
  assert.match(path.basename(directory), /^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/u);
  assert.equal(ledger, path.join(directory, "owned-process-ledger.read.jsonl"));
  const file = path.join(directory, "verified.json"), stat = fs.lstatSync(file, { bigint: true });
  assert.equal(fs.realpathSync(directory), directory); assert.equal(fs.realpathSync(file), file);
  assert(stat.isFile()); assert.equal(stat.nlink, BigInt(1)); assert.equal(stat.uid, BigInt(process.getuid!()));
  assert(stat.size > BigInt(0) && stat.size <= BigInt(128 * 1024));
  const bytes = fs.readFileSync(file), sha256 = createHash("sha256").update(bytes).digest("hex");
  return { file, directory, stat, bytes, sha256 };
}

/** New-only sibling then exact same-byte replacement; the original namespace is never inferred again. */
function replaceVerified(original: RecordHold): void {
  assert.equal(fs.realpathSync(original.directory), original.directory);
  const current = fs.lstatSync(original.file, { bigint: true });
  assert.equal(current.dev, original.stat.dev); assert.equal(current.ino, original.stat.ino);
  assert.equal(current.nlink, BigInt(1)); assert.equal(current.uid, BigInt(process.getuid!()));
  const temporary = path.join(original.directory, "TEST-original-verified-replacement.json");
  fs.writeFileSync(temporary, original.bytes, { flag: "wx", mode: 0o600 });
  fs.renameSync(temporary, original.file);
}

test("final original readback budget callback cannot replace its verified publication after actual candidate CAS", async t => {
  const fixture = await bodySourceReadbackFixture(t);
  await fixture.run(async f => {
    const rename = fs.renameSync, stat = fs.lstatSync, journal = autoEditJobPath(f.context.dir);
    const watermark = path.join(f.context.dir, "generation-clock-observations",
      f.context.budget.admission.clockHash, `${f.context.operation.executionId}.json`);
    let original: RecordHold | undefined, committedHash: string | undefined, changed = false;
    const publication = t.mock.method(fs, "renameSync", (from: fs.PathLike, to: fs.PathLike) => {
      rename(from, to);
      if (String(to) !== journal || committedHash) return;
      committedHash = observeHumanCutJob(f.context.dir).job.guidedHandoffV2?.bodyCandidateHash;
      if (committedHash) original = originalVerified(fixture.root, f);
    });
    const metadata = t.mock.method(fs, "lstatSync", ((file: fs.PathLike, options?: { bigint?: boolean }) => {
      const value = stat(file, options as { bigint: true });
      if (original && !changed && String(file) === watermark) {
        changed = true; replaceVerified(original);
      }
      return value;
    }) as typeof fs.lstatSync);
    let failure: unknown;
    try { await f.qualify(); } catch (error) { failure = error; }
    finally { metadata.mock.restore(); publication.mock.restore(); }
    assert(original); assert(committedHash); assert(changed, "original remaining callback reached its actual watermark IO");
    const current = fs.lstatSync(original.file, { bigint: true });
    assert.notEqual(current.ino, original.stat.ino);
    assert.equal(createHash("sha256").update(fs.readFileSync(original.file)).digest("hex"), original.sha256);
    assert.equal(observeHumanCutJob(f.context.dir).job.guidedHandoffV2?.bodyCandidateHash, committedHash);
    assert.equal(f.calls.length, 1, "only the explicitly TEST native-read leaf ran");
    assert(failure instanceof Error, "readback returned success after its original verification publication was replaced");
    assert.match(failure.message, /publication|identity|changed|record/);
  });
});
