/** Pure admitted presentation metadata and manual layout projection; no media or approval. */
import { packetCutSegments } from "@/app/api/producer/auto-edit/plan-review-packet-source";
import { SCOPES, resolveLanes, validateLaneOverrides } from "@/lib/producer/intent-presets";
import { enumValue, exactKeys, objectValue, sha256, stringValue } from "@/lib/producer/contracts/validation";
import { parseTreatmentProposalV8, type TreatmentProposalV8 } from "@/lib/producer/contracts/treatment-proposal-v8";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { guidedPresenterWindows, type GuidedPresenterFrameEvidence } from "./guided-proposal-presenter-frames";
export { guidedPresenterWindows, type GuidedPresenterWindow, type GuidedPresenterFrameEvidence } from "./guided-proposal-presenter-frames";

export interface GuidedPresenterAsset {
  assetId: string; sourceSha256: string; sourceSizeBytes: number; admissionReceiptSha256: string;
  kind: "image" | "video"; durationS: number | null; width: number; height: number; rights: "unverified";
}
export interface GuidedPresenterPolicy {
  schemaVersion: 1; scope: "admitted-project-presentation-metadata-not-source-rights-or-quality-approval";
  acceptedMotionEnabled: boolean; acceptedBrollEnabled: boolean; assets: GuidedPresenterAsset[];
}
interface ProjectionInput {
  plan: Record<string, unknown>; manifest: Record<string, unknown>; proposal: TreatmentProposalV8;
  policy: GuidedPresenterPolicy; evidence: GuidedPresenterFrameEvidence;
}
const COLLISIONS = ["presenterLayouts", "presenter", "overlays"];
const POLICY_KEYS = ["schemaVersion", "scope", "acceptedMotionEnabled", "acceptedBrollEnabled", "assets"];
const ASSET_KEYS = ["assetId", "sourceSha256", "sourceSizeBytes", "admissionReceiptSha256", "kind", "durationS", "width", "height", "rights"];

function laneIntent(value: unknown) {
  const row = objectValue(value, "presenter lane intent"), scope = enumValue(row.scope, SCOPES, "presenter scope");
  const lanes = validateLaneOverrides(row.lanes);
  return { scope, lanes };
}

/** Target lane declarations mirror actual accepted operator intent; equal effective scopes are not substitutions. */
export function assertGuidedPresenterIntent(plan: Record<string, unknown>, intent: unknown): void {
  if (canonicalJsonSha256(laneIntent(plan.target)) !== canonicalJsonSha256(laneIntent(intent))) {
    throw new Error("Accepted presenter target scope/lanes differ from stored operator intent; an explicit intent revision is required");
  }
}

function positiveInteger(value: unknown, label: string, maximum = Number.MAX_SAFE_INTEGER): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 1 || value > maximum) {
    throw new Error(`Presenter ${label} requires a positive bounded safe integer`);
  }
  return value;
}

function admittedAsset(value: unknown): GuidedPresenterAsset {
  const row = objectValue(value, "manifest presentation asset");
  for (const key of ["originalPath", "path", "admissionReceiptPath"]) stringValue(row[key], `presentation ${key}`, 4096);
  const kind = enumValue(row.kind, ["image", "video"] as const, "presentation kind");
  if (kind === "image" ? row.duration !== null : typeof row.duration !== "number" || !Number.isFinite(row.duration) || row.duration <= 0) {
    throw new Error("Presentation requires null image duration or positive finite video duration metadata");
  }
  if (!Array.isArray(row.resolution) || row.resolution.length !== 2) throw new Error("Presentation requires exact admitted resolution metadata");
  return { assetId: stringValue(row.id, "presentation assetId", 128), sourceSha256: sha256(row.sourceSha256, "presentation source hash"),
    sourceSizeBytes: positiveInteger(row.sourceSizeBytes, "asset bytes"), admissionReceiptSha256: sha256(row.admissionReceiptSha256, "presentation admission hash"),
    kind, durationS: row.duration as number | null, width: positiveInteger(row.resolution[0], "asset width", 16384),
    height: positiveInteger(row.resolution[1], "asset height", 16384), rights: "unverified" };
}

/** Every b-roll row is held or refused; metadata does not confer source freshness, display geometry or rights. */
export function guidedPresenterPolicy(plan: Record<string, unknown>, manifest: Record<string, unknown>): GuidedPresenterPolicy {
  const { scope, lanes } = laneIntent(plan.target), resolved = resolveLanes(scope, lanes);
  const rows = manifest.broll === undefined ? [] : manifest.broll;
  if (!Array.isArray(rows) || rows.length > 128) throw new Error("Presentation catalog requires at most 128 admitted rows");
  const assets = rows.map(admittedAsset);
  if (new Set(assets.map(asset => asset.assetId)).size !== assets.length) throw new Error("Presentation asset IDs are ambiguous");
  return { schemaVersion: 1, scope: "admitted-project-presentation-metadata-not-source-rights-or-quality-approval",
    acceptedMotionEnabled: resolved.motion === "auto", acceptedBrollEnabled: resolved.broll === "auto", assets };
}

