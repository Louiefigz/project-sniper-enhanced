/** Explicit original-source replay transport. Parsing is not native proof, selection or approval. */
import { exactKeys, objectValue, sha256, stringValue, uuid } from "./validation";
import { openingAbsolutePath } from "./guided-opening-media-v1";
import { parseBoundedJson } from "./bounded-json";
import { BODY_MEDIA_REFERENCES, parseBodyFileReference } from "./guided-body-media-v1";
import { parseBodySourceColorReplayReferences, type BodySourceColorReplayReferencesV2 } from "./guided-body-source-color-replay-v2";
import { parseBodyMediaCompletion, parseBodyMediaReadback, type BodyMediaCompletionV1, type BodyMediaReadbackV1 } from "./guided-body-result-v1";
import type { SourceColorMediaEvidenceRef } from "./guided-opening-result-v2";
import { SCREENED_CAPTION_BODY_PROFILE, SCREENED_CAPTION_SHORT_BODY_PROFILE } from "./guided-caption-profile";
import { PRESENTER_CAPTION_BODY_PROFILE, PRESENTER_CAPTION_SHORT_BODY_PROFILE } from "./guided-presenter-profile";

export const BODY_SOURCE_COLOR_READBACK_SCOPE = "exact-source-color-held-private-body-media-not-body-or-delivery-approval" as const;
export const BODY_SOURCE_COLOR_REPLAY_SCOPE = "original-opening-observation-and-base-consumption-not-new-grade-or-approval" as const;
export const BODY_SOURCE_COLOR_STAGES = ["body-original-source-color-observations", "body-original-base-picture-consumption"] as const;
export const BODY_SOURCE_COLOR_READBACK_STAGES = ["body-read-control", "body-read-current-inputs", "body-read-held-result",
  "body-read-current-pipeline", ...BODY_SOURCE_COLOR_STAGES, "body-read-whole-base-master", "body-read-all-graphics",
  "body-read-final-media-and-qc", "body-read-final-revalidation"] as const;
export interface BodySourceColorReadback {
  schemaVersion: 1; kind: "guided-body-original-source-color-replay"; scope: typeof BODY_SOURCE_COLOR_REPLAY_SCOPE;
  sourceColorEvidence: SourceColorMediaEvidenceRef; observationRecordHash: string; consumptionRecordHash: string;
  sourceColorRecordsReplayed: true; basePictureConsumptionVerified: true;
  gamutMeasured: false; gradeApplied: false; colorQualified: false; bodyApproved: false; deliveryApproved: false;
}
export interface BodySourceColorResultFields { sourceColorReplay: BodySourceColorReplayReferencesV2; sourceColorReadback: BodySourceColorReadback }
export interface BodyMediaCompletionV2 extends Omit<BodyMediaCompletionV1, "schemaVersion">, BodySourceColorResultFields { schemaVersion: 2 }
export interface BodyMediaReadbackV2 extends Omit<BodyMediaReadbackV1, "schemaVersion" | "scope">, BodySourceColorResultFields {
  schemaVersion: 2; scope: typeof BODY_SOURCE_COLOR_READBACK_SCOPE;
}
export interface BodyMediaResultV2 extends BodySourceColorResultFields, Record<string, unknown> {
  schemaVersion: 2; kind: "guided-body-media-result"; status: "complete"; scope: "private-body-candidate-not-approval";
  profile: string; executionId: string; inputPath: string; inputSha256: string;
  executionActivationPath: string; executionActivationSha256: string; receiptHash: string;
  references: Record<typeof BODY_MEDIA_REFERENCES[number], ReturnType<typeof parseBodyFileReference>>;
  bodyApproved: false; deliveryApproved: false;
}
export type CurrentBodyMediaCompletion = BodyMediaCompletionV1 | BodyMediaCompletionV2;
export type CurrentBodyMediaReadback = BodyMediaReadbackV1 | BodyMediaReadbackV2;
const SOURCE_KEYS = ["sourceColorReplay", "sourceColorReadback"];
const FALSE_FLAGS = ["gamutMeasured", "gradeApplied", "colorQualified", "bodyApproved", "deliveryApproved"] as const;

