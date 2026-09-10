import { existsSync } from "node:fs";
import path from "node:path";
import { runNativeCli } from "../ai-edit/palmier-native-process";
import type { TimelineIdentity } from "./authority";
import type { LiveBuildPreflight } from "./preflight";

interface CandidateVerdict {
  ok?: unknown;
  candidate?: Record<string, unknown>;
  base?: Record<string, unknown>;
}

function identity(value: unknown, label: string): TimelineIdentity {
  const row = value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown> : {};
  if (typeof row.projectId !== "string" || typeof row.timelineId !== "string"
      || typeof row.fingerprint !== "string") {
    throw new Error(`Palmier live-build ${label} identity is incomplete.`);
  }
  return { projectId: row.projectId, timelineId: row.timelineId,
    fingerprint: row.fingerprint };
}

function cliPath(input: LiveBuildPreflight): string {
  const root = input.ctx.pipeline?.snapshotRoot;
  if (!root) throw new Error("Palmier live build has no pinned pipeline snapshot.");
  const cli = path.join(root, "scripts", "producer", "palmier",
    "live_build_candidate_cli.py");
  if (!existsSync(cli)) {
    throw new Error("The approved plan predates the pinned live-build controller. Re-run plan review before building.");
  }
  return cli;
}

async function run(
  input: LiveBuildPreflight,
  args: string[],
  signal?: AbortSignal,
): Promise<{ candidate: TimelineIdentity; parent: TimelineIdentity }> {
  const verdict = await runNativeCli(args, signal, cliPath(input)) as CandidateVerdict;
  return {
    candidate: identity(verdict.candidate, "candidate"),
    parent: identity(verdict.base, "parent"),
  };
}

export function prepareLiveBuildCandidate(
  input: LiveBuildPreflight,
  resume: boolean,
  signal?: AbortSignal,
  expectedFingerprint?: string,
): Promise<{ candidate: TimelineIdentity; parent: TimelineIdentity }> {
  const action = resume
    ? [
      input.dir,
      "--resume",
      ...(expectedFingerprint
        ? ["--expected-candidate-fingerprint", expectedFingerprint] : []),
    ]
    : [input.dir, "--fork", `Sniper live build · ${new Date().toISOString().slice(11, 19)}`];
  return run(input, action, signal);
}

export function observeLiveBuildCandidate(
  input: LiveBuildPreflight,
  signal?: AbortSignal,
): Promise<{ candidate: TimelineIdentity; parent: TimelineIdentity }> {
  return run(input, [input.dir, "--observe"], signal);
}

export function checkpointLiveBuildCandidate(
  input: LiveBuildPreflight,
  authorityPath: string,
  signal?: AbortSignal,
  expectedFingerprint?: string,
): Promise<{ candidate: TimelineIdentity; parent: TimelineIdentity }> {
  return run(input, [
    input.dir,
    "--checkpoint", authorityPath,
    ...(expectedFingerprint
      ? ["--expected-candidate-fingerprint", expectedFingerprint] : []),
  ], signal);
}
