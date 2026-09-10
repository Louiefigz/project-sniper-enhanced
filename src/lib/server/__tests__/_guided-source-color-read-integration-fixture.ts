/** Actual metadata chain and TEMP leases/CAS; native, source admission and executable qualification remain TEST-only. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { createHash, randomUUID } from "node:crypto";
import type { TestContext } from "node:test";
import { autoEditJobPath } from "../auto-edit-job-persistence";
import { autoEditRequestKey, canonicalJson, canonicalJsonSha256 } from "../auto-edit-hash";
import { observeHumanCutJob, saveHumanCutJobSnapshot } from "../human-cut-acceptance-store";
import { writeGuidedObject } from "../guided-cut-v2-store";
import { readStoppedOpeningProcess } from "../guided-opening-process";
import { readSourceColorCleanupAttempt } from "../guided-source-color-cleanup-attempt-read";
import { recordSourceColorCleanupAttempt } from "../guided-source-color-cleanup-attempt";
import { runSourceColorCleanupProcess } from "../guided-source-color-cleanup-process";
import { captureSourceColorCleanupMedia } from "../guided-source-color-cleanup-attempt-media";
import { commitPreparedSourceColorCleanup } from "../guided-source-color-cleanup-pending-commit";
import { readRetainedSourceColorCleanupPending, readSourceColorCleanupPending } from "../guided-source-color-cleanup-pending-read";
import { retirePreparedSourceColorReservation } from "../guided-source-color-reservation-retirement";
import { commitRetiredSourceColorCleanup } from "../guided-source-color-cleanup-final-commit";
import { readFinalSourceColorCleanupForJournal } from "../guided-source-color-cleanup-final-read";
import { openingCleanupStoreDependencies, readCommittedOpeningCleanup } from "../guided-opening-cleanup-store";
import { readHeldSourceColorOpeningResult } from "../guided-source-color-opening-result";
import { holdSourceColorReadInvocation } from "../guided-source-color-read-transport";
import { cleanupPendingCommitFixture } from "./_guided-source-color-cleanup-pending-commit-fixture";
import { cleanupPendingReadLeaves } from "./_guided-source-color-cleanup-pending-read-fixture";

type Before = ReturnType<typeof cleanupPendingCommitFixture>;
export type FinalReadSetup = (job: Before["before"]["job"], root: string) => void;
const hash = (bytes: string | Buffer) => createHash("sha256").update(bytes).digest("hex");

/** Only three pre-capture protocol leaves and the current TEST journal may already exist. */
function publish(f: Before, file: string, bytes: string): string {
  const root = fs.realpathSync(f.staging.root); assert(file.startsWith(root + path.sep));
  fs.mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 });
  assert.equal(fs.realpathSync(path.dirname(file)), path.dirname(file));
  const allowed = f.media.files.filter(row => ["intent", "outcome", "ledger"].includes(row.role)).map(row => row.path);
  allowed.push(autoEditJobPath(f.before.job.ctx.dir));
  const existing = fs.existsSync(file);
  if (existing) {
    assert(allowed.includes(file)); assert.equal(fs.realpathSync(file), file);
    const stat = fs.lstatSync(file); assert(stat.isFile()); assert.equal(stat.nlink, 1); assert.equal(stat.uid, process.getuid!());
  }
  fs.writeFileSync(file, bytes, { flag: existing ? "w" : "wx", mode: 0o600 }); return hash(bytes);
}

/** No installed executable is read or run: these exact bytes are inert TEST metadata. */
function toolMetadata(f: Before) {
  const root = path.join(f.staging.root, "TEST-read-tools"), tools = Object.fromEntries(["python", "ffmpeg", "ffprobe"].map(name => {
    const file = path.join(root, name), sha256 = publish(f, file, `TEST inert ${name}; never executed\n`);
    return [name, { path: file, sha256 }];
  }));
  const script = path.join(f.input.held.job.ctx.pipeline!.snapshotRoot, "scripts/producer/guided_opening_media.py");
  const scriptHash = publish(f, script, "# TEST inert media worker; never executed\n");
  const readScript = path.join(path.dirname(script), "guided_opening_read.py");
  const readHash = publish(f, readScript, "# TEST inert read worker; never executed\n");
  f.tools.runnerScriptHash = publish(f, f.tools.runnerScript, "# TEST inert runner; never executed\n");
  const process = { ...f.tools, script, scriptHash, python: tools.python.path, pythonResolved: tools.python.path,
    pythonHash: tools.python.sha256, venvRoot: root, venvConfig: path.join(root, "pyvenv.cfg"),
    venvConfigHash: publish(f, path.join(root, "pyvenv.cfg"), "TEST inert venv metadata\n") };
  return { tools, process, read: { ...process, script: readScript, scriptHash: readHash } };
}

