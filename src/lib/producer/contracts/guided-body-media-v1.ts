import { exactKeys, objectValue, sha256, uuid } from "./validation";
import { openingAbsolutePath } from "./guided-opening-media-v1";
import { parseOpeningRuntimeControl, type OpeningRuntimeControlV1 } from "./guided-opening-claim-v1";
import { MANUAL_SHORT_BODY_PROFILE, type BodyMediaProfile } from "./guided-media-profile";
import { isPresenterBodyProfile, type PresenterBodyProfile } from "./guided-presenter-profile";
import { CAPTION_BODY_PROFILE, CAPTION_SHORT_BODY_PROFILE,
  SCREENED_CAPTION_BODY_PROFILE, SCREENED_CAPTION_SHORT_BODY_PROFILE } from "./guided-caption-profile";
import { parseBodySourceColorReplayReferences, type BodySourceColorReplayReferencesV2 } from "./guided-body-source-color-replay-v2";

export const BODY_MEDIA_PROFILE = "held-source-float-own-screen-body-v1" as const;
export type CurrentBodyMediaProfile = BodyMediaProfile | PresenterBodyProfile;
/** Shared initial raw-graph observation class: metadata128 is not executable128. Python rechecks actual pixels. */
export const BODY_GRAPH_PIXEL_LIMIT = 64 * 1024 * 1024;
export const BODY_MEDIA_REFERENCES = ["admissionClaim", "heldInput", "approvedSnapshot", "openingInput", "openingResult",
  "budgetAdmission", "budgetPrecommit"] as const;
export interface BodyFileReference { path: string; sha256: string }
export interface GuidedBodyMediaInputV1 {
  schemaVersion: 1; kind: "guided-body-media-input"; scope: "private-body-candidate-not-approval";
  profile: CurrentBodyMediaProfile; requestId: string; executionId: string;
  references: Record<typeof BODY_MEDIA_REFERENCES[number], BodyFileReference>;
  runtime: OpeningRuntimeControlV1; selectedGraphicOrders: number[];
}
/** Explicit replay metadata, not body execution or source-color qualification. */
export interface GuidedBodyMediaInputV2 extends Omit<GuidedBodyMediaInputV1, "schemaVersion"> {
  schemaVersion: 2; sourceColorReplay: BodySourceColorReplayReferencesV2;
}
export type CurrentGuidedBodyMediaInput = GuidedBodyMediaInputV1 | GuidedBodyMediaInputV2;

/** Shape only. Each reference must separately bind retained bytes and the actual approved lineage. */
export function parseBodyFileReference(value: unknown): BodyFileReference {
  const row = objectValue(value, "body file reference");
  exactKeys(row, ["path", "sha256"], ["path", "sha256"], "body file reference");
  openingAbsolutePath(row.path); sha256(row.sha256, "body file SHA");
  return row as unknown as BodyFileReference;
}

/** Reference projection only: the original complete opening receipt remains separately hash-held and validated.
 * Probe facts (codec, clock, size, decode) must not be confused with the closed {path,sha256} reference DTO. */
export function projectBodyProgramReferences(value: unknown) {
  const record = objectValue(value, "opening result"), full = objectValue(record.fullProgram, "opening full program");
  const documents = objectValue(record.documents, "opening documents");
  const project = (value: unknown) => {
    const row = objectValue(value, "opening file observation");
    return parseBodyFileReference({ path: row.path, sha256: row.sha256 });
  };
  return { base: project(full.base), masterSelection: project({ path: full.fullMasterSelectionEventPath, sha256: full.fullMasterSelectionEventSha256 }),
    candidatePlan: project(documents.candidatePlan), manifest: project(documents.manifest) };
}

/** The structural limit is not proof that the actual graph/resources fit the rendering budget. */
export function parseBodyGraphicOrders(value: unknown): number[] {
  if (!Array.isArray(value) || value.length > 128 || value.some((order, index) => order !== index)) {
    throw new Error("Body graphic orders must cover every whole-plan row exactly once");
  }
  return value;
}

