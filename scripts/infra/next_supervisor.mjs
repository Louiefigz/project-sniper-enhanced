#!/usr/bin/env node

import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import {
  LOCK_HEARTBEAT_MS,
  acquireSupervisorLock,
  heartbeatSupervisorLock,
  releaseSupervisorLock,
  supervisorLockPath,
} from "./next_supervisor_lock.mjs";

export {
  acquireSupervisorLock,
  heartbeatSupervisorLock,
  releaseSupervisorLock,
  supervisorLockPath,
} from "./next_supervisor_lock.mjs";

const require = createRequire(import.meta.url);
const { loadEnvConfig } = require("@next/env");

export function supervisorRoot(moduleUrl = import.meta.url) {
  return path.resolve(path.dirname(fileURLToPath(moduleUrl)), "..", "..");
}

const ROOT = supervisorRoot();
const NEXT_BIN = path.join(ROOT, "node_modules", "next", "dist", "bin", "next");
const FAST_EXIT_MS = 30_000;
const MAX_FAST_EXITS = 3;
const EXIT_WINDOW_MS = 10 * 60_000;
const MAX_WINDOW_EXITS = 5;
const RESTART_DELAY_MS = 1_000;
const SHUTDOWN_GRACE_MS = 5_000;
const GROUP_CLEANUP_MS = 1_500;

export class SupervisorConfigError extends Error {}

export function parseSupervisorArgs(argv) {
  const [command, ...rest] = argv;
  if (command !== "dev" && command !== "start") {
    throw new SupervisorConfigError("Usage: next_supervisor.mjs <dev|start> [--local] [Next options]");
  }
  const forwarded = [];
  let local = false;
  for (const arg of rest) {
    if (arg === "--local") local = true;
    else forwarded.push(arg);
  }
  return { command, local, forwarded };
}

function optionValue(args, shortName, longName) {
  let value;
  for (let index = 0; index < args.length; index += 1) {
    const arg = args[index];
    if (arg === shortName || arg === longName) {
      if (index + 1 >= args.length) throw new SupervisorConfigError(`${arg} requires a value`);
      value = args[index + 1];
    } else if (arg.startsWith(`${longName}=`)) {
      value = arg.slice(longName.length + 1);
    }
  }
  return value;
}

export function effectivePort(forwarded, env = process.env) {
  const raw = optionValue(forwarded, "-p", "--port") ?? env.PORT ?? "3000";
  if (!/^\d+$/.test(String(raw)) || Number(raw) > 65_535) {
    throw new SupervisorConfigError(`Invalid Next port: ${raw}`);
  }
  return String(raw);
}

export function assertLocalForwarding(forwarded) {
  const override = forwarded.find((arg) =>
    arg === "-H" || arg === "--hostname" || arg.startsWith("--hostname="),
  );
  if (override) {
    throw new SupervisorConfigError(`${override} cannot override the loopback binding in local mode`);
  }
}

export function nextNodeOptions(env = process.env) {
  const current = env.NODE_OPTIONS ?? "";
  if (/--max[-_]old[-_]space[-_]size(?:=|\s|$)/.test(current)) return current;
  const raw = env.SNIPER_NEXT_HEAP_MB ?? "3072";
  if (!/^\d+$/.test(raw) || Number(raw) < 256 || Number(raw) > 131_072) {
    throw new SupervisorConfigError("SNIPER_NEXT_HEAP_MB must be an integer from 256 to 131072");
  }
  return `${current} --max-old-space-size=${raw}`.trim();
}

export function buildNextArgs(config, nextBin = NEXT_BIN) {
  return [
    nextBin,
    config.command,
    ...config.forwarded,
    ...(config.local ? ["--hostname", "127.0.0.1"] : []),
  ];
}

export function createRestartTracker(now = () => Date.now()) {
  let fastExits = [];
  let allExits = [];
  return {
    record(runtimeMs) {
      const at = now();
      fastExits = fastExits.filter((item) => at - item < FAST_EXIT_MS);
      allExits = allExits.filter((item) => at - item < EXIT_WINDOW_MS);
      if (runtimeMs < FAST_EXIT_MS) fastExits.push(at);
      allExits.push(at);
      const fastLoop = fastExits.length >= MAX_FAST_EXITS;
      const repeatedLoop = allExits.length >= MAX_WINDOW_EXITS;
      return { stop: fastLoop || repeatedLoop, fastLoop, fastCount: fastExits.length, exitCount: allExits.length };
    },
  };
}

export function processGroupAlive(pid) {
  if (process.platform === "win32" || !pid) return false;
  try { process.kill(-pid, 0); return true; } catch { return false; }
}

