import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtempSync, rmSync, utimesSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  SupervisorConfigError,
  acquireSupervisorLock,
  assertLocalForwarding,
  buildNextArgs,
  createRestartTracker,
  effectivePort,
  heartbeatSupervisorLock,
  loadSupervisorEnvironment,
  nextNodeOptions,
  parseSupervisorArgs,
  processGroupAlive,
  releaseSupervisorLock,
  supervisorRoot,
  terminateResidualGroup,
} from "../infra/next_supervisor.mjs";

function testArguments() {
  assert.equal(supervisorRoot(), path.resolve(process.cwd()));
  const parsed = parseSupervisorArgs(["dev", "--local", "--webpack", "--port", "3101"]);
  assert.deepEqual(parsed, {
    command: "dev",
    local: true,
    forwarded: ["--webpack", "--port", "3101"],
  });
  assert.deepEqual(buildNextArgs(parsed, "/next"), [
    "/next", "dev", "--webpack", "--port", "3101", "--hostname", "127.0.0.1",
  ]);
  assert.equal(effectivePort(parsed.forwarded), "3101");
  assert.equal(effectivePort(["--port=3102"], { PORT: "3100" }), "3102");
  assert.throws(() => parseSupervisorArgs(["build"]), SupervisorConfigError);
  assert.throws(() => effectivePort(["--port", "nope"]), SupervisorConfigError);
  assert.throws(() => assertLocalForwarding(["--hostname=0.0.0.0"]), SupervisorConfigError);
}

function testHeapOptions() {
  assert.equal(nextNodeOptions({}), "--max-old-space-size=3072");
  assert.equal(nextNodeOptions({ SNIPER_NEXT_HEAP_MB: "4096" }), "--max-old-space-size=4096");
  assert.equal(
    nextNodeOptions({ NODE_OPTIONS: "--trace-warnings --max_old_space_size=2048", SNIPER_NEXT_HEAP_MB: "4096" }),
    "--trace-warnings --max_old_space_size=2048",
  );
  assert.throws(() => nextNodeOptions({ SNIPER_NEXT_HEAP_MB: "3GB" }), SupervisorConfigError);
}

function testEnvFileHeap() {
  const root = mkdtempSync(path.join(os.tmpdir(), "sniper-supervisor-env-"));
  const previous = process.env.SNIPER_NEXT_HEAP_MB;
  try {
    delete process.env.SNIPER_NEXT_HEAP_MB;
    writeFileSync(path.join(root, ".env.local"), "SNIPER_NEXT_HEAP_MB=5120\n");
    loadSupervisorEnvironment(root, true);
    assert.match(nextNodeOptions(), /--max-old-space-size=5120$/);
  } finally {
    if (previous === undefined) delete process.env.SNIPER_NEXT_HEAP_MB;
    else process.env.SNIPER_NEXT_HEAP_MB = previous;
    rmSync(root, { recursive: true, force: true });
  }
}

function testRestartCircuit() {
  let now = 0;
  const fast = createRestartTracker(() => now);
  assert.equal(fast.record(1_000).stop, false);
  now += 1_000;
  assert.equal(fast.record(1_000).stop, false);
  now += 1_000;
  const fastStop = fast.record(1_000);
  assert.equal(fastStop.stop, true);
  assert.equal(fastStop.fastLoop, true);
  const repeated = createRestartTracker(() => now);
  for (let count = 1; count < 5; count += 1) {
    assert.equal(repeated.record(45_000).stop, false);
    now += 60_000;
  }
  assert.equal(repeated.record(45_000).stop, true);
}

function testPortLock() {
  const root = mkdtempSync(path.join(os.tmpdir(), "sniper-supervisor-lock-"));
  const lockPath = path.join(root, "server.pid");
  try {
    acquireSupervisorLock(lockPath);
    assert.throws(() => acquireSupervisorLock(lockPath), /owns this port/);
    assert.equal(heartbeatSupervisorLock(lockPath), true);
    releaseSupervisorLock(lockPath);
    writeFileSync(lockPath, "");
    assert.throws(() => acquireSupervisorLock(lockPath), /acquiring this port/);
    rmSync(lockPath, { force: true });
    writeFileSync(lockPath, "99999999\n");
    acquireSupervisorLock(lockPath);
    releaseSupervisorLock(lockPath);
    writeFileSync(lockPath, `${process.pid}\n`);
    const stale = new Date(Date.now() - 6 * 60_000);
    utimesSync(lockPath, stale, stale);
    acquireSupervisorLock(lockPath);
    releaseSupervisorLock(lockPath);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
}

function childPid(child) {
  return new Promise((resolve, reject) => {
    let output = "";
    child.stdout.on("data", (chunk) => {
      output += String(chunk);
      const match = output.match(/\d+/);
      if (match) resolve(Number(match[0]));
    });
    child.once("error", reject);
    child.once("close", () => reject(new Error("process group closed before reporting its child")));
  });
}

async function testProcessGroupCleanup() {
  if (process.platform === "win32") return;
  const program = [
    "const {spawn}=require('node:child_process');",
    "const kid=spawn(process.execPath,['-e','setInterval(()=>{},1000)'],{stdio:'ignore'});",
    "console.log(kid.pid); setInterval(()=>{},1000);",
  ].join("");
  const child = spawn(process.execPath, ["-e", program], {
    detached: true,
    stdio: ["ignore", "pipe", "ignore"],
  });
  try {
    const kid = await childPid(child);
    assert.equal(processGroupAlive(child.pid), true);
    assert.equal(await terminateResidualGroup(child.pid), true);
    assert.equal(processGroupAlive(child.pid), false);
    assert.throws(() => process.kill(kid, 0));
  } finally {
    if (processGroupAlive(child.pid)) {
      try { process.kill(-child.pid, "SIGKILL"); } catch {}
    }
  }
}

async function main() {
  testArguments();
  testHeapOptions();
  testEnvFileHeap();
  testRestartCircuit();
  testPortLock();
  await testProcessGroupCleanup();
  console.log("next_supervisor.test.mjs: all assertions passed");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
