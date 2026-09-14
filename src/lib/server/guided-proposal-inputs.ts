import path from "node:path";
import { observeCutPreviewFile, readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { runCutPreviewProcess } from "@/app/api/producer/auto-edit/cut-preview-process";
import { pythonInterpreter } from "@/app/api/_lib/spawn-python";
import { objectValue } from "@/lib/producer/contracts/validation";
import { restoreAutoEditPipeline } from "./auto-edit-pipeline-authority";
import { humanCutDirectory, createHumanCutIndex } from "./human-cut-acceptance-store";
import { stageTimingEnv } from "./stage-timing-context";
import { timedStage } from "./stage-timing";
import { buildProposalEvidence, pinnedProposalFile } from "./guided-proposal-evidence";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import type { AcceptedGuidedCut } from "./guided-raw-treatment-store";
import { readRawTreatmentClock } from "./guided-raw-treatment-store";
import { generationChildTimeout } from "./generation-attempt-clock";
import { CURRENT_TREATMENT_PROPOSAL_VERSION } from "@/lib/producer/contracts/treatment-proposal-v5";
import { stageNativeReferences, readNativeReferences, type NativeReferenceSelection } from "./guided-native-references";
import { stageNativeDirector, readNativeDirector, type DirectorBrain } from "./native-director-store";

function transcriptFile(root: string, requested: string): string {
  if (requested.split(/[\\/]/u).includes("..")) throw new Error("Proposal transcript traversal is forbidden");
  const file = path.resolve(root, requested), relative = path.relative(root, file);
  if (!relative || relative.startsWith("..") || path.isAbsolute(relative)) throw new Error("Proposal transcript escapes its admitted source directory");
  return file;
}

/** Parse bounded no-follow bytes once, then give existing readers only new private canonical copies. */
function boundInput(file: string, value: unknown, mode: "stage" | "observe") {
  if (mode === "stage") createHumanCutIndex(file, value);
  if (canonicalJsonSha256(readCutPreviewObject(file).value) !== canonicalJsonSha256(value)) throw new Error("Private proposal input differs from the accepted source bytes");
}

function stageTranscripts(cut: AcceptedGuidedCut, directory: string, mode: "stage" | "observe") {
  const manifest = structuredClone(cut.manifest.value), sources = manifest.sources;
  if (!Array.isArray(sources) || sources.length > 128) throw new Error("Proposal source count exceeds 128");
  const transcriptRoot = mode === "stage" ? humanCutDirectory(directory, "transcripts") : path.join(directory, "transcripts");
  const proof: Array<{ sourceId: string; originalHash: string; stagedHash: string }> = [];
  let total = 0;
  for (const [index, value] of sources.entries()) {
    const source = objectValue(value, "manifest source");
    if (!source.transcriptPath) continue;
    if (typeof source.transcriptPath !== "string" || typeof source.id !== "string") throw new Error("Proposal transcript source is invalid");
    const file = transcriptFile(cut.job.ctx.transcriptsDir, source.transcriptPath);
    const observed = observeCutPreviewFile(file, 2 * 1024 * 1024, true); total += observed.sizeBytes;
    if (total > 8 * 1024 * 1024) throw new Error("Proposal transcripts exceed the 8 MiB aggregate bound");
    const transcript = objectValue(JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(observed.bytes)), "transcript");
    const staged = path.join(transcriptRoot, `${index}.json`); boundInput(staged, transcript, mode);
    proof.push({ sourceId: source.id, originalHash: observed.sha256, stagedHash: readCutPreviewObject(staged).sha256 });
    source.transcriptPath = path.basename(staged);
  }
  boundInput(path.join(directory, "transcript-proof.json"), { schemaVersion: 1, sources: proof }, mode);
  boundInput(path.join(directory, "manifest.json"), manifest, mode);
  boundInput(path.join(directory, "cut-plan.json"), cut.plan.value, mode);
  return { manifest, ctx: { ...cut.job.ctx, transcriptsDir: transcriptRoot } };
}