/** Replace no immutable snapshot: this new pre-activation job has the same original claim and staged inputs. */
function priorJob(f: Before, tools: ReturnType<typeof toolMetadata>, finalize?: FinalReadSetup) {
  const job = structuredClone(f.before.job); delete job.guidedHandoffV2!.openingProcessOutcomeHash;
  for (const row of [{ path: "scripts/producer/guided_opening_media.py", hash: tools.process.scriptHash },
    { path: "scripts/producer/guided_opening_read.py", hash: tools.read.scriptHash }]) {
    const existing = job.ctx.pipeline!.files.find(item => item.path === row.path);
    if (existing) assert.deepEqual(existing, row);
    else job.ctx.pipeline!.files.push(row);
  }
  job.ctx.pipeline!.files.find(row => row.path === "scripts/producer/headless/process_runner.py")!.hash = tools.process.runnerScriptHash;
  finalize?.(job, f.staging.root);
  job.requestKey = autoEditRequestKey(job.ctx);
  const sha256 = canonicalJsonSha256(job), file = path.join(job.ctx.dir, "human-cut-job-snapshots", `${sha256}.json`);
  publish(f, file, canonicalJson(job)); return { job, sha256, file };
}

/** Metadata stat targets only, not playable video. Publish before the first result or native-read capture. */
function defaultPicture(f: Before): ReadIntegrationPicture {
  const rows = [30, 60].map((frames, index) => {
    const file = path.join(f.input.held.claim.outputRoot, `${index ? "review" : "core"}.mp4`);
    const bytes = `TEST inert ${frames}-frame private range; never decoded\n`, sha256 = publish(f, file, bytes);
    return { path: file, sha256, sizeBytes: Buffer.byteLength(bytes), startFrame: 0, endFrameExclusive: frames,
      startSample: 0, endSampleExclusive: frames * 1600 };
  });
  return { authority: { frameRate: "30/1", target: { width: 160, height: 90 },
    core: { startFrame: 0, endFrameExclusive: 30 }, review: { startFrame: 0, endFrameExclusive: 60 } },
  media: { core: rows[0], review: rows[1] } };
}

/** Schema2 completion describes only inert TEST metadata; evidence/media bytes are deliberately not qualified. */
function mediaResult(f: Before, tools: ReturnType<typeof toolMetadata>, picture?: ReadIntegrationPicture) {
  const held = f.input.held, claim = held.claim, output = claim.outputRoot, file = path.join(output, "media-result.json");
  fs.mkdirSync(path.join(output, "audio"), { recursive: true, mode: 0o700 });
  const evidence = { path: path.join(output, "source-color-evidence.json"), sha256: hash("TEST evidence not replayed"),
    sizeBytes: 128, receiptHash: hash("TEST evidence semantic identity") };
  const body = { schemaVersion: 2, kind: "guided-opening-media-result", status: "complete",
    scope: "private-opening-media-not-opening-body-or-delivery-approval", executionId: claim.executionId,
    inputPath: claim.inputPath, inputSha256: claim.inputSha256, executionInputHash: claim.executionInputHash,
    executionClaim: { path: held.claimPath, sha256: held.claimSha256 }, pipeline: { tools: tools.tools },
    sourceColorEvidence: evidence, ...picture, openingApproved: false, deliveryApproved: false };
  const receiptHash = canonicalJsonSha256(body), record = { ...body, receiptHash }, receiptSha256 = publish(f, file, canonicalJson(record));
  const completion = { schemaVersion: 2, kind: "guided-opening-media-completion", status: "complete", executionId: claim.executionId,
    inputSha256: claim.inputSha256, executionInputHash: claim.executionInputHash, executionClaimSha256: held.claimSha256,
    receiptPath: file, receiptSha256, receiptHash, sourceColorEvidence: evidence, openingApproved: false, deliveryApproved: false };
  return { file, record, completion };
}