/** Conservative full-native input sum, including base. Refuse before rendering any unsupported workload. */
export function assertBodyGraphWorkload(target: unknown, graphicCount: number): void {
  const row = objectValue(target, "body native canvas"), width = row.width, height = row.height;
  if (!Number.isSafeInteger(width) || !Number.isSafeInteger(height) || Number(width) < 2 || Number(height) < 2
      || !Number.isSafeInteger(graphicCount) || graphicCount < 0 || graphicCount > 128) throw new Error("Body graph workload metadata is malformed");
  const pixels = Number(width) * Number(height) * (graphicCount + 1);
  if (!Number.isSafeInteger(pixels) || pixels > BODY_GRAPH_PIXEL_LIMIT) {
    throw new Error("Body full-native graph exceeds the qualified64MiPixel input ceiling; no graphics have been rendered");
  }
}

/** Closed metadata only; V1 body admission stays non-executable without separate owned activation. */
export function parseGuidedBodyMediaInput(value: unknown): GuidedBodyMediaInputV1 {
  return parseBodyInputProfile(value, BODY_MEDIA_PROFILE);
}

/** New class is explicit; the historical parser above remains closed to it. */
export function parseCurrentBodyMediaInput(value: unknown): CurrentGuidedBodyMediaInput {
  const row = objectValue(value, "body input"), profile = row.profile;
  if (profile !== BODY_MEDIA_PROFILE && profile !== MANUAL_SHORT_BODY_PROFILE
      && profile !== CAPTION_BODY_PROFILE && profile !== CAPTION_SHORT_BODY_PROFILE
      && profile !== SCREENED_CAPTION_BODY_PROFILE && profile !== SCREENED_CAPTION_SHORT_BODY_PROFILE
      && !isPresenterBodyProfile(profile)) throw new Error("Body media profile is unsupported");
  if (row.schemaVersion === 2) return parseBodyInputV2(row, profile);
  return parseBodyInputProfile(value, profile);
}

/** V2 has the same seven closed references plus one mandatory, detached original replay declaration. */
function parseBodyInputV2(row: Record<string, unknown>, profile: CurrentBodyMediaProfile): GuidedBodyMediaInputV2 {
  const keys = ["schemaVersion", "kind", "scope", "profile", "requestId", "executionId", "references", "runtime", "selectedGraphicOrders", "sourceColorReplay"];
  exactKeys(row, keys, keys, "body media input V2");
  const { sourceColorReplay, ...common } = row;
  const original = parseBodyInputProfile({ ...common, schemaVersion: 1 }, profile);
  return structuredClone({ ...original, schemaVersion: 2, sourceColorReplay: parseBodySourceColorReplayReferences(sourceColorReplay) });
}

function parseBodyInputProfile(value: unknown, profile: CurrentBodyMediaProfile): GuidedBodyMediaInputV1 {
  const row = objectValue(value, "body media input");
  const keys = ["schemaVersion", "kind", "scope", "profile", "requestId", "executionId", "references", "runtime", "selectedGraphicOrders"];
  exactKeys(row, keys, keys, "body media input");
  if (row.schemaVersion !== 1 || row.kind !== "guided-body-media-input" || row.scope !== "private-body-candidate-not-approval"
      || row.profile !== profile) throw new Error("Body media profile/role is unsupported");
  uuid(row.requestId, "body requestId"); uuid(row.executionId, "body executionId");
  const references = objectValue(row.references, "body references");
  exactKeys(references, [...BODY_MEDIA_REFERENCES], [...BODY_MEDIA_REFERENCES], "body references");
  BODY_MEDIA_REFERENCES.forEach((name) => parseBodyFileReference(references[name]));
  parseOpeningRuntimeControl(row.runtime); parseBodyGraphicOrders(row.selectedGraphicOrders);
  return row as unknown as GuidedBodyMediaInputV1;
}
