/** A frozen, separately critiqued Director step before the native scene compiler. */
import path from "node:path";
import { runCodex, type CodexRunOptions } from "@/app/api/_lib/codex-cli";
import { brainProvider } from "@/app/api/_lib/ai-provider";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { parseNativeDirectorReview, type NativeDirectorPlan, type NativeDirectorReview } from "@/lib/producer/contracts/native-director-v1";
import { createHumanCutIndex, humanCutDirectory } from "./human-cut-acceptance-store";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { catalogFromSources, directorCatalogHash, loadDirectorCatalog, type DirectorSource } from "./native-director-library";
import { directorInput, validateDirectorPlan, type DirectorInput } from "./native-director-validation";
import { buildDirectorPrompt } from "./native-director-prompt";
import { timedStage } from "./stage-timing";
import type { ProposalEvidence } from "./guided-proposal-evidence";

export interface NativeDirectorRecord {
  schemaVersion: 1; sourceHash: string; libraryHash: string; planHash: string;
  plan: NativeDirectorPlan; review: NativeDirectorReview;
  scope: "reviewed-director-plan-not-rendered-hook-or-delivery-approval";
}
export interface DirectorBrainInput { phase: "author" | "critic"; prompt: string; cwd: string; timeoutMs: number }
export type DirectorBrain = (input: DirectorBrainInput) => Promise<{ output: unknown }>;

/** Reuse configured subscription admission, model/effort, isolation, process lifetime and output bounds. */
export const runNativeDirectorBrain: DirectorBrain = async (input) => {
  if (brainProvider() !== "codex") throw new Error("Native Director requires the configured Codex subscription route; no provider fallback");
  const schema: CodexRunOptions["schema"] = input.phase === "author" ? "producer-native-director" : "producer-native-director-review";
  const result = await runCodex({ prompt: input.prompt, cwd: input.cwd, timeoutMs: input.timeoutMs,
    sandbox: "read-only", tools: "none", schema, maxOutputBytes: 128 * 1024 });
  return { output: JSON.parse(result.message) };
};

function reviewedRecord(input: DirectorInput, sources: DirectorSource[], output: unknown, critique: unknown): NativeDirectorRecord {
  const catalog = catalogFromSources(sources), plan = validateDirectorPlan(output, catalog, input);
  const planHash = canonicalJsonSha256(plan), review = parseNativeDirectorReview(critique);
  if (review.planHash !== planHash || review.verdict !== "pass") throw new Error(`Director critique blocked native assembly: ${review.findings.join("; ")}`);
  return { schemaVersion: 1, sourceHash: canonicalJsonSha256(input), libraryHash: directorCatalogHash(catalog), planHash, plan, review,
    scope: "reviewed-director-plan-not-rendered-hook-or-delivery-approval" };
}

/** Store author output before independent critique; failures retain their actual attempted decisions. */
export async function stageNativeDirector(options: { directory: string; rawIntent: string; evidence: ProposalEvidence;
  remainingMs: () => number; brain?: DirectorBrain }): Promise<NativeDirectorRecord> {
  const directory = humanCutDirectory(options.directory, "native-director"), catalog = loadDirectorCatalog();
  const input = directorInput(options.rawIntent, options.evidence), brain = options.brain ?? runNativeDirectorBrain;
  createHumanCutIndex(path.join(directory, "input.json"), input);
  createHumanCutIndex(path.join(directory, "library.json"), { schemaVersion: 1, sources: catalog.sources });
  const invoke = async (phase: DirectorBrainInput["phase"], prompt: string) => {
    createHumanCutIndex(path.join(directory, `${phase}-prompt.json`), { prompt });
    const result = await timedStage(options.directory, `native_director_${phase}`, () => brain({ phase, prompt, cwd: directory, timeoutMs: options.remainingMs() }));
    createHumanCutIndex(path.join(directory, `${phase}-result.json`), result);
    options.remainingMs(); return result.output;
  };
  const output = await invoke("author", buildDirectorPrompt(input, catalog));
  const plan = validateDirectorPlan(output, catalog, input), planHash = canonicalJsonSha256(plan);
  const critique = await invoke("critic", buildDirectorPrompt(input, catalog, { plan, planHash }));
  const record = reviewedRecord(input, catalog.sources, output, critique);
  createHumanCutIndex(path.join(directory, "record.json"), record);
  return readNativeDirector(options.directory);
}

/** Cold reconstruction reads frozen libraries; it never borrows changed current examples or calls a model. */
export function readNativeDirector(parent: string): NativeDirectorRecord {
  const directory = path.join(parent, "native-director"), read = (name: string) => readCutPreviewObject(path.join(directory, name)).value;
  const input = read("input.json") as unknown as DirectorInput, library = read("library.json");
  if (library.schemaVersion !== 1 || !Array.isArray(library.sources)) throw new Error("Director library snapshot is missing");
  const sources = library.sources as DirectorSource[], catalog = catalogFromSources(sources);
  const plan = validateDirectorPlan(read("author-result.json").output, catalog, input);
  const planHash = canonicalJsonSha256(plan);
  if (read("author-prompt.json").prompt !== buildDirectorPrompt(input, catalog)
      || read("critic-prompt.json").prompt !== buildDirectorPrompt(input, catalog, { plan, planHash })) throw new Error("Director prompt differs from its frozen source/template evidence");
  const record = reviewedRecord(input, sources, plan, read("critic-result.json").output);
  if (canonicalJsonSha256(record) !== canonicalJsonSha256(read("record.json"))) throw new Error("Director retained decision changed");
  return record;
}

export function assertDirectorSource(record: NativeDirectorRecord, rawIntent: string, evidence: ProposalEvidence): void {
  if (record.sourceHash !== canonicalJsonSha256(directorInput(rawIntent, evidence))) throw new Error("Director strategy belongs to different source words, timing, target or intent");
}
