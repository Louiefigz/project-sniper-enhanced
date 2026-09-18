import path from "node:path";
import { SCRIPTS_DIR } from "@/app/api/_lib/spawn-python";

export const CURRENT_RENDER_GRAPH = path.join(
  SCRIPTS_DIR,
  "producer",
  "current_render_graph_cli.py",
);

export type CurrentRenderAudioPolicy = "legacy-v1" | "source-float-v2";

export interface CurrentRenderGraphCommand {
  phase: "base" | "assemble";
  producerDir: string;
  artifactDir?: string;
  planPath: string;
  manifestPath: string;
  basePath: string;
  outputPath: string;
  rendererArgs: readonly string[];
  nextPlanPath?: string;
  cacheDir?: string;
  forceFull?: boolean;
  deferActive?: boolean;
  audioClockPolicy?: CurrentRenderAudioPolicy;
}

export interface EditorReadyRenderGraphCommand {
  producerDir: string;
  artifactDir?: string;
  sourcePlanPath: string;
  outputPlanPath: string;
  manifestPath: string;
  basePath: string;
  outputPath: string;
  fingerprintPath: string;
  workDir: string;
  renderScript: string;
  assembleScript: string;
  deferActive?: boolean;
  audioClockPolicy?: CurrentRenderAudioPolicy;
}

/**
 * Route every canonical current-render subprocess through one durable graph
 * preflight/commit boundary while preserving the child command verbatim.
 */
export function currentRenderGraphArgs(
  input: CurrentRenderGraphCommand,
): string[] {
  const args = [
    CURRENT_RENDER_GRAPH,
    "--phase", input.phase,
    "--producer-dir", input.producerDir,
    "--plan", input.planPath,
    "--manifest", input.manifestPath,
    "--base", input.basePath,
    "--output", input.outputPath,
  ];
  if (input.artifactDir) args.push("--artifact-dir", input.artifactDir);
  if (input.nextPlanPath) args.push("--next-plan", input.nextPlanPath);
  if (input.cacheDir) args.push("--cache-dir", input.cacheDir);
  if (input.forceFull) args.push("--force-full");
  if (input.deferActive) args.push("--defer-active");
  if (input.audioClockPolicy) args.push("--audio-clock-policy", input.audioClockPolicy);
  return [...args, "--", ...input.rendererArgs];
}

/** Build the two canonical stages used by the editor-ready render route. */
export function editorReadyRenderGraphArgs(
  input: EditorReadyRenderGraphCommand,
): { baseArgs: string[]; assembleArgs: string[] } {
  const artifactDir = input.artifactDir ?? input.producerDir;
  const baseRenderer = [
    input.renderScript, input.sourcePlanPath, input.manifestPath,
    artifactDir, "--workdir", input.workDir, "--skip-graphics",
    "--require-source-set-admission",
  ];
  const assembleRenderer = [
    input.assembleScript, input.basePath, input.outputPlanPath, input.outputPath,
    "--fingerprint", input.fingerprintPath, "--auto-base",
    "--manifest", input.manifestPath, "--require-source-set-admission",
  ];
  if (input.audioClockPolicy) {
    baseRenderer.push("--audio-clock-policy", input.audioClockPolicy);
    assembleRenderer.push("--audio-clock-policy", input.audioClockPolicy);
  }
  return {
    baseArgs: currentRenderGraphArgs({
      phase: "base", producerDir: input.producerDir,
      artifactDir: input.artifactDir,
      planPath: input.sourcePlanPath, nextPlanPath: input.outputPlanPath,
      manifestPath: input.manifestPath, basePath: input.basePath,
      outputPath: input.outputPath, rendererArgs: baseRenderer,
      audioClockPolicy: input.audioClockPolicy,
    }),
    assembleArgs: currentRenderGraphArgs({
      phase: "assemble", producerDir: input.producerDir,
      artifactDir: input.artifactDir,
      planPath: input.outputPlanPath, manifestPath: input.manifestPath,
      basePath: input.basePath, outputPath: input.outputPath,
      rendererArgs: assembleRenderer, deferActive: input.deferActive,
      audioClockPolicy: input.audioClockPolicy,
    }),
  };
}
