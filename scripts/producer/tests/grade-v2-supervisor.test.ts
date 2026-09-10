/** Actual blocked Node/Python pipe and processes; explicitly fake metadata worker, no daemon. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { startSupervisor, closeBlockedSupervisor, invokeSupervisor } from "./live_grade_v2_supervisor";
import { groupState } from "./live_grade_v2_lifecycle";
import { writeHeldRecord } from "./live_grade_v2_finalization";

const REPO = path.dirname(fs.realpathSync("src"));
const TEST_WORKER = `"""TEST pipe only. No source, Docker, observation, or approval."""
import json,sys,time
print(json.dumps({"readyMonotonicNs":str(time.monotonic_ns())}),flush=True)
deadline=json.loads(sys.stdin.readline())["deadlineMonotonicNs"]
assert time.monotonic_ns()<int(deadline)
print(json.dumps({"resultSha256":"a"*64,"cleanupVerified":True,"status":"failed"}),flush=True)
`;
function scaffold() {
  const root = fs.mkdtempSync("/private/tmp/TEST-v2-supervisor-pipe-"), scripts = path.join(root, "scripts/producer");
  fs.mkdirSync(path.join(scripts, "tests"), { recursive: true, mode: 0o700 });
  for (const name of ["cut_preview_io.py", "cross_runtime_canonical_json.py"])
    fs.copyFileSync(path.join(REPO, "scripts/producer", name), path.join(scripts, name));
  fs.copyFileSync(path.join(__dirname, "live_grade_v2_supervisor.py"), path.join(scripts, "tests/live_grade_v2_supervisor.py"));
  fs.writeFileSync(path.join(scripts, "tests/live_grade_v2_launch.py"), TEST_WORKER);
  return { root, scripts, python: path.join(REPO, ".venv/bin/python3"), deadline: process.hrtime.bigint() + BigInt(4_000_000_000) };
}
function permit(f: ReturnType<typeof scaffold>, supervisor: Awaited<ReturnType<typeof startSupervisor>>) {
  const directory = path.join(f.root, "7758dfae-d894-4845-9bc5-b6870715640d"), resource = path.join(f.root, "TEST-resource");
  fs.mkdirSync(directory, { mode: 0o700 }); fs.mkdirSync(resource, { mode: 0o700 });
  const inputSha = writeHeldRecord(path.join(directory, "input.json"), { jobId: path.basename(directory), ownerPid: supervisor.identity.pid });
  // Fake metadata tests ONLY the actual two-stage owned pipe. This is not a
  // production v2Input/lifecycle and never reaches readLifecycle or finalization.
  const lifecycleSha256 = writeHeldRecord(path.join(directory, "TEST-lifecycle.json"), { directory, resource, python: f.python,
    supervisor: supervisor.identity, owner: { pid: process.pid }, producerDir: f.root,
    inputSha256: inputSha, supervisorDeadlineNs: supervisor.deadlineNs, pins: [] });
  const claimPath = path.join(resource, "active.json"), claimSha256 = writeHeldRecord(claimPath, {
    jobId: path.basename(directory), dir: f.root, requestDigest: inputSha, lifecycleSha256 });
  return { directory, lifecycleSha256, claimPath, claimSha256, inputSha };
}
test("real supervisor is blocked and identified before any TEST claim, EOF leaves no group", async () => {
  const f = scaffold();
  try {
    const held = await startSupervisor(f);
    assert.equal(groupState(held.identity.pid), "present"); assert.equal(fs.existsSync(path.join(f.root, "TEST-resource")), false);
    await closeBlockedSupervisor(held); assert.equal(groupState(held.identity.pid), "absent");
  } finally { fs.rmSync(f.root, { recursive: true }); }
});
test("exact permit then worker handshake uses original remainder and waits real whole-group absence", async () => {
  const f = scaffold();
  try {
    const held = await startSupervisor(f), value = permit(f, held);
    const { inputSha, ...activation } = value;
    const result = await invokeSupervisor(held, { root: f.root, directory: value.directory, inputHash: inputSha, deadline: f.deadline }, activation);
    assert.equal(result.held.status, "failed"); assert.equal(result.closed.absent, true);
    assert.equal(result.closed.code, 0); assert.equal(groupState(held.identity.pid), "absent");
    assert.ok(result.held.handshake!.remainingMs < 4000);
    assert.ok(fs.existsSync(value.claimPath), "pipe-only test never finalizes or releases the TEST claim");
  } finally { fs.rmSync(f.root, { recursive: true }); }
});
test("changed original claim rejects activation before fake inner worker fork", async () => {
  const f = scaffold();
  try {
    const held = await startSupervisor(f), value = permit(f, held), { inputSha, ...activation } = value;
    fs.chmodSync(value.claimPath, 0o600); fs.writeFileSync(value.claimPath, "{}");
    const result = await invokeSupervisor(held, { root: f.root, directory: value.directory, inputHash: inputSha, deadline: f.deadline }, activation);
    assert.equal(result.held.status, "interrupted"); assert.equal(result.held.handshake, null);
    assert.equal(result.closed.absent, true); assert.equal(groupState(held.identity.pid), "absent");
    assert.equal(result.stdout, "");
  } finally { fs.rmSync(f.root, { recursive: true }); }
});
test("normal leader return with an ignored-stdio descendant is not quiescent completion", async () => {
  const f = scaffold();
  try {
    const extra = "import subprocess,os\nsubprocess.Popen([sys.executable,'-c','import time;time.sleep(.4)'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)\n";
    fs.writeFileSync(path.join(f.scripts, "tests/live_grade_v2_launch.py"), TEST_WORKER.replace('print(json.dumps({"resultSha256"', extra + 'print(json.dumps({"resultSha256"'));
    const held = await startSupervisor(f), value = permit(f, held), { inputSha, ...activation } = value;
    const result = await invokeSupervisor(held, { root: f.root, directory: value.directory, inputHash: inputSha, deadline: f.deadline }, activation);
    assert.equal(result.held.status, "interrupted"); assert.equal(result.closed.absent, false);
    assert.ok(fs.existsSync(value.claimPath));
    await new Promise(resolve => setTimeout(resolve, 600));
    assert.equal(groupState(held.identity.pid), "absent");
  } finally { fs.rmSync(f.root, { recursive: true }); }
});
