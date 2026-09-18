import { readFileSync } from "fs";
import { spawnSync } from "child_process";

/** Durable identity for a PID. Optional fields preserve legacy/unsupported hosts. */
export interface ProcessIdentity {
  pid: number;
  bootSession?: string;
  startToken?: string;
}

export interface ProcessIdentityProbe {
  bootSession: () => string | undefined;
  processStart: (pid: number) => string | undefined;
  processAlive: (pid: number) => boolean;
  processGroupAlive: (pid: number) => boolean;
}

export const PROCESS_HEARTBEAT_MAX_AGE_MS = 60 * 60 * 1000;

function signalAlive(target: number): boolean {
  try {
    process.kill(target, 0);
    return true;
  } catch (error) {
    return (error as NodeJS.ErrnoException).code === "EPERM";
  }
}

function commandOutput(command: string, args: string[]): string | undefined {
  const result = spawnSync(command, args, { encoding: "utf8", timeout: 1_000 });
  const output = result.status === 0 ? result.stdout.trim() : "";
  return output || undefined;
}

function bootSession(): string | undefined {
  try {
    if (process.platform === "linux") {
      return `linux:${readFileSync("/proc/sys/kernel/random/boot_id", "utf8").trim()}`;
    }
    if (process.platform === "darwin") {
      const value = commandOutput("/usr/sbin/sysctl", ["-n", "kern.boottime"]);
      const seconds = value?.match(/sec\s*=\s*(\d+)/)?.[1];
      return seconds ? `darwin:${seconds}` : undefined;
    }
  } catch {
    // Unsupported/restricted hosts retain PID + heartbeat fallback semantics.
  }
  return undefined;
}

function linuxStartToken(pid: number): string | undefined {
  try {
    const stat = readFileSync(`/proc/${pid}/stat`, "utf8");
    const close = stat.lastIndexOf(")");
    const fields = close >= 0 ? stat.slice(close + 1).trim().split(/\s+/) : [];
    return fields[19] ? `linux-ticks:${fields[19]}` : undefined;
  } catch {
    return undefined;
  }
}

function processStart(pid: number): string | undefined {
  if (!Number.isInteger(pid) || pid < 1) return undefined;
  if (process.platform === "linux") return linuxStartToken(pid);
  if (process.platform === "darwin" || process.platform === "freebsd") {
    const value = commandOutput("/bin/ps", ["-o", "lstart=", "-p", String(pid)]);
    return value ? `ps:${value.replace(/\s+/g, " ")}` : undefined;
  }
  return undefined;
}

const SYSTEM_PROBE: ProcessIdentityProbe = {
  bootSession,
  processStart,
  processAlive: (pid) => Number.isInteger(pid) && pid > 0 && signalAlive(pid),
  processGroupAlive: (pid) => process.platform === "win32"
    ? Number.isInteger(pid) && pid > 0 && signalAlive(pid)
    : Number.isInteger(pid) && pid > 0 && signalAlive(-pid),
};

export function processAlive(pid: number | undefined): boolean {
  return !!pid && SYSTEM_PROBE.processAlive(pid);
}

export function processGroupAlive(pid: number | undefined): boolean {
  return !!pid && SYSTEM_PROBE.processGroupAlive(pid);
}

export function captureProcessIdentity(
  pid: number,
  probe: ProcessIdentityProbe = SYSTEM_PROBE,
): ProcessIdentity {
  const identity: ProcessIdentity = { pid };
  const boot = probe.bootSession();
  const start = probe.processStart(pid);
  if (boot) identity.bootSession = boot;
  if (start) identity.startToken = start;
  return identity;
}

export function validProcessIdentity(value: unknown): value is ProcessIdentity {
  if (!value || typeof value !== "object") return false;
  const identity = value as Partial<ProcessIdentity>;
  return Number.isInteger(identity.pid) && Number(identity.pid) > 0
    && (identity.bootSession === undefined || typeof identity.bootSession === "string")
    && (identity.startToken === undefined || typeof identity.startToken === "string");
}

interface DurableLivenessOptions {
  now?: number;
  maxHeartbeatAgeMs?: number;
  probe?: ProcessIdentityProbe;
}

function heartbeatFresh(updatedAt: string, options: DurableLivenessOptions): boolean {
  const timestamp = Date.parse(updatedAt);
  const now = options.now ?? Date.now();
  const ceiling = options.maxHeartbeatAgeMs ?? PROCESS_HEARTBEAT_MAX_AGE_MS;
  return Number.isFinite(timestamp) && timestamp <= now + 60_000 && now - timestamp <= ceiling;
}

function identityMatches(
  pid: number,
  identity: ProcessIdentity | undefined,
  probe: ProcessIdentityProbe,
): boolean {
  if (identity?.pid !== undefined && identity.pid !== pid) return false;
  // These OS probes are optional and may time out under load. Only a concrete
  // conflicting value proves PID reuse; no value is an inconclusive probe and
  // retains the fresh-heartbeat + signal-zero fallback.
  const boot = identity?.bootSession ? probe.bootSession() : undefined;
  if (identity?.bootSession && boot && boot !== identity.bootSession) return false;
  const start = identity?.startToken ? probe.processStart(pid) : undefined;
  if (identity?.startToken && start && start !== identity.startToken) return false;
  return true;
}

/** A durable PID is live only when fresh and still names the recorded process. */
export function durableProcessAlive(
  pid: number | undefined,
  identity: ProcessIdentity | undefined,
  updatedAt: string,
  options: DurableLivenessOptions = {},
): boolean {
  if (!pid || !heartbeatFresh(updatedAt, options)) return false;
  const probe = options.probe ?? SYSTEM_PROBE;
  return probe.processAlive(pid) && identityMatches(pid, identity, probe);
}

/** Group-aware variant: an original child may outlive its recorded leader. */
export function durableProcessGroupAlive(
  pid: number | undefined,
  identity: ProcessIdentity | undefined,
  updatedAt: string,
  options: DurableLivenessOptions = {},
): boolean {
  if (!pid || !heartbeatFresh(updatedAt, options)) return false;
  const probe = options.probe ?? SYSTEM_PROBE;
  if (!probe.processGroupAlive(pid)) return false;
  const boot = identity?.bootSession ? probe.bootSession() : undefined;
  if (identity?.bootSession && boot && boot !== identity.bootSession) return false;
  return !probe.processAlive(pid) || identityMatches(pid, identity, probe);
}
