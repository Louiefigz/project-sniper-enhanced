import fs from "node:fs";
import path from "node:path";
import { assertSubscriptionStatus, claudeSubscriptionArgs, codexSubscriptionArgs, SUBSCRIPTION_VERSIONS,
  subscriptionStatusArgs, type SubscriptionProvider } from "./subscription-policy";
import { captureSubscriptionStatus } from "./subscription-status-process";

export interface SubscriptionInvocation {
  provider: SubscriptionProvider; bin: string; args: string[]; cwd: string;
  env: NodeJS.ProcessEnv; timeoutMs: number; signal?: AbortSignal;
}

function executable(bin: string, env: NodeJS.ProcessEnv): string {
  if (!bin || /[\0\r\n]/.test(bin)) throw new Error("Subscription CLI path is invalid");
  const candidates = path.isAbsolute(bin) ? [bin]
    : (env.PATH ?? "").split(path.delimiter).filter(path.isAbsolute).map((root) => path.join(root, bin));
  if (!path.isAbsolute(bin) && (bin.includes("/") || bin.includes("\\"))) throw new Error("Subscription CLI must be absolute or a PATH command");
  const found = candidates.find((value) => {
    try { return fs.statSync(value).isFile() && (fs.accessSync(value, fs.constants.X_OK), true); } catch { return false; }
  });
  if (!found) throw new Error("Subscription CLI executable is unavailable");
  return fs.realpathSync(found);
}

function identity(file: string): string {
  const stat = fs.statSync(file, { bigint: true });
  if (!stat.isFile()) throw new Error("Subscription CLI is not a regular executable");
  return [stat.dev, stat.ino, stat.size, stat.mtimeNs, stat.ctimeNs].join(":");
}

/** One monotonic deadline covers metadata admission AND inference. No auth-output logging. */
export async function admitSubscriptionInvocation(input: SubscriptionInvocation) {
  const started = performance.now();
  const { timeoutMs, signal, provider } = input;
  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0 || timeoutMs > 86_400_000) {
    throw new Error("Subscription invocation deadline is invalid");
  }
  const env = Object.freeze({ ...input.env }), cwd = fs.realpathSync(input.cwd);
  const bin = executable(input.bin, env), held = identity(bin);
  const args = Object.freeze(provider === "claude" ? claudeSubscriptionArgs(input.args) : codexSubscriptionArgs(input.args));
  const remainingMs = () => {
    if (signal?.aborted) throw new Error("Subscription invocation was cancelled");
    const remaining = timeoutMs - (performance.now() - started);
    if (remaining <= 0) throw new Error("Subscription invocation timed out during authentication");
    if (identity(bin) !== held) throw new Error("Subscription CLI changed during authentication");
    return Math.max(1, Math.floor(remaining));
  };
  const capture = (argv: string[]) => captureSubscriptionStatus({ bin, args: argv, cwd, env,
    timeoutMs: Math.min(10_000, remainingMs()), signal });
  const version = await capture(["--version"]);
  if (version.stdout.trim() !== SUBSCRIPTION_VERSIONS[provider] || version.stderr.trim()) {
    throw new Error("Subscription CLI version is not qualified for this authentication policy");
  }
  const status = await capture(subscriptionStatusArgs(provider));
  assertSubscriptionStatus(provider, status);
  remainingMs();
  return { bin, args, cwd, env, remainingMs, elapsedMs: () => performance.now() - started };
}

export type AdmittedSubscriptionInvocation = Awaited<ReturnType<typeof admitSubscriptionInvocation>>;
