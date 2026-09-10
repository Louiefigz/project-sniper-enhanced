import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import path from "node:path";
import { PLANNING_GATE_IDS, type PlanningGateId } from "@/app/api/producer/auto-edit/planning-gate-contract";

/** Exact-name reconciliation of the readiness gates' owned sealed-renderer containers. */
export interface RendererReconciliation {
  containerNames: string[]; present: string[]; removed: string[]; verifiedAbsent: boolean; detail: string;
}
export interface SealedRendererConfig { dockerPath: string; socket: string }
export type DockerExec = (config: SealedRendererConfig, args: string[]) => { code: number | null; stdout: string; stderr: string };

/** Only an explicitly configured sealed renderer needs caller-owned container names; the host renderer uses none. */
export type EnvironmentView = Record<string, string | undefined>;

export function sealedRendererConfigured(env: EnvironmentView = process.env): SealedRendererConfig | null {
  const dockerPath = env.SNIPER_DOCKER_PATH, socket = env.SNIPER_DOCKER_SOCKET;
  if (!env.SNIPER_RENDER_IMAGE_ID || !dockerPath || !socket) return null;
  return { dockerPath, socket };
}

/** One owned name per gate, in the sealed renderer's own grammar (`sniper-render-<32 hex>`, container_renderer.py
 * `_CONTAINER_NAME`): concurrent gates never share a container, and the id derives from OUR execution, never a guess. */
export function readinessContainerName(executionId: string, gate: PlanningGateId): string {
  if (!/^[0-9a-f-]{36}$/.test(executionId)) throw new Error("readiness container names need the exact execution id");
  return `sniper-render-${createHash("sha256").update(`readiness|${executionId}|${gate}`).digest("hex").slice(0, 32)}`;
}

function spawnDocker(config: SealedRendererConfig, args: string[]) {
  const result = spawnSync(config.dockerPath, ["--host", `unix://${config.socket}`, ...args], { encoding: "utf8", timeout: 30_000 });
  return { code: result.error ? null : result.status, stdout: result.stdout ?? "", stderr: result.error?.message ?? result.stderr ?? "" };
}

function ownedNamesPresent(config: SealedRendererConfig, names: string[], exec: DockerExec): string[] | null {
  const listed = exec(config, ["ps", "-a", "--format", "{{.Names}}"]);
  if (listed.code !== 0) return null;
  return listed.stdout.split("\n").map((line) => line.trim()).filter((name) => names.includes(name));
}

/** Remove only this execution's exact names, then verify none remain. Nothing else is ever signalled or removed. */
export function reconcileReadinessContainers(config: SealedRendererConfig, executionId: string, exec: DockerExec = spawnDocker): RendererReconciliation {
  const containerNames = PLANNING_GATE_IDS.map((gate) => readinessContainerName(executionId, gate));
  const present = ownedNamesPresent(config, containerNames, exec);
  if (present === null) return { containerNames, present: [], removed: [], verifiedAbsent: false, detail: "docker ps failed; owned containers unverified" };
  const removed = present.filter((name) => exec(config, ["rm", "-f", name]).code === 0);
  const remaining = ownedNamesPresent(config, containerNames, exec);
  const verifiedAbsent = remaining !== null && remaining.length === 0;
  return { containerNames, present, removed, verifiedAbsent,
    detail: verifiedAbsent ? "owned readiness containers absent" : `owned readiness containers still present: ${(remaining ?? ["unverified"]).join(", ")}` };
}

export interface ReadinessRendererInput {
  executionId: string;
  /** Resolves the pinned ffmpeg/ffprobe the sealed lane hashes into its cache identity and proofs
   * (container_renderer.py); read only when a sealed renderer is actually configured. */
  proofTools: () => { ffmpeg: string; ffprobe: string };
}

/** Per-gate child environment plus the exact reconciliation the readiness record must carry. */
export function readinessRenderer(input: ReadinessRendererInput, env: EnvironmentView = process.env, exec?: DockerExec) {
  const config = sealedRendererConfigured(env);
  if (!config) return null;
  const { ffmpeg, ffprobe } = input.proofTools();
  if (!path.isAbsolute(ffmpeg) || !path.isAbsolute(ffprobe)) throw new Error("readiness proof tools must be absolute pinned paths");
  return { env: (gate: PlanningGateId) => ({ SNIPER_RENDER_CONTAINER_NAME: readinessContainerName(input.executionId, gate),
      SNIPER_PROOF_FFMPEG_PATH: ffmpeg, SNIPER_PROOF_FFPROBE_PATH: ffprobe }),
    reconcile: () => reconcileReadinessContainers(config, input.executionId, exec) };
}
