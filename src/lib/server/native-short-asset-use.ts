/** Speech-bound visual choices and origin enforcement, separate from semantic review. */
import { ASSET_USES } from "@/lib/producer/contracts/asset-record";
import { exactKeys, objectValue } from "@/lib/producer/contracts/validation";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { assertNativeAssetUseMedia } from "./native-short-asset-use-media";
import { assetUseText, nativeAssetUseOrigins } from "./native-short-asset-use-origins";
import type { NativeAssetOriginBinding, NativeAssetOriginReceipt, NativeAssetUseDecision, NativeAssetUseInput,
  NativeAssetUseOptions, NativeShortAssetUsePlan } from "./native-short-asset-use-types";
export type { NativeAssetOriginBinding, NativeAssetOriginReceipt, NativeAssetUseDecision, NativeAssetUseInput,
  NativeAssetUseOptions, NativeShortAssetUsePlan } from "./native-short-asset-use-types";

/** A meaning, source, layout or timing revision requires reauthoring each dependent decision. */
export function nativeAssetUseRevisionHash(input: NativeAssetUseInput): string {
  return canonicalJsonSha256({ request: input.request, requestPacket: input.requestPacket ?? null,
    canvas: input.canvas, extension: input.extension ?? null,
    assets: input.assets.map(({ file, sha256, role, origin, webCapture }) => ({ file, sha256, role,
      origin: origin ?? null, webCapture: webCapture ?? null })),
    scenes: input.strategy.scenes, supportingSearch: input.strategy.supportingSearch });
}

function shape(value: unknown, label: string, keys: string[], required = keys): void {
  exactKeys(objectValue(value, label), keys, required, label);
}

function planContext(input: NativeAssetUseInput, options: NativeAssetUseOptions): NativeShortAssetUsePlan {
  const plan = input.strategy.assetUse;
  if (!plan) throw new Error("New native strategies require a speech-bound asset-use plan");
  shape(plan, "asset-use plan", ["schemaVersion", "revisionHash", "policy", "intendedUse", "decisions"]);
  shape(plan.intendedUse, "asset intended use", ["use", "platform"]);
  if (plan.schemaVersion !== 1 || !ASSET_USES.includes(plan.intendedUse.use) || plan.intendedUse.platform !== "local-review"
      || !Array.isArray(plan.decisions) || !plan.decisions.length || plan.decisions.length > 128) {
    throw new Error("Asset use requires bounded decisions and an explicit local-review intended use");
  }
  shape(options.expectedPolicy, "requested media policy", ["placement", "sources"]);
  if (!["auto", "off"].includes(options.expectedPolicy.placement)
      || !["provided-only", "local-only", "public-web"].includes(options.expectedPolicy.sources)) {
    throw new Error("Asset use requires scalar supported media policy values");
  }
  if (canonicalJsonSha256(plan.policy) !== canonicalJsonSha256(options.expectedPolicy)) {
    throw new Error("Asset-use plan cannot broaden the requested media policy");
  }
  if (plan.revisionHash !== nativeAssetUseRevisionHash(input)) throw new Error("Asset-use plan is stale after a speech, request, source or visual revision");
  return plan;
}

function speech(input: NativeAssetUseInput, decision: NativeAssetUseDecision): void {
  const cue = decision.speech;
  shape(cue, "asset-use speech", ["startFrame", "endFrame", "occurrenceIds", "text"]);
  if (![cue.startFrame, cue.endFrame].every(Number.isSafeInteger) || cue.startFrame < 0
      || cue.endFrame <= cue.startFrame || cue.endFrame > input.canvas.totalFrames) throw new Error("Asset use needs a bounded retained speech window");
  const expected = input.canvas.occurrences.filter(word => word[3] < cue.endFrame && word[4] > cue.startFrame);
  if (!expected.length || canonicalJsonSha256(expected.map(word => word[0])) !== canonicalJsonSha256(cue.occurrenceIds)
      || expected.map(word => word[5]).join(" ") !== cue.text) throw new Error("Asset use lost its exact retained speech and context binding");
}

function inspection(decision: NativeAssetUseDecision): void {
  const review = decision.inspection;
  shape(review, "asset inspection", ["method", "observations", "limitations"]);
  if (!["local-source-review", "not-reviewed"].includes(review.method)
      || !Array.isArray(review.observations) || !Array.isArray(review.limitations)
      || review.observations.length > 24 || review.limitations.length > 24
      || (review.method === "local-source-review" && !review.observations.length)
      || (review.method === "not-reviewed" && !review.limitations.length)) throw new Error("Asset inspection must state actual observations and remaining limitations");
  [...review.observations, ...review.limitations].forEach(assetUseText);
}

