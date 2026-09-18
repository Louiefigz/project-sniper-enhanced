/** Opt-in actual V2 owner pipe. TEST-only; never imported by production routes. */
import fs from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
import { pythonInterpreter } from "../../../src/app/api/_lib/spawn-python";
import { readBytes, sha } from "../../../src/app/api/producer/studio/import/files";
import { checkTime, object, privateDirectory, readRecord, sourceInventory } from "../../../src/lib/server/grade-observation-store";
import { assertLiveReturn, assertResult, assertSameParents, fixtureProducer, v2Input, WORK_NS } from "./live_grade_v2_contract";

import { finalizeV2Success, readCleanupProof, releaseV2Failed, writeHeldRecord as writeRecord, type V2LiveReturn,
  type V2Finalization } from "./live_grade_v2_finalization";

import { startSupervisor, invokeSupervisor, closeBlockedSupervisor, type V2Supervisor } from "./live_grade_v2_supervisor";
import { acquireV2Scope as acquire, exactIdentity, groupState, retainLifecycle, runtimeV2, pinV2, checkPinsV2,
  type V2Lifecycle } from "./live_grade_v2_lifecycle";
import { recoverV2Owner } from "./live_grade_v2_recovery";
function bytes(file: string, maximum = 8 * 1024 * 1024): string { return sha(readBytes(file, maximum)); }
function toolsHeld(root: string) {
  const python = pythonInterpreter(), script = path.join(root, "scripts/producer/color/grade_project_worker.py");
  if (!path.isAbsolute(python) || !["darwin", "linux"].includes(process.platform)) throw new Error("Existing POSIX venv required");
  const files = [script, fs.realpathSync(python), path.join(path.dirname(path.dirname(python)), "pyvenv.cfg"),
    path.join(root, "src/lib/server/atomic-file.ts"),
    ...["live_grade_v2_owner.ts", "live_grade_v2_contract.ts", "live_grade_v2_fixture.py", "live_grade_v2_finalization.ts", "live_grade_v2_lifecycle.ts",
      "live_grade_v2_supervisor.ts", "live_grade_v2_supervisor.py",  "live_grade_v2_launch.py",
      "live_grade_v2_recovery.ts"]
      .map(name => path.join(root, "scripts/producer/tests", name))];
  const hashes = files.map(file => bytes(file, 128 * 1024 * 1024));
  return { python, script, files, check: () => {
    if (files.some((file, index) => bytes(file, 128 * 1024 * 1024) !== hashes[index])) throw new Error("Held worker/interpreter changed");
  } };
}
function create(dir: string, root: string, context: { deadline: bigint; ownerPid: number }) {
  const store = privateDirectory(path.join(dir, ".sniper-grade-observations"), true), jobId = randomUUID();
  const directory = path.join(store, jobId);
  fs.mkdirSync(directory, { mode: 0o700 });
  const inventory = sourceInventory(root, context.deadline);
  const implementationSha = writeRecord(path.join(directory, "implementation.json"), inventory);
  const input = v2Input(dir, jobId, implementationSha, context.ownerPid), inputHash = writeRecord(path.join(directory, "input.json"), input);
  return { input, inputHash, directory, inventory };
}
function verify(job: ReturnType<typeof create>, liveSha: string) {
  const file = path.join(job.directory, "observation.json");
  if (bytes(file) !== liveSha) throw new Error("Actual owner-returned result bytes changed");
  const value = readRecord(file), observation = assertResult(value, job.input, job.inputHash);
  const execution = path.join(job.directory, "execution/execution.json");
  if (bytes(execution) !== observation.executionSha256) throw new Error("Held execution bytes changed");
  const row = readRecord(execution), worker = object(row.worker), removal = object(row.removal);
  if (row.status !== "complete" || row.cleanupVerified !== true || removal.canonicalAbsenceProved !== true
      || row.sourceBeforeSha256 !== row.sourceAfterSha256 || object(worker.decoder).frames !== 24
      || object(worker.decoder).sha256 !== observation.rawFramesSha256) throw new Error("Actual full decoder or cleanup proof differs");
  const rawDir = path.join(job.directory, "execution/result");
  if (bytes(path.join(rawDir, "frames.ffprobe")) !== observation.rawFramesSha256
      || bytes(path.join(rawDir, "probe.json")) !== observation.rawProbeSha256) throw new Error("Raw EOF/probe records changed");
  const source = object((readRecord(path.join(job.input.producerDir, "asset_manifest.json")).sources as unknown[])[0]);
  if (bytes(String(source.path)) !== object(observation.source).sourceSha256
      || source.sourceSha256 !== object(observation.source).sourceSha256) throw new Error("Actual admitted snapshot changed");
  if (bytes(file) !== liveSha || bytes(execution) !== observation.executionSha256) throw new Error("Final receipt recheck failed");
  return observation;
}
interface OwnerState {
  claimed: boolean; job?: ReturnType<typeof create>; claimFile?: string; claimSha?: string;
  live?: V2LiveReturn; candidate?: { path: string; sha256: string };
  supervisor?: V2Supervisor; lifecycle?: V2Lifecycle; lifecycleSha?: string; activated?: boolean;
}
interface OwnerContext {
  root: string; dir: string; started: bigint; deadline: bigint;
  tools: ReturnType<typeof toolsHeld>; scope: ReturnType<typeof acquire>;
}
function completeState(state: OwnerState) {
  if (!state.job || !state.claimFile || !state.claimSha || !state.live) throw new Error("Actual return/claim is unavailable; retain fence");
  return { job: state.job, claimFile: state.claimFile, claimSha: state.claimSha, live: state.live };
}
function heldFinalization(state: OwnerState, deadline: bigint): V2Finalization {
  const { job, claimFile, claimSha, live } = completeState(state);
  if (!live.held.resultSha256) throw new Error("No actual held result hash; retain fence");
  return { live, input: { path: path.join(job.directory, "input.json"), sha256: job.inputHash },
    result: { path: path.join(job.directory, "observation.json"), sha256: live.held.resultSha256 },
    claim: { path: claimFile, sha256: claimSha }, candidate: state.candidate, deadline };
}
function currentCleanup(state: OwnerState, context: OwnerContext, deadline: bigint): void {
  const { job, live } = completeState(state);
  context.scope.guard(); checkTime(deadline); context.tools.check();
  if (!state.lifecycle || JSON.stringify(runtimeV2(context.root)) !== JSON.stringify(state.lifecycle.runtime))
    throw new Error("Original runtime changed");
  checkPinsV2(state.lifecycle.pins);
  if (!live.pid || groupState(live.pid) !== "absent") throw new Error("Current owned process group absence is unproved");
  if (JSON.stringify(sourceInventory(context.root, deadline)) !== JSON.stringify(job.inventory))
    throw new Error("Original observer implementation changed; cleanup authority unavailable");
  readCleanupProof(job.directory, job.input, job.inputHash, live);
  context.scope.guard(); checkTime(deadline);
}
function finalChecks(state: OwnerState, context: OwnerContext, deadline: bigint, success: boolean) {
  return { ownership: context.scope.guard,
    parents: () => assertSameParents(context.dir, completeState(state).job.input.expected),
    proof: () => {
      currentCleanup(state, context, deadline);
      if (success) {
        const { job, live } = completeState(state);
        verify(job, live.held.resultSha256!);
      }
    } };
}
async function prepareActivation(context: OwnerContext, state: OwnerState) {
  const { root, dir, deadline, tools, scope, started } = context;
  scope.guard(); fixtureProducer(dir); checkTime(deadline); // Recheck bounded TEST intake under the acquired lease.
  const supervisor = await startSupervisor({ root, python: tools.python, deadline }); state.supervisor = supervisor;
  const job = create(dir, root, { deadline, ownerPid: supervisor.identity.pid }); state.job = job;
  const source = object((readRecord(path.join(dir, "asset_manifest.json")).sources as unknown[])[0]);
  const lifecycle: V2Lifecycle = { schemaVersion: 1, kind: "TEST-grade-v2-lifecycle", root, producerDir: dir,
    directory: job.directory, resource: scope.resource, python: tools.python, inputSha256: job.inputHash, owner: exactIdentity(process.pid),
    supervisor: supervisor.identity, startedNs: String(started), deadlineNs: String(deadline),
    supervisorDeadlineNs: supervisor.deadlineNs, containerName: "sniper-grade-observation-" + job.input.jobId.replaceAll("-", ""),
    source: { path: String(source.path), sha256: String(source.sourceSha256) }, runtime: runtimeV2(root),
    pins: pinV2([...tools.files, ...job.inventory.files.map(row => row.path)]) };
  state.lifecycle = lifecycle; state.lifecycleSha = retainLifecycle(lifecycle);
  state.claimFile = path.join(scope.resource, "active.json");
  state.claimed = true; // An uncertain O_EXCL publication remains fenced.
  state.claimSha = writeRecord(state.claimFile, { jobId: job.input.jobId, dir, requestDigest: job.inputHash, lifecycleSha256: state.lifecycleSha });
  scope.guard(); checkTime(deadline);
  return { job, supervisor, lifecycleSha: state.lifecycleSha, claimFile: state.claimFile, claimSha: state.claimSha };
}
async function executeOwner(context: OwnerContext, state: OwnerState): Promise<Record<string, unknown>> {
  const { root, dir, deadline, started, tools, scope } = context;
  const { job, supervisor, lifecycleSha, claimFile, claimSha } = await prepareActivation(context, state);
  state.activated = true;
  state.live = await invokeSupervisor(supervisor, { root, directory: job.directory, inputHash: job.inputHash, deadline },
    { directory: job.directory, lifecycleSha256: lifecycleSha, claimPath: claimFile, claimSha256: claimSha });
  writeRecord(path.join(job.directory, "TEST-owner-outcome.json"), { ...state.live,
    syntheticOnly: true, requiresActualReceiptVerification: true, selection: "live-return-only" });
  tools.check(); assertLiveReturn(state.live.held, state.live.closed);
  const observation = verify(job, state.live.held.resultSha256!);
  scope.guard(); assertSameParents(dir, job.input.expected); checkTime(deadline);
  const result = { syntheticOnly: true, status: "candidate-only", selection: "live-return-only",
    scope: "actual-owner-OCI-EOF-plumbing-not-large-source-or-color-qualification",
    directory: job.directory, resultSha256: state.live.held.resultSha256, observation,
    elapsedMs: Number(process.hrtime.bigint() - started) / 1e6, gradeApplicable: false, deliveryApproved: false };
  const candidatePath = path.join(job.directory, "TEST-result.json");
  state.candidate = { path: candidatePath, sha256: writeRecord(candidatePath, result) };
  finalizeV2Success(heldFinalization(state, deadline), finalChecks(state, context, deadline, true));
  state.claimed = false;
  return { ...result, status: "complete", elapsedMs: Number(process.hrtime.bigint() - started) / 1e6 };
}
function failureCleanup(state: OwnerState, context: OwnerContext, error: unknown): string | null {
  if (!state.claimed) return null;
  // One <=5s metadata-only release attempt, also inside original lifecycle+5s.
  // Python owns its existing90s Docker cleanup; this never spawns or renews work.
  const now = process.hrtime.bigint(), cap = context.deadline + BigInt(105_000_000_000);
  const deadline = now + BigInt(5_000_000_000) < cap ? now + BigInt(5_000_000_000) : cap;
  try {
    releaseV2Failed(heldFinalization(state, deadline), finalChecks(state, context, deadline, false), String(error));
    state.claimed = false;
    return null;
  } catch (cleanupError) { return String(cleanupError); }
}
export async function runV2Owner(raw: string): Promise<Record<string, unknown>> {
  const started = process.hrtime.bigint(), deadline = started + WORK_NS;
  const dir = fixtureProducer(raw), root = fs.realpathSync(process.cwd()), tools = toolsHeld(root);
  const scope = acquire(dir), state: OwnerState = { claimed: false };
  const context = { root, dir, started, deadline, tools, scope };
  try { return await executeOwner(context, state); }
  catch (error) {
    let cleanupError: string | null = null;
    try { if (state.supervisor && !state.activated) await closeBlockedSupervisor(state.supervisor); }
    catch (blockedError) { cleanupError = String(blockedError); }
    cleanupError ??= failureCleanup(state, context, error);
    if (state.job) {
      try {
        writeRecord(path.join(state.job.directory, "TEST-failed.json"), { error: String(error), cleanupError,
          ownershipRetained: state.claimed, elapsedMs: Number(process.hrtime.bigint() - started) / 1e6, noApproval: true });
      } catch (retentionError) {
        throw new AggregateError([error, retentionError], "V2 attempt failed; failure retention also failed");
      }
    }
    throw error;
  } finally { if (!state.claimed) scope.release(); }
}
function printResult(pending: Promise<Record<string, unknown>>): void {
  pending.then(value => console.log(JSON.stringify(value))).catch(error => {
    console.error(JSON.stringify({ ok: false, error: String(error), noApproval: true })); process.exitCode = 1;
  });
}
function main(argv: string[]): void {
  if (argv.length === 2 && argv[0] === "--run") { printResult(runV2Owner(argv[1])); return; }
  if (argv.length === 3 && argv[0] === "--recover") { printResult(recoverV2Owner(argv[1], argv[2])); return; }
  console.log("Usage: live_grade_v2_owner.ts --run EXACT_TEST_PRODUCER | --recover EXACT_TEST_PRODUCER EXACT_JOB (cleanup only)");
  if (argv.length > 1 || ![undefined, "--help"].includes(argv[0])) process.exitCode = 2;
}
if (process.argv[1]?.endsWith("/live_grade_v2_owner.ts")) main(process.argv.slice(2));
