/** Pure admitted-project music metadata and projection; no DSP, source observation or rights approval. */
import { objectValue, sha256, stringValue } from "@/lib/producer/contracts/validation";
import { GUIDED_MUSIC_GAP_DB, parseTreatmentProposalV7, type TreatmentProposalV7 } from "@/lib/producer/contracts/treatment-proposal-v7";
import { canonicalJsonSha256 } from "./auto-edit-hash";

export interface GuidedMusicAsset {
  assetId: string; sourceSha256: string; sourceSizeBytes: number; admissionReceiptSha256: string;
  durationS: number; rights: "unverified";
}
export interface GuidedMusicPolicy {
  schemaVersion: 1; scope: "admitted-project-music-metadata-not-source-rights-or-quality-approval";
  acceptedMusicEnabled: boolean; gapDb: typeof GUIDED_MUSIC_GAP_DB; duck: true;
  fitting: "full-program-loop-crossfade-and-ending-fade"; assets: GuidedMusicAsset[];
  excludedBuiltinCount: number;
}

function musicEnabled(row: Record<string, unknown>, label: string): boolean {
  if (Object.hasOwn(row, "music") && typeof row.music !== "boolean") {
    throw new Error(`${label}.music must be an actual boolean when present`);
  }
  return row.music === true;
}

/** The locked target is only a mirror: actual accepted context remains the opt-in authority. */
export function assertGuidedMusicIntent(plan: Record<string, unknown>, intent: unknown): void {
  const target = objectValue(plan.target, "accepted music target"), operator = objectValue(intent, "accepted operator intent");
  if (musicEnabled(target, "accepted target") !== musicEnabled(operator, "accepted operator intent")) {
    throw new Error("Accepted target music differs from the stored operator intent; no accepted-plan retrofit or implicit intent change");
  }
}

function admittedAsset(row: Record<string, unknown>): GuidedMusicAsset {
  if (typeof row.originalPath !== "string" || !row.originalPath || typeof row.path !== "string" || !row.path
      || typeof row.admissionReceiptPath !== "string" || !row.admissionReceiptPath) {
    throw new Error("Music catalog needs complete admitted project references; arbitrary library rows are unsupported");
  }
  if (!Number.isSafeInteger(row.sourceSizeBytes) || Number(row.sourceSizeBytes) < 1
      || typeof row.duration !== "number" || !Number.isFinite(row.duration) || row.duration <= 0) {
    throw new Error("Music catalog requires positive admitted bytes and duration metadata");
  }
  return { assetId: stringValue(row.id, "music assetId", 128), sourceSha256: sha256(row.sourceSha256, "music source hash"),
    sourceSizeBytes: Number(row.sourceSizeBytes), admissionReceiptSha256: sha256(row.admissionReceiptSha256, "music admission hash"),
    durationS: row.duration, rights: "unverified" };
}

/** Reproduce metadata from the exact held manifest. Full admission/path/byte checks remain the executor's obligation. */
export function guidedMusicPolicy(plan: Record<string, unknown>, manifest: Record<string, unknown>): GuidedMusicPolicy {
  const target = objectValue(plan.target, "accepted music target"), rows = manifest.music ?? [];
  const acceptedMusicEnabled = musicEnabled(target, "accepted target");
  if (!Array.isArray(rows) || rows.length > 128) throw new Error("Music catalog exceeds its bounded 128-asset metadata contract");
  const ids = new Set<string>(), assets: GuidedMusicAsset[] = [];
  let excludedBuiltinCount = 0;
  for (const value of rows) {
    const row = objectValue(value, "manifest music asset"), id = stringValue(row.id, "music assetId", 128);
    if (ids.has(id)) throw new Error("Music catalog asset IDs are ambiguous");
    ids.add(id);
    if (row.source === "builtin" && row.originalPath == null) { excludedBuiltinCount++; continue; }
    assets.push(admittedAsset(row));
  }
  return { schemaVersion: 1, scope: "admitted-project-music-metadata-not-source-rights-or-quality-approval",
    acceptedMusicEnabled, gapDb: { ...GUIDED_MUSIC_GAP_DB }, duck: true,
    fitting: "full-program-loop-crossfade-and-ending-fade", assets, excludedBuiltinCount };
}

/** Add only the one requested bed. Accepted cuts/target/audio fields are untouched; no inherited music replacement. */
export function applyGuidedMusicOperations(input: { plan: Record<string, unknown>; manifest: Record<string, unknown>;
  proposal: TreatmentProposalV7; policy: GuidedMusicPolicy }): Record<string, unknown> {
  const current = parseTreatmentProposalV7(input.proposal), expected = guidedMusicPolicy(input.plan, input.manifest);
  if (canonicalJsonSha256(input.policy) !== canonicalJsonSha256(expected)) throw new Error("Music policy differs from exact accepted target and manifest metadata");
  const operation = current.operations.find((item) => item.type === "music-bed-full-program");
  if (!operation) return structuredClone(input.plan);
  if (!expected.acceptedMusicEnabled || Object.hasOwn(input.plan, "music")) {
    throw new Error("A new music bed requires accepted music:true and absent inherited music; explicit intent/replacement revision is required");
  }
  const selection = operation.music!;
  if (!expected.assets.some((item) => item.assetId === selection.assetId)) throw new Error("Selected music is not in the exact admitted-project catalog; no builtin, path or search fallback");
  return { ...structuredClone(input.plan), music: { enabled: true, assetId: selection.assetId, gapDb: selection.gapDb, duck: true } };
}

/** Re-derive music from the original request; hashes on a changed candidate are not selection authority. */
export function assertGuidedMusicCandidate(input: { accepted: Record<string, unknown>; candidate: Record<string, unknown>;
  manifest: Record<string, unknown>; proposal: TreatmentProposalV7 }): void {
  const expected = applyGuidedMusicOperations({ plan: input.accepted, manifest: input.manifest,
    proposal: input.proposal, policy: guidedMusicPolicy(input.accepted, input.manifest) });
  if (Object.hasOwn(input.candidate, "music") !== Object.hasOwn(expected, "music")
      || Object.hasOwn(expected, "music") && canonicalJsonSha256(input.candidate.music) !== canonicalJsonSha256(expected.music)) {
    throw new Error("Candidate music differs from the actual V7 request and accepted music state");
  }
}