function selection(input: NativeAssetUseInput, decision: NativeAssetUseDecision, plan: NativeShortAssetUsePlan): void {
  const use = decision.selection;
  if (decision.decision === "no-insert") {
    if (use !== null) throw new Error("A no-insert decision cannot carry a selected media target");
    return;
  }
  if (!use || plan.policy.placement === "off" || ["style-direction", "no-insert"].includes(decision.purpose)
      || decision.entity.role === "style-reference") throw new Error("Disabled or style-only direction cannot become a depicted media insert");
  const keys = ["assetFile", "targetId", "kind", "startFrame", "endFrame", "essentialRegion", "essentialContent",
    "audio", "sourceRange", "sourceIdentity", "attribution"];
  shape(use, "asset selection", keys, keys.filter(key => key !== "sourceRange"));
  if (!/^[a-z][a-z0-9-]{0,95}$/u.test(use.targetId) || !["image", "logo", "video", "web", "creator-image", "creator-excerpt"].includes(use.kind)
      || ![use.startFrame, use.endFrame].every(Number.isSafeInteger) || use.startFrame < 0
      || use.endFrame <= use.startFrame || use.endFrame > input.canvas.totalFrames
      || use.startFrame >= decision.speech.endFrame || use.endFrame <= decision.speech.startFrame) {
    throw new Error("Selected media needs an exact output window overlapping its retained speech cue");
  }
  if (["logo", "creator-image", "creator-excerpt"].includes(use.kind) && decision.entity.role === "none") {
    throw new Error("Brand and creator inserts require an explicit depicted entity identity");
  }
  if (use.sourceRange) shape(use.sourceRange, "asset source range", ["startSeconds", "endSeconds", "frameRate"]);
  if (use.attribution !== null) shape(use.attribution, "asset attribution", ["text", "placement"]);
  assetUseText(use.sourceIdentity);
}

function decisionContext(input: NativeAssetUseInput, decision: NativeAssetUseDecision, plan: NativeShortAssetUsePlan): void {
  shape(decision, "asset decision", ["id", "decision", "speech", "entity", "purpose", "reason", "rejectedAlternative",
    "claimLimit", "context", "inspection", "selection"]);
  shape(decision.entity, "asset entity", ["name", "role", "canonicalIdentity"]);
  if (!/^[a-z][a-z0-9-]{0,95}$/u.test(decision.id) || !["insert", "no-insert"].includes(decision.decision)
      || !["identify", "demonstrate", "analyze-quote", "illustrate", "style-direction", "no-insert"].includes(decision.purpose)
      || !["subject", "quoted-source", "comparison", "style-reference", "none"].includes(decision.entity.role)) {
    throw new Error("Asset decision needs an explicit entity role, viewer purpose and stable identity");
  }
  [decision.entity.name, decision.reason, decision.rejectedAlternative, decision.claimLimit, decision.context].forEach(assetUseText);
  if (decision.entity.role !== "none" || decision.entity.canonicalIdentity !== null) assetUseText(decision.entity.canonicalIdentity);
  speech(input, decision); inspection(decision); selection(input, decision, plan);
}

/** Legacy reads opt out explicitly; new assembly must require origin-bound decisions. */
export function assertNativeShortAssetUse(input: NativeAssetUseInput, html: string, options: NativeAssetUseOptions): void {
  if (!options.required && input.strategy.assetUse === undefined) return;
  const plan = planContext(input, options);
  if (new Set(plan.decisions.map(row => row.id)).size !== plan.decisions.length) throw new Error("Asset-use decisions duplicate an identity");
  plan.decisions.forEach(decision => decisionContext(input, decision, plan));
  const origins = nativeAssetUseOrigins(input, options);
  assertNativeAssetUseMedia(input, html, origins);
}

function evidenceFiles(input: NativeAssetUseInput, origins: Map<string, NativeAssetOriginReceipt>): NativeAssetOriginBinding[] {
  const evidence = input.assets.flatMap(asset => asset.origin ? [asset.origin] : []);
  for (const origin of origins.values()) {
    evidence.push(...origin.acquisition.evidence);
    const web = origin.acquisition.webCapture;
    if (web) evidence.push({ path: web.path, sha256: web.sha256 }, { path: web.supervisionPath, sha256: web.supervisionSha256 });
  }
  const unique = new Map<string, NativeAssetOriginBinding>();
  for (const item of evidence) {
    if (unique.has(item.path) && unique.get(item.path)!.sha256 !== item.sha256) throw new Error("Origin evidence assigns conflicting hashes to the same file");
    unique.set(item.path, item);
  }
  return [...unique.values()].sort((left, right) => left.path.localeCompare(right.path));
}

/** Report structural traceability without upgrading identity, relevance, rights or playback review. */
export function nativeShortAssetUseReport(input: NativeAssetUseInput, html: string, options: NativeAssetUseOptions) {
  assertNativeShortAssetUse(input, html, options);
  const plan = input.strategy.assetUse, origins = plan ? nativeAssetUseOrigins(input, options) : new Map<string, NativeAssetOriginReceipt>();
  return { schemaVersion: 1, scope: "native-short-asset-use-structural-traceability",
    status: plan ? "source-bound-use-contract-checked" : "legacy-unplanned", revisionHash: nativeAssetUseRevisionHash(input),
    plan: plan ?? null, originEvidenceFiles: evidenceFiles(input, origins),
    assets: [...origins].map(([file, origin]) => ({ file, record: origin.record, acquisition: origin.acquisition })),
    semanticReview: "not-established-by-structural-checks", publicationAdmission: "not-performed-local-review-only",
    reviewRequired: ["Verify exact entity, original source, source context and currency against inspected evidence",
      "Check demonstration versus illustration, negation, attribution and claim limits in the complete edit",
      "Inspect essential regions against crop, title and captions at phone size throughout each selected interval",
      "Review actual audio, caption ownership and final encoded playback at normal speed"] };
}