/** All protocol publication precedes the first actual media/attempt capture; old TEST activation facts remain untouched. */
function publishMedia(f: Before, picture?: ReadIntegrationPicture, finalize?: FinalReadSetup) {
  const held = f.input.held, tools = toolMetadata(f), prior = priorJob(f, tools, finalize), result = mediaResult(f, tools, picture);
  const execution = path.dirname(held.claimPath), at = (second: string) => held.claim.generationStartedAt.replace("00.000Z", `${second}.000Z`);
  const ledger = ["worker-started", "worker-finished"].map((event, index) =>
    JSON.stringify({ event, pid: process.pid, argv0: tools.process.script, at: 1000 + index })).join("\n") + "\n";
  const ledgerSha256 = publish(f, path.join(execution, "owned-process-ledger.media.jsonl"), ledger);
  const intent = { schemaVersion: 3, kind: "guided-opening-process-intent", claimHash: held.claimHash,
    inputSha256: held.claim.inputSha256, executionId: held.claim.executionId, journalHash: prior.sha256,
    clockHash: held.claim.clockHash, generationStartedAt: held.claim.generationStartedAt, startedAt: at("01"),
    sourceColor: f.actual.sourceColor, tools: tools.process };
  const intentHash = publish(f, path.join(execution, "media-process-intent.json"), canonicalJson(intent));
  const outcome = { schemaVersion: 3, kind: "guided-opening-process-outcome", scope: "owned-process-stop-not-media-or-delivery-approval",
    intentHash, claimHash: held.claimHash, inputSha256: held.claim.inputSha256, executionId: held.claim.executionId,
    startedAt: at("01"), finishedAt: at("02"), elapsedMs: 1000, status: "complete", error: "", timedOut: false,
    groupStopped: true, forcedStop: false, stdout: JSON.stringify(result.completion), stderr: "TEST no native media", ledgerSha256 };
  const outcomeSha256 = publish(f, path.join(execution, "media-process-result.json"), canonicalJson(outcome));
  const activation = { schemaVersion: 2, kind: "guided-opening-process-activation", scope: "actual-owned-process-outcome-not-media-or-delivery-approval",
    claimHash: held.claimHash, beforeJournalHash: prior.sha256, executionId: held.claim.executionId, inputSha256: held.claim.inputSha256,
    intentSha256: intentHash, outcomeSha256, clockHash: held.claim.clockHash, generationStartedAt: held.claim.generationStartedAt, createdAt: at("03") };
  prior.job.guidedHandoffV2!.openingProcessOutcomeHash = writeGuidedObject(prior.job.ctx.dir, activation); prior.job.updatedAt = at("03");
  publish(f, autoEditJobPath(prior.job.ctx.dir), canonicalJson(prior.job));
  f.before = observeHumanCutJob(prior.job.ctx.dir); saveHumanCutJobSnapshot(prior.job.ctx.dir, f.before); Object.assign(held, f.before);
  f.media.files.length = 0;
  captureSourceColorCleanupMedia(held, ref => { f.media.files.push(ref); return fs.readFileSync(ref.path); });
  assert.equal(readStoppedOpeningProcess(held).nestedOwnership, "resolved-by-normal-return");
  return { ...result, tools, priorPath: prior.file };
}

/** Original small staged controls are verified unchanged; no source or dependency inventory is read. */
function originalInputs(f: Before) {
  const files = [f.input.held.claimPath, f.input.held.claim.inputPath, f.staged.input.path, f.staged.reservation.path];
  const originals = files.map(file => ({ file, bytes: fs.readFileSync(file), stat: fs.lstatSync(file, { bigint: true }) }));
  const check = () => {
    for (const row of originals) {
      assert.deepEqual(fs.readFileSync(row.file), row.bytes);
      assert.deepEqual(fs.lstatSync(row.file, { bigint: true }), row.stat);
    }
  };
  return { originals, check };
}