function assertPolicy(value: unknown, expected: GuidedPresenterPolicy): void {
  const policy = objectValue(value, "presenter policy"); exactKeys(policy, POLICY_KEYS, POLICY_KEYS, "presenter policy");
  if (!Array.isArray(policy.assets) || policy.assets.length > 128) throw new Error("Presenter policy assets are malformed");
  for (const value of policy.assets) exactKeys(objectValue(value, "presenter policy asset"), ASSET_KEYS, ASSET_KEYS, "presenter policy asset");
  if (canonicalJsonSha256(value) !== canonicalJsonSha256(expected)) throw new Error("Presenter policy differs from exact accepted target and manifest metadata");
}

function assertAcceptedFrames(input: ProjectionInput): void {
  if (canonicalJsonSha256(input.plan.target) !== canonicalJsonSha256(input.evidence.target)) throw new Error("Presenter evidence target differs from accepted target");
  if (!Array.isArray(input.plan.cutTrack) || input.plan.cutTrack.length !== input.evidence.segments.length) {
    throw new Error("Presenter evidence lacks exact accepted cut segment coverage");
  }
  const segments = packetCutSegments(input.plan);
  if (segments.length !== input.evidence.segments.length || segments.some((segment, index) => segment.speed !== 1
      || segment.sourceId !== input.evidence.segments[index].sourceId)) {
    throw new Error("Presenter evidence differs from the ordered accepted speed-1 cut segments");
  }
}

/** Add only the explicit presenter track; never replace inherited layout, retime, infer a source or select an asset. */
export function applyGuidedPresenterOperations(input: ProjectionInput): Record<string, unknown> {
  const expected = guidedPresenterPolicy(input.plan, input.manifest); assertPolicy(input.policy, expected);
  const windows = guidedPresenterWindows(input.proposal, input.evidence);
  if (!windows.length) return structuredClone(input.plan);
  if (!expected.acceptedMotionEnabled || !expected.acceptedBrollEnabled || COLLISIONS.some(key => Object.hasOwn(input.plan, key))) {
    throw new Error("Presenter layout requires accepted motion/broll auto and absent inherited presenter/overlays; explicit revision is required");
  }
  assertAcceptedFrames(input);
  for (const window of windows) {
    const asset = expected.assets.find(row => row.assetId === window.layout.assetId);
    if (!asset) throw new Error("Presenter asset is not in the exact admitted-project presentation catalog");
    if (asset.kind === "image" && window.layout.assetStart.numerator !== 0) throw new Error("Presenter still image requires assetStart 0/1");
  }
  return { ...structuredClone(input.plan), presenterLayouts: windows };
}

function assertCandidateTarget(accepted: unknown, candidate: unknown, proposal: TreatmentProposalV8): void {
  const target = objectValue(accepted, "accepted presenter target");
  const actual = canonicalJsonSha256(objectValue(candidate, "candidate presenter target"));
  if (actual === canonicalJsonSha256(target)) return;
  const decorated = { ...target, graphicsStyle: proposal.graphicsStyle, graphicsStyleRationale: proposal.graphicsStyleRationale };
  if (actual !== canonicalJsonSha256(decorated)) throw new Error("Candidate target differs from accepted target and exact proposal-authored graphics-style decoration");
}

/** Re-derive actual request windows; only the full builder's exact paired style decoration may differ on target. */
export function assertGuidedPresenterCandidate(input: { accepted: Record<string, unknown>; candidate: Record<string, unknown>;
  manifest: Record<string, unknown>; proposal: TreatmentProposalV8; evidence: GuidedPresenterFrameEvidence }): void {
  const proposal = parseTreatmentProposalV8(input.proposal);
  const expected = applyGuidedPresenterOperations({ plan: input.accepted, manifest: input.manifest, proposal,
    policy: guidedPresenterPolicy(input.accepted, input.manifest), evidence: input.evidence });
  assertCandidateTarget(input.accepted.target, input.candidate.target, proposal);
  const protectedKeys = [...COLLISIONS, "cutTrack", "cutDecisions"];
  if (protectedKeys.some(key => Object.hasOwn(input.candidate, key) !== Object.hasOwn(expected, key)
      || Object.hasOwn(expected, key) && canonicalJsonSha256(input.candidate[key]) !== canonicalJsonSha256(expected[key]))) {
    throw new Error("Candidate presenter layout or accepted cut/target differs from the actual V8 request");
  }
}