/** Same original opening artifact role, never this body's newly composed candidate. */
function evidence(value: unknown, replay: BodySourceColorReplayReferencesV2): SourceColorMediaEvidenceRef {
  const row = objectValue(value, "body original source evidence"), keys = ["path", "sha256", "sizeBytes", "receiptHash"];
  exactKeys(row, keys, keys, "body original source evidence"); openingAbsolutePath(row.path);
  sha256(row.sha256, "body source evidence raw SHA"); sha256(row.receiptHash, "body source evidence semantic SHA");
  const root = replay.input.path.slice(0, -"source-color/input.json".length);
  if (row.path !== `${root}media-output/source-color-evidence.json` || !Number.isSafeInteger(row.sizeBytes)
      || Number(row.sizeBytes) < 1 || Number(row.sizeBytes) > 16 * 1024 * 1024) throw new Error("Body source evidence role or bound differs");
  return row as unknown as SourceColorMediaEvidenceRef;
}

/** Hash values describe completed actual replay holders; only an independently owned worker/read can establish them. */
export function parseBodySourceColorReadback(value: unknown, replay: BodySourceColorReplayReferencesV2): BodySourceColorReadback {
  const row = objectValue(value, "body original source replay result");
  const keys = ["schemaVersion", "kind", "scope", "sourceColorEvidence", "observationRecordHash", "consumptionRecordHash",
    "sourceColorRecordsReplayed", "basePictureConsumptionVerified", ...FALSE_FLAGS];
  exactKeys(row, keys, keys, "body original source replay result");
  if (row.schemaVersion !== 1 || row.kind !== "guided-body-original-source-color-replay" || row.scope !== BODY_SOURCE_COLOR_REPLAY_SCOPE
      || row.sourceColorRecordsReplayed !== true || row.basePictureConsumptionVerified !== true
      || FALSE_FLAGS.some(key => row[key] !== false)) throw new Error("Body source replay cannot omit coverage or grant grade/approval");
  evidence(row.sourceColorEvidence, replay); sha256(row.observationRecordHash, "body observation record SHA");
  sha256(row.consumptionRecordHash, "body consumption record SHA"); return structuredClone(row) as unknown as BodySourceColorReadback;
}

function sourceFields(row: Record<string, unknown>): BodySourceColorResultFields {
  const sourceColorReplay = parseBodySourceColorReplayReferences(row.sourceColorReplay);
  return { sourceColorReplay, sourceColorReadback: parseBodySourceColorReadback(row.sourceColorReadback, sourceColorReplay) };
}

/** Retain legacy parsing exactly, including its existing scalar and output-size policy. */
function version(stdout: string): unknown {
  if (Buffer.byteLength(stdout, "utf8") > 128 * 1024 || stdout.includes("\0")) throw new Error("Body output is unsafe or over its closed bound");
  return objectValue(JSON.parse(stdout.trim()), "body output").schemaVersion;
}
export function parseCurrentBodyMediaCompletion(stdout: string): CurrentBodyMediaCompletion {
  return version(stdout) === 2 ? parseSourceColorBodyCompletion(stdout) : parseBodyMediaCompletion(stdout);
}
export function parseCurrentBodyMediaReadback(stdout: string): CurrentBodyMediaReadback {
  return version(stdout) === 2 ? parseSourceColorBodyReadback(stdout) : parseBodyMediaReadback(stdout);
}

/** V2 alone adds the required exact original replay and actual completed bridge projection. */
export function parseSourceColorBodyCompletion(stdout: string): BodyMediaCompletionV2 {
  const row = objectValue(parseBoundedJson(stdout, "body source completion"), "body source completion");
  const { sourceColorReplay: _replay, sourceColorReadback: _proof, ...common } = row; void _replay; void _proof;
  if (row.schemaVersion !== 2) throw new Error("Body source completion requires explicit schema2");
  parseBodyMediaCompletion(JSON.stringify({ ...common, schemaVersion: 1 }));
  if (typeof row.receiptPath !== "string" || !row.receiptPath.endsWith("/body-result.json")) throw new Error("Body result has the wrong role");
  return { ...row, ...sourceFields(row) } as unknown as BodyMediaCompletionV2;
}

function readStages(row: Record<string, unknown>): void {
  if (!Array.isArray(row.stages) || row.stages.length !== BODY_SOURCE_COLOR_READBACK_STAGES.length) throw new Error("Body source read stages are incomplete");
  let total = 0;
  row.stages.forEach((value, index) => {
    const stage = objectValue(value, "body source read stage"), keys = ["stage", "status", "elapsedMs"];
    exactKeys(stage, keys, keys, "body source read stage");
    if (stage.stage !== BODY_SOURCE_COLOR_READBACK_STAGES[index] || stage.status !== "complete" || !Number.isSafeInteger(stage.elapsedMs)
        || Number(stage.elapsedMs) < 0 || Number(stage.elapsedMs) > Number(row.elapsedMs)) throw new Error("Body source read stage failed or reordered");
    total += Number(stage.elapsedMs);
  });
  if (total > Number(row.elapsedMs) + Math.ceil(BODY_SOURCE_COLOR_READBACK_STAGES.length / 2)) throw new Error("Body source stage sum exceeds elapsed work");
}

