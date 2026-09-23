import { constants, accessSync, lstatSync, realpathSync } from "node:fs";
import path from "node:path";
import { observeCutPreviewFile, readCutPreviewObject, assertCutPreviewDirectory } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { parseOpeningRuntimeControl, type OpeningRuntimeControlV1 } from "@/lib/producer/contracts/guided-opening-claim-v1";
import { pipelineAuthorityPath } from "./auto-edit-pipeline-authority";
import type { OpeningReadiness } from "./guided-opening-authority";

function socketIdentity(file: string) {
  assertCutPreviewDirectory(path.dirname(file));
  const info = lstatSync(file, { bigint: true });
  if (!info.isSocket() || info.isSymbolicLink() || typeof process.getuid !== "function"
      || info.uid !== BigInt(process.getuid())) throw new Error("Opening Docker socket must be actual, canonical and owned by this user");
  return { dockerSocketDevice: String(info.dev), dockerSocketInode: String(info.ino) };
}

function configuredPath(name: string): string {
  const value = process.env[name];
  if (!value || value !== value.trim() || !path.isAbsolute(value)) throw new Error(`Opening requires explicit ${name}; no runtime fallback`);
  return realpathSync(value);
}

/** The guided checkpoint renders in the approved container, which the Mac package does not provide. */
export const GUIDED_CONTAINER_UNAVAILABLE = "The guided opening/body checkpoint workflow renders its graphics in the approved "
  + "container renderer, which this Mac package does not include. Use Auto Edit or the native Short/Long route instead.";

/** Observe explicit local controls before the durable claim. This does not contact Docker. */
export function captureOpeningRuntimeControl(proposal: OpeningReadiness): OpeningRuntimeControlV1 {
  if (!process.env.SNIPER_DOCKER_PATH && !process.env.SNIPER_RENDER_IMAGE_ID) throw new Error(GUIDED_CONTAINER_UNAVAILABLE);
  if (!proposal.job.ctx.pipeline) throw new Error("Opening runtime controls require the exact pinned pipeline; no current-repository fallback");
  const dockerPath = configuredPath("SNIPER_DOCKER_PATH"), dockerSocketPath = configuredPath("SNIPER_DOCKER_SOCKET");
  accessSync(dockerPath, constants.X_OK);
  const docker = observeCutPreviewFile(dockerPath, 256 * 1024 * 1024);
  const imageApprovalPath = pipelineAuthorityPath(proposal.job.ctx, "scripts/producer/headless/render_image_approval.json");
  const approval = readCutPreviewObject(imageApprovalPath);
  const imageId = process.env.SNIPER_RENDER_IMAGE_ID, userId = process.env.SNIPER_RENDER_UID_GID;
  if (approval.value.schemaVersion !== 1 || approval.value.imageId !== imageId) throw new Error("Opening runtime does not select the exact pinned approved image");
  const runtimeRepoRoot = realpathSync(process.env.SNIPER_RUNTIME_REPO_ROOT ?? process.cwd());
  if (runtimeRepoRoot !== realpathSync(process.cwd())) throw new Error("Opening runtime repository differs from its current verified TS execution");
  assertCutPreviewDirectory(runtimeRepoRoot);
  return parseOpeningRuntimeControl({ dockerPath, dockerSha256: docker.sha256, dockerSocketPath, ...socketIdentity(dockerSocketPath),
    imageId, userId, imageApprovalPath, imageApprovalSha256: approval.sha256, runtimeRepoRoot });
}

/** Cleanup must retain the original control plane; an edited environment cannot select another Docker. */
export function assertOpeningRuntimeControl(value: OpeningRuntimeControlV1): void {
  const runtime = parseOpeningRuntimeControl(value);
  accessSync(runtime.dockerPath, constants.X_OK);
  const binary = observeCutPreviewFile(runtime.dockerPath, 256 * 1024 * 1024), socket = socketIdentity(runtime.dockerSocketPath);
  const approval = readCutPreviewObject(runtime.imageApprovalPath);
  if (binary.sha256 !== runtime.dockerSha256 || socket.dockerSocketDevice !== runtime.dockerSocketDevice
      || socket.dockerSocketInode !== runtime.dockerSocketInode || approval.sha256 !== runtime.imageApprovalSha256
      || approval.value.imageId !== runtime.imageId) throw new Error("Opening original Docker controls changed; cleanup remains unproved");
  assertCutPreviewDirectory(runtime.runtimeRepoRoot);
}

/** Explicit held controls only; callers merge their separate timing context and pinned Python environment. */
export function openingRuntimeEnvironment(runtime: OpeningRuntimeControlV1): Partial<NodeJS.ProcessEnv> {
  assertOpeningRuntimeControl(runtime);
  return { SNIPER_DOCKER_PATH: runtime.dockerPath, SNIPER_DOCKER_SOCKET: runtime.dockerSocketPath,
    SNIPER_RENDER_IMAGE_ID: runtime.imageId, SNIPER_RENDER_UID_GID: runtime.userId, SNIPER_RUNTIME_REPO_ROOT: runtime.runtimeRepoRoot };
}