/** Actual record, both CASes, retirement and final store; only original claim admission/native tool invocation are TEST leaves. */
async function finalCleanup(t: TestContext, f: Before) {
  const recorded = await recordSourceColorCleanupAttempt(f.writerInput, { stopped: readStoppedOpeningProcess,
    read: readSourceColorCleanupAttempt, run: input => runSourceColorCleanupProcess(input,
      { ...f.dependencies, stopped: readStoppedOpeningProcess }) });
  commitPreparedSourceColorCleanup(recorded);
  const leaves = { claim: cleanupPendingReadLeaves(f).claim, attempt: readSourceColorCleanupAttempt };
  const history = (input: Parameters<typeof readRetainedSourceColorCleanupPending>[0], sha: string) => readRetainedSourceColorCleanupPending(input, sha, leaves);
  const pending = readSourceColorCleanupPending({ dir: f.before.job.ctx.dir, guard: f.assertLeases,
    remainingMs: f.writerInput.clock.remainingMs }, leaves);
  const retired = retirePreparedSourceColorReservation({ pending, projectLease: f.projectLease, resource: f.staging.resource },
    { workspace: () => f.staging.root });
  const committed = commitRetiredSourceColorCleanup(retired, { history });
  const current = observeHumanCutJob(f.before.job.ctx.dir); saveHumanCutJobSnapshot(current.job.ctx.dir, current);
  t.mock.method(openingCleanupStoreDependencies, "final", (input: Parameters<typeof readFinalSourceColorCleanupForJournal>[0]) =>
    readFinalSourceColorCleanupForJournal(input, { history }));
  const cleanup = readCommittedOpeningCleanup(current.job.ctx.dir);
  return { cleanup, recorded, pending, retired, committed, current };
}

/** Genuine SAME-held capabilities are composed only after the original actual final store read returns. */
export interface ReadIntegrationPicture { authority: Record<string, unknown>; media: Record<string, unknown> }
export async function sourceColorReadIntegrationFixture(t: TestContext, f = cleanupPendingCommitFixture(t), picture?: ReadIntegrationPicture, finalize?: FinalReadSetup) {
  const original = originalInputs(f), oldMedia = f.media.files.map(row => ({ ...row }));
  const media = publishMedia(f, picture ?? defaultPicture(f), finalize); original.check(); f.input.reservation.assertCurrent();
  for (const row of oldMedia.filter(row => ["activation", "priorJournal"].includes(row.role))) assert.equal(hash(fs.readFileSync(row.path)), row.sha256);
  const final = await finalCleanup(t, f);
  const selected = readHeldSourceColorOpeningResult({ held: final.cleanup.held, guard: () => {} });
  const invocation = holdSourceColorReadInvocation({ cleanup: final.cleanup, selected });
  const stable = original.originals.slice(0, 3);
  for (const row of stable) { assert.deepEqual(fs.readFileSync(row.file), row.bytes); assert.deepEqual(fs.lstatSync(row.file, { bigint: true }), row.stat); }
  assert.deepEqual(fs.readFileSync(final.recorded.fact.archive.path), original.originals[3].bytes);
  return { ...f, ...final, media, selected, invocation, original: original.originals };
}
export type SourceColorReadIntegrationFixture = Awaited<ReturnType<typeof sourceColorReadIntegrationFixture>>;

/** Fault permission is only this exact final archive, never a held dependency or arbitrary caller-selected file. */
export function replaceReadIntegrationArchive(f: SourceColorReadIntegrationFixture): void {
  const file = f.recorded.fact.archive.path, root = fs.realpathSync(f.staging.root);
  assert(file.startsWith(root + path.sep)); assert.equal(fs.realpathSync(file), file);
  assert.equal(fs.realpathSync(path.dirname(file)), path.dirname(file));
  const stat = fs.lstatSync(file); assert(stat.isFile()); assert.equal(stat.nlink, 1); assert.equal(stat.uid, process.getuid!());
  const temporary = path.join(path.dirname(file), `TEST-read-archive-${randomUUID()}.json`);
  fs.writeFileSync(temporary, fs.readFileSync(file), { flag: "wx", mode: 0o600 }); fs.renameSync(temporary, file);
}
