/** Local native Shorts entry point; this command never invokes a model/provider. */
import { readFileSync } from "node:fs";
import path from "node:path";
import { readNativeShortProject, writeNativeShortProject } from "../../src/lib/server/native-short-project";
import { prepareNativeShortRequest } from "../../src/lib/server/native-short-request";
import { storedAutoEditIntent } from "../../src/app/api/producer/auto-edit/operator-intent-authority";
import { measureNativeShortPacing, nativePacingBindings, nativePacingVisualWindows } from "../../src/lib/server/native-short-pacing-observations";
import { buildNativeCanvas } from "../../src/lib/server/native-short-composition";
import { nativeAssetUseRevisionHash } from "../../src/lib/server/native-short-asset-use";
import { nativeStoryRevisionHash } from "../../src/lib/server/native-short-story";
import { bindNativeWebOrigin, writeNativeAssetOrigin } from "../../src/lib/server/native-short-asset-origin";
import { prepareGuidedNativeShortRequest } from "../../src/lib/server/guided-native-authority";
import { buildGuidedNativeProject, parseGuidedNativeVisualPlan } from "../../src/lib/server/guided-native-build";
import { observeCutPreviewFile } from "../../src/app/api/producer/auto-edit/cut-preview-receipt";
import { MAX_TREATMENT_REQUEST_BYTES, parseTreatmentRequestJson } from "./guided-treatment-json";

const USAGE = "Usage: native-short.ts prepare|prepare-guided <producer-directory> | build-guided <producer-dir> <visual-plan.json> | measure <plan.json> | build <plan.json> <new-project> | check <project> | origin|origin-web <input.json> <new-receipt.json>";
/** Fixed in-process test seam only; parsed input cannot replace a service. */
export const nativeShortCommandServices = { buildGuided: buildGuidedNativeProject };

function guidedVisual(file: string) {
  if (!file || file.length > 4096 || /[\0\r\n]/u.test(file)) throw new Error("Guided visual plan path is invalid");
  const held = observeCutPreviewFile(path.resolve(file), MAX_TREATMENT_REQUEST_BYTES, true);
  return parseGuidedNativeVisualPlan(parseTreatmentRequestJson(new TextDecoder("utf-8", { fatal: true }).decode(held.bytes)));
}

export async function executeNativeShortCommand(argv: string[]) {
  const [operation, input, destination] = argv;
  if (operation === "--help" && argv.length === 1) return { usage: USAGE };
  const withDestination = ["build", "build-guided", "origin", "origin-web"].includes(operation);
  if (!input || !["prepare", "prepare-guided", "measure", "build", "build-guided", "check", "origin", "origin-web"].includes(operation)
      || argv.length !== (withDestination ? 3 : 2)) throw new Error(USAGE);
  if (operation === "prepare") {
    const producerDir = path.resolve(input);
    return prepareNativeShortRequest({ producerDir, intent: storedAutoEditIntent(producerDir), repo: process.cwd() });
  } else if (operation === "prepare-guided") {
    return prepareGuidedNativeShortRequest(path.resolve(input));
  } else if (operation === "build-guided") {
    if (input.length > 4096 || /[\0\r\n]/u.test(input)) throw new Error("Guided producer directory path is invalid");
    const visual = guidedVisual(destination);
    return nativeShortCommandServices.buildGuided({ dir: path.resolve(input), visual });
  } else if (operation === "measure") {
    const plan = JSON.parse(readFileSync(path.resolve(input), "utf8"));
    return { status: "observations-awaiting-editorial-pacing", ...nativePacingBindings(plan),
      assetUseRevisionHash: nativeAssetUseRevisionHash(plan),
      storyRevisionHash: nativeStoryRevisionHash(plan),
      observations: measureNativeShortPacing(plan.canvas),
      visualWindows: nativePacingVisualWindows(plan, buildNativeCanvas(plan.canvas) + (plan.extension?.markup ?? "")) };
  } else if (operation === "origin" || operation === "origin-web") {
    const record = JSON.parse(readFileSync(path.resolve(input), "utf8"));
    return operation === "origin" ? writeNativeAssetOrigin(record, destination) : bindNativeWebOrigin(record, destination);
  } else if (operation === "build") {
    const result = writeNativeShortProject(JSON.parse(readFileSync(path.resolve(input), "utf8")), destination);
    return { status: "built-awaiting-native-qc", ...result };
  } else {
    const plan = readNativeShortProject(path.resolve(input));
    return { status: "project-current", totalFrames: plan.canvas.totalFrames,
      request: plan.request, selectedTreatment: plan.strategy.selectedTreatment,
      story: plan.strategy.story ? "authored-obligations-checked-awaiting-whole-story-review" : "unplanned",
      assetUse: plan.strategy.assetUse ? "source-bound-decisions-checked-awaiting-editorial-review" : "legacy-unplanned",
      pacing: plan.strategy.pacing ? "declared-budgets-checked-awaiting-playback-review" : "legacy-unplanned" };
  }
}

if (require.main === module) executeNativeShortCommand(process.argv.slice(2))
  .then(value => console.log(JSON.stringify(value))).catch((error: unknown) => {
    console.error(JSON.stringify({ ok: false, error: String(error).slice(0, 2048),
      recovery: "Preserve retained attempt/project files; an error is not rollback or publication approval." }));
    process.exitCode = 1;
  });
