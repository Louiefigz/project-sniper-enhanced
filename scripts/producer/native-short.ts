import { assertNativeMotionReviews } from "../../src/lib/server/native-motion-review";
/** Local native Shorts entry point; this command never invokes a model/provider. */
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { assembleNativeShortHtml, readNativeShortProject, writeNativeShortProject } from "../../src/lib/server/native-short-project";
import { prepareNativeSourceMedia } from "../../src/lib/server/native-selected-sources";
import { assertNativeShortPrebuildReview, assertNativeLongPrebuildReview, nativeShortPrebuildPlanHash } from "../../src/lib/server/native-short-prebuild-review";
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
import { prepareNativeLongformRequest, checkNativeLongformRequest } from "../../src/lib/server/native-longform-request";

const USAGE = "Usage: native-short.ts prepare|prepare-guided|prepare-longform <producer-directory> | check-longform <request-directory> | prepare-media <plan.json> <new-media-directory> | build-guided <producer-dir> <visual-plan.json> | measure <plan.json> | build <plan.json> <new-project> | check|check-export <project> | check-long-review <review.json> <plan-hash> | origin|origin-web <input.json> <new-receipt.json>";
/** Fixed in-process test seam only; parsed input cannot replace a service. */
export const nativeShortCommandServices = { buildGuided: buildGuidedNativeProject };

function guidedVisual(file: string) {
  if (!file || file.length > 4096 || /[\0\r\n]/u.test(file)) throw new Error("Guided visual plan path is invalid");
  const held = observeCutPreviewFile(path.resolve(file), MAX_TREATMENT_REQUEST_BYTES, true);
  return parseGuidedNativeVisualPlan(parseTreatmentRequestJson(new TextDecoder("utf-8", { fatal: true }).decode(held.bytes)));
}

export async function executeNativeShortCommand(argv: string[]) {
  const [operation, input, destination] = argv;
  if (operation === "check-motion-reviews" && argv.length === 3) return assertNativeMotionReviews(path.resolve(input), path.resolve(destination));
  if (operation === "check-long-review" && argv.length === 3) return assertNativeLongPrebuildReview(path.resolve(input), destination);
  if (operation === "check-export" && argv.length === 2) {
    const plan = readNativeShortProject(path.resolve(input));
    return assertNativeShortPrebuildReview(plan);
  }
  if (operation === "--help" && argv.length === 1) return { usage: USAGE };
  const withDestination = ["prepare-media", "build", "build-guided", "origin", "origin-web"].includes(operation);
  if (!input || !["prepare", "prepare-guided", "prepare-longform", "check-longform", "prepare-media", "measure", "build", "build-guided", "check", "origin", "origin-web"].includes(operation)
      || argv.length !== (withDestination ? 3 : 2)) throw new Error(USAGE);
  if (operation === "prepare-longform") return prepareNativeLongformRequest(path.resolve(input), process.cwd());
  if (operation === "check-longform") return checkNativeLongformRequest(path.resolve(input));
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
      prebuildPlanHash: nativeShortPrebuildPlanHash(plan),
      assetUseRevisionHash: nativeAssetUseRevisionHash(plan),
      storyRevisionHash: nativeStoryRevisionHash(plan),
      observations: measureNativeShortPacing(plan.canvas),
      visualWindows: nativePacingVisualWindows(plan, buildNativeCanvas(plan.canvas) + (plan.extension?.markup ?? "")) };
  } else if (operation === "origin" || operation === "origin-web") {
    const record = JSON.parse(readFileSync(path.resolve(input), "utf8"));
    return operation === "origin" ? writeNativeAssetOrigin(record, destination) : bindNativeWebOrigin(record, destination);
  } else if (operation === "build" || operation === "prepare-media") {
    if (existsSync(path.resolve(destination))) throw new Error("Native build needs a new destination");
    const original = JSON.parse(readFileSync(path.resolve(input), "utf8"));
    if (operation === "build") assertNativeShortPrebuildReview(original);
    const plan = prepareNativeSourceMedia(original, assembleNativeShortHtml(original),
      operation === "prepare-media" ? destination : `${destination}.sources`);
    if (operation === "prepare-media") return { status: "selected-sources-ready", preparedSources: plan.preparedSources,
      plan: original.preparedSources ? path.resolve(input) : path.resolve(destination, "prepared-plan.json") };
    const result = writeNativeShortProject(plan, destination);
    return { status: "built-awaiting-native-qc", ...result };
  } else {
    const plan = readNativeShortProject(path.resolve(input));
    return { status: "project-current", totalFrames: plan.canvas.totalFrames,
      request: plan.request, selectedTreatment: plan.strategy.selectedTreatment,
      prebuildReview: plan.prebuildReview ? "recorded-independent-plan-pass-not-playback-approval" : "legacy-unreviewed",
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