/** The caller still owes actual current-input, process cleanup and original body-clock ownership. */
export function parseSourceColorBodyReadback(stdout: string): BodyMediaReadbackV2 {
  const row = objectValue(parseBoundedJson(stdout, "body source readback"), "body source readback");
  const { sourceColorReplay: _replay, sourceColorReadback: _proof, ...common } = row; void _replay; void _proof;
  if (row.schemaVersion !== 2 || row.scope !== BODY_SOURCE_COLOR_READBACK_SCOPE) throw new Error("Body source readback requires explicit schema2 scope");
  readStages(row);
  const stages = (row.stages as unknown[]).filter((_value, index) => index !== 4 && index !== 5);
  parseBodyMediaReadback(JSON.stringify({ ...common, schemaVersion: 1, scope: "exact-held-private-body-media-not-body-or-delivery-approval", stages }));
  return { ...row, ...sourceFields(row) } as unknown as BodyMediaReadbackV2;
}

/** Raw body work may include existing graphic/caption stages; both source stages must be unique, complete and ordered. */
function workStages(value: unknown): void {
  if (!Array.isArray(value) || !value.length || value.length > 2048) throw new Error("Body work stages exceed complete bounded coverage");
  const names = value.map(item => {
    const row = objectValue(item, "body completed work stage");
    if (row.status !== "complete" || typeof row.stage !== "string" || !Number.isSafeInteger(row.elapsedMs)
        || Number(row.elapsedMs) < 0 || Number(row.elapsedMs) > 3_300_000) throw new Error("Body work stage is failed or unbounded");
    return row.stage;
  });
  if (BODY_SOURCE_COLOR_STAGES.some(name => names.filter(value => value === name).length !== 1)
      || names.indexOf(BODY_SOURCE_COLOR_STAGES[0]) >= names.indexOf(BODY_SOURCE_COLOR_STAGES[1])) throw new Error("Body original replay stages are absent or reordered");
}

/** Closed envelope only. Complex existing media/pipeline/graphics evidence remains the actual independent reader's responsibility. */
export function parseSourceColorBodyMediaResult(value: unknown): BodyMediaResultV2 {
  const row = objectValue(value, "body source media result");
  const keys = ["schemaVersion", "kind", "status", "scope", "profile", "executionId", "inputPath", "inputSha256",
    "executionActivationPath", "executionActivationSha256", "references", "pipeline", "workload", "templates", "graphics",
    "resolvedClips", "composition", "programDeliveryReceipt", "media", "stages", "bodyApproved", "deliveryApproved", "receiptHash", ...SOURCE_KEYS];
  const screened = [SCREENED_CAPTION_BODY_PROFILE, SCREENED_CAPTION_SHORT_BODY_PROFILE,
    PRESENTER_CAPTION_BODY_PROFILE, PRESENTER_CAPTION_SHORT_BODY_PROFILE].some(profile => profile === row.profile);
  if (screened) keys.push("captionLayoutScreen"); exactKeys(row, keys, keys, "body source media result");
  if (row.schemaVersion !== 2 || row.kind !== "guided-body-media-result" || row.status !== "complete" || row.scope !== "private-body-candidate-not-approval"
      || row.bodyApproved !== false || row.deliveryApproved !== false) throw new Error("Body source result has an unsupported role or approval");
  stringValue(row.profile, "body result profile", 128); uuid(row.executionId, "body executionId");
  openingAbsolutePath(row.inputPath); openingAbsolutePath(row.executionActivationPath);
  for (const key of ["inputSha256", "executionActivationSha256", "receiptHash"]) sha256(row[key], key);
  const references = objectValue(row.references, "body original references");
  exactKeys(references, [...BODY_MEDIA_REFERENCES], [...BODY_MEDIA_REFERENCES], "body original references");
  BODY_MEDIA_REFERENCES.forEach(name => parseBodyFileReference(references[name])); workStages(row.stages);
  return { ...structuredClone(row), ...sourceFields(row) } as BodyMediaResultV2;
}