async function advice(cut: AcceptedGuidedCut, directory: string, transcripts: string, remainingMs: () => number) {
  const results: Record<string, unknown> = {};
  for (const name of ["graphics_style_advisor.py", "graphics_planner.py"]) {
    const script = pinnedProposalFile(cut, `scripts/producer/${name}`), root = path.dirname(script.file);
    const args = [script.file, path.join(directory, "cut-plan.json"), transcripts, path.join(directory, "manifest.json")];
    if (name === "graphics_planner.py") {
      const prior = objectValue(results["graphics_style_advisor.py"], "style advice");
      const style = objectValue(prior.recommendedTargetFields, "recommended style").graphicsStyle;
      if (!["cutaway-only", "overlay-rich", "face-bridge"].includes(String(style))) throw new Error("Style advisor did not return a supported proposal grammar");
      args[1] = plannerAdvicePlan(cut, directory, prior, "stage");
      args.push("--json", "--style", String(style)); // Recommendation input only; accepted target remains unchanged.
    }
    const result = await timedStage(cut.job.ctx.dir, `proposal_${name.replace(".py", "")}`, () => runCutPreviewProcess({
      command: pythonInterpreter(), args, cwd: directory, timeoutMs: generationChildTimeout(30_000, remainingMs),
      env: { ...stageTimingEnv(), PYTHONPATH: root, SNIPER_PIPELINE_ROOT: cut.job.ctx.pipeline!.snapshotRoot, PYTHONDONTWRITEBYTECODE: "1" },
    }));
    results[name] = objectValue(JSON.parse(result.stdout), "deterministic graphics advice");
  }
  createHumanCutIndex(path.join(directory, "graphics-advice.json"), results);
  return results;
}

function plannerAdvicePlan(cut: AcceptedGuidedCut, directory: string, advice: Record<string, unknown>, mode: "stage" | "observe") {
  const fields = objectValue(advice.recommendedTargetFields, "recommended target fields");
  const plan = structuredClone(cut.plan.value), target = { ...objectValue(plan.target, "target"), ...fields };
  if (!Array.isArray(advice.removeTargetFields) || advice.removeTargetFields.some((key) => key !== "visualProfile")) throw new Error("Invalid style-advice removals");
  for (const key of advice.removeTargetFields as string[]) delete target[key];
  const file = path.join(directory, "advice-plan.json"); boundInput(file, { ...plan, target }, mode); return file;
}

/** Isolated copies + existing actual advisors, never graphics rendering or active-plan mutation. */
export async function prepareProposalEvidence(cut: AcceptedGuidedCut, execution: string, remainingMs: () => number,
  options: { version: 4 | 5 | 6 | 7 | 8 | 9 | 10; nativeReferences?: NativeReferenceSelection[]; directorBrain?: DirectorBrain } = { version: CURRENT_TREATMENT_PROPOSAL_VERSION }) {
  remainingMs();
  if (!cut.job.ctx.pipeline) throw new Error("Proposal requires captured pipeline authority");
  restoreAutoEditPipeline(cut.job.ctx.pipeline);
  const directory = humanCutDirectory(execution, "candidate-inputs"), staged = stageTranscripts(cut, directory, "stage");
  if (options.version === 9 || options.version === 10) {
    const nativeReferences = stageNativeReferences(directory, options.nativeReferences ?? []);
    const graphicsAdvice = { nativeShorts: true, route: "native-short-v1", nativeDirectorVersion: 1,
      ...(options.version === 10 ? { nativeSupportingVersion: 1 } : {}) };
    createHumanCutIndex(path.join(directory, "graphics-advice.json"), graphicsAdvice);
    const evidence = await buildProposalEvidence(cut, { ...staged, graphicsAdvice, nativeReferences }, options);
    const nativeDirector = await stageNativeDirector({ directory, evidence, rawIntent: readRawTreatmentClock(cut).submission.rawIntent,
      remainingMs, brain: options.directorBrain });
    return { ...evidence, nativeDirector };
  }
  const graphicsAdvice = await advice(cut, directory, staged.ctx.transcriptsDir, remainingMs);
  return buildProposalEvidence(cut, { ...staged, graphicsAdvice }, options);
}

/** Non-creating read, proving stored bounded inputs still represent the actual admitted transcript bytes. */
export function readProposalInputs(cut: AcceptedGuidedCut, execution: string) {
  const directory = path.join(execution, "candidate-inputs"), staged = stageTranscripts(cut, directory, "observe");
  const graphicsAdvice = readCutPreviewObject(path.join(directory, "graphics-advice.json")).value;
  if (graphicsAdvice.nativeShorts === true) return { ...staged, graphicsAdvice, nativeReferences: readNativeReferences(directory),
    ...(graphicsAdvice.nativeDirectorVersion === 1 ? { nativeDirector: readNativeDirector(directory) } : {}) };
  plannerAdvicePlan(cut, directory, objectValue(graphicsAdvice["graphics_style_advisor.py"], "style advice"), "observe");
  return { ...staged, graphicsAdvice };
}