export function signalProcessTree(run, signal) {
  if (!run?.pid) return;
  try {
    if (process.platform === "win32") run.child.kill(signal);
    else process.kill(-run.pid, signal);
  } catch (error) {
    if (error?.code !== "ESRCH") console.error(`[sniper:supervisor] Could not signal Next: ${error.message}`);
  }
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export async function terminateResidualGroup(pid) {
  if (process.platform === "win32" || !pid || !processGroupAlive(pid)) return true;
  try { process.kill(-pid, "SIGTERM"); } catch {}
  const deadline = Date.now() + GROUP_CLEANUP_MS;
  while (processGroupAlive(pid) && Date.now() < deadline) await delay(50);
  if (processGroupAlive(pid)) {
    try { process.kill(-pid, "SIGKILL"); } catch {}
    await delay(100);
  }
  return !processGroupAlive(pid);
}

class NextSupervisor {
  constructor(config, lockPath) {
    this.config = config;
    this.lockPath = lockPath;
    this.args = buildNextArgs(config);
    this.tracker = createRestartTracker();
    this.active = null;
    this.cleanupPid = null;
    this.restartTimer = null;
    this.shutdownTimer = null;
    this.heartbeatTimer = null;
    this.stopping = false;
    this.finished = false;
    this.shutdownCode = 0;
  }

  start() {
    process.on("SIGINT", () => this.stop("SIGINT", 130));
    process.on("SIGTERM", () => this.stop("SIGTERM", 143));
    process.on("SIGHUP", () => this.stop("SIGHUP", 129));
    process.once("exit", () => releaseSupervisorLock(this.lockPath));
    this.heartbeatTimer = setInterval(() => {
      if (heartbeatSupervisorLock(this.lockPath)) return;
      console.error("[sniper:supervisor] Supervisor port lock was lost; stopping Next to prevent a duplicate server.");
      this.stop("SIGTERM", 1);
    }, LOCK_HEARTBEAT_MS);
    this.heartbeatTimer.unref();
    this.launch();
  }

  launch() {
    if (this.stopping) return;
    const startedAt = Date.now();
    const child = spawn(process.execPath, this.args, {
      cwd: ROOT,
      env: {
        ...process.env,
        ...(this.config.local ? { SNIPER_EXECUTION_MODE: "local" } : {}),
        NODE_OPTIONS: nextNodeOptions(),
      },
      detached: process.platform !== "win32",
      stdio: "inherit",
    });
    const run = { child, pid: child.pid, startedAt, spawnError: null, closed: false };
    this.active = run;
    child.once("error", (error) => {
      run.spawnError = error;
      console.error(`[sniper:supervisor] Could not launch Next: ${error.message}`);
    });
    child.once("close", (code, signal) => void this.handleClose(run, code, signal));
  }

  async handleClose(run, code, signal) {
    if (run.closed) return;
    run.closed = true;
    if (this.active === run) this.active = null;
    this.cleanupPid = run.pid ?? null;
    const cleaned = await terminateResidualGroup(run.pid);
    this.cleanupPid = null;
    if (this.stopping) return this.finish(this.shutdownCode);
    if (!cleaned) {
      console.error("[sniper:supervisor] The previous Next process group survived SIGKILL; refusing a duplicate restart.");
      return this.finish(1);
    }
    const runtimeMs = Date.now() - run.startedAt;
    const result = this.tracker.record(runtimeMs);
    const reason = run.spawnError?.message ?? (signal ? `signal ${signal}` : `exit ${code ?? "unknown"}`);
    if (result.stop) {
      const loop = result.fastLoop ? `${result.fastCount} fast exits in 30s` : `${result.exitCount} exits in 10m`;
      console.error(`[sniper:supervisor] Next stopped repeatedly (${loop}; last: ${reason}); not restarting.`);
      return this.finish(Number.isInteger(code) && code > 0 ? code : 1);
    }
    console.error(`[sniper:supervisor] Next stopped unexpectedly (${reason}); restarting in 1s.`);
    this.restartTimer = setTimeout(() => {
      this.restartTimer = null;
      this.launch();
    }, RESTART_DELAY_MS);
  }

  stop(signal, exitCode) {
    if (this.stopping) {
      signalProcessTree(this.active, "SIGKILL");
      if (this.cleanupPid && process.platform !== "win32") {
        try { process.kill(-this.cleanupPid, "SIGKILL"); } catch {}
      }
      return this.finish(exitCode);
    }
    this.stopping = true;
    this.shutdownCode = exitCode;
    if (this.restartTimer) clearTimeout(this.restartTimer);
    this.restartTimer = null;
    signalProcessTree(this.active, signal);
    if (!this.active && !this.cleanupPid) return this.finish(exitCode);
    this.shutdownTimer = setTimeout(() => {
      signalProcessTree(this.active, "SIGKILL");
      if (this.cleanupPid && process.platform !== "win32") {
        try { process.kill(-this.cleanupPid, "SIGKILL"); } catch {}
      }
      this.finish(exitCode);
    }, SHUTDOWN_GRACE_MS);
  }

  finish(code) {
    if (this.finished) return;
    this.finished = true;
    if (this.restartTimer) clearTimeout(this.restartTimer);
    if (this.shutdownTimer) clearTimeout(this.shutdownTimer);
    if (this.heartbeatTimer) clearInterval(this.heartbeatTimer);
    releaseSupervisorLock(this.lockPath);
    process.exit(code);
  }
}

export function loadSupervisorEnvironment(root, development) {
  loadEnvConfig(root, development);
}

export function main(argv = process.argv.slice(2)) {
  try {
    const parsed = parseSupervisorArgs(argv);
    loadSupervisorEnvironment(ROOT, parsed.command === "dev");
    const local = parsed.local || process.env.SNIPER_EXECUTION_MODE === "local";
    if (local) assertLocalForwarding(parsed.forwarded);
    nextNodeOptions();
    if (!existsSync(NEXT_BIN)) throw new SupervisorConfigError("Next is not installed; run npm install first");
    const config = { ...parsed, local };
    const lockPath = supervisorLockPath(ROOT, effectivePort(config.forwarded));
    acquireSupervisorLock(lockPath);
    new NextSupervisor(config, lockPath).start();
  } catch (error) {
    console.error(`[sniper:supervisor] ${error instanceof Error ? error.message : String(error)}`);
    process.exit(2);
  }
}

const invokedPath = process.argv[1] ? pathToFileURL(path.resolve(process.argv[1])).href : "";
if (import.meta.url === invokedPath) main();
