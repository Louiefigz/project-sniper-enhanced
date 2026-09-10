import {
  parseCutRepairTargetV1,
  type CutRepairTargetV1,
} from "@/lib/producer/contracts/cut-repair-target";
import {
  parseCutRepairAlternateTakeRequestV1,
  type CutRepairAlternateTakeRequestV1,
} from "./cut-repair-alternate-take-policy";

const STEPPED_ON_WORD =
  /\b(?:stepped|cut)\s+on\s+(?:one\s+of\s+)?(?:my\s+)?(?:word|words|phrase)\b/iu;
const RESTORE_SPEECH =
  /\b(?:restore|recover|put\s+back|extend)\b.{0,60}\b(?:word|phrase|syllable|speech)\b/iu;
const DAMAGED_SPEECH =
  /\b(?:word|phrase|syllable)\b.{0,60}\b(?:cut\s+off|clipped|missing|truncated)\b/iu;

type CutRepairMode =
  | "analyze"
  | "reopen"
  | "prepare"
  | "review"
  | "approve"
  | "execute";

export interface CutRepairDirectiveV1 {
  schemaVersion: 1;
  operation: "cut.restoreSpeech";
  mode: CutRepairMode;
  packageHash?: string;
  idempotencyKey?: string;
  requestedAt?: string;
  audition?: CutRepairOperatorAuditionAttestationV1;
  alternateTake?: CutRepairAlternateTakeRequestV1;
  target: CutRepairTargetV1;
}

export interface CutRepairOperatorAuditionAttestationV1 {
  schemaVersion: 1;
  kind: "cut-repair-operator-audition-attestation";
  preparationHash: string;
  candidateDescriptorHash: string;
  candidateSha256: string;
  operatorReceiptId: string;
  reviewedAt: string;
  decision: "approved" | "rejected";
  reportedDamageResolved: boolean;
}

function object(value: unknown, label: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} must be an object`);
  }
  return value as Record<string, unknown>;
}

function closed(
  value: Record<string, unknown>,
  allowed: readonly string[],
  required: readonly string[],
  label: string,
): void {
  const extras = Object.keys(value).filter((key) => !allowed.includes(key));
  const missing = required.filter((key) => !(key in value));
  if (extras.length || missing.length) {
    throw new Error(
      `${label} has unsupported or missing fields: `
      + [...extras, ...missing].join(", "),
    );
  }
}

function boundedString(
  value: unknown,
  label: string,
  maximum: number,
): string {
  if (typeof value !== "string" || !value.trim()
      || Array.from(value).length > maximum) {
    throw new Error(`${label} must be 1..${maximum} characters`);
  }
  return value.trim();
}

function requestIdentity(
  row: Record<string, unknown>,
  mode: "reopen" | "prepare" | "approve",
): { idempotencyKey: string; requestedAt: string } {
  if (typeof row.idempotencyKey !== "string"
      || !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/u
        .test(row.idempotencyKey)) {
    throw new Error(`cut.restoreSpeech ${mode} requires a canonical UUID`);
  }
  if (typeof row.requestedAt !== "string"
      || !Number.isFinite(Date.parse(row.requestedAt))) {
    throw new Error(`cut.restoreSpeech ${mode} requires requestedAt`);
  }
  return {
    idempotencyKey: row.idempotencyKey,
    requestedAt: row.requestedAt,
  };
}

function hash(value: unknown, label: string): string {
  if (typeof value !== "string" || !/^[0-9a-f]{64}$/u.test(value)) {
    throw new Error(`${label} must be one lowercase SHA-256`);
  }
  return value;
}

function parseAudition(
  value: unknown,
): CutRepairOperatorAuditionAttestationV1 {
  const row = object(value, "cut repair operator audition");
  const keys = [
    "schemaVersion", "kind", "preparationHash",
    "candidateDescriptorHash", "candidateSha256", "operatorReceiptId",
    "reviewedAt", "decision", "reportedDamageResolved",
  ];
  closed(row, keys, keys, "cut repair operator audition");
  if (row.schemaVersion !== 1
      || row.kind !== "cut-repair-operator-audition-attestation"
      || (row.decision !== "approved" && row.decision !== "rejected")
      || typeof row.reportedDamageResolved !== "boolean"
      || typeof row.reviewedAt !== "string"
      || !Number.isFinite(Date.parse(row.reviewedAt))) {
    throw new Error("cut repair operator audition is malformed");
  }
  return {
    schemaVersion: 1,
    kind: "cut-repair-operator-audition-attestation",
    preparationHash: hash(row.preparationHash, "audition preparationHash"),
    candidateDescriptorHash: hash(
      row.candidateDescriptorHash, "audition candidateDescriptorHash"),
    candidateSha256: hash(row.candidateSha256, "audition candidateSha256"),
    operatorReceiptId: boundedString(
      row.operatorReceiptId, "audition operatorReceiptId", 160),
    reviewedAt: row.reviewedAt,
    decision: row.decision,
    reportedDamageResolved: row.reportedDamageResolved,
  };
}

function parseMode(row: Record<string, unknown>): CutRepairMode {
  const modes: CutRepairMode[] = [
    "analyze", "reopen", "prepare", "review", "approve", "execute",
  ];
  if (row.schemaVersion !== 1
      || !modes.includes(row.mode as CutRepairMode)) {
    throw new Error("cut.restoreSpeech API mode is unsupported");
  }
  return row.mode as CutRepairMode;
}

function validateModeFields(
  row: Record<string, unknown>,
  mode: CutRepairMode,
): void {
  if (["review", "approve", "execute"].includes(mode)
      && (typeof row.packageHash !== "string"
        || !/^[0-9a-f]{64}$/u.test(row.packageHash))) {
    throw new Error(`cut.restoreSpeech ${mode} requires packageHash`);
  }
  if ((mode === "analyze" || mode === "reopen")
      && row.packageHash !== undefined) {
    throw new Error(
      `cut.restoreSpeech ${mode} cannot select an execution package`);
  }
  if (mode === "prepare" && row.packageHash !== undefined) {
    throw new Error("cut.restoreSpeech prepare cannot promote a package");
  }
  if (mode !== "reopen" && mode !== "prepare" && mode !== "approve"
      && (row.idempotencyKey !== undefined || row.requestedAt !== undefined)) {
    throw new Error(
      "cut.restoreSpeech request identity is only valid for reopen, prepare, "
      + "or approve");
  }
  if (mode !== "approve" && row.audition !== undefined) {
    throw new Error(
      "cut.restoreSpeech operator audition is only valid for approve");
  }
  if (mode === "approve" && row.audition === undefined) {
    throw new Error("cut.restoreSpeech approve requires operator audition");
  }
  if (mode !== "prepare" && row.alternateTake !== undefined) {
    throw new Error(
      "cut.restoreSpeech alternateTake is only valid for prepare");
  }
}

function modeOptions(
  row: Record<string, unknown>,
  mode: CutRepairMode,
): Pick<
  CutRepairDirectiveV1,
  "packageHash" | "idempotencyKey" | "requestedAt" | "audition"
    | "alternateTake"
> {
  const identity = mode === "reopen"
    || mode === "prepare"
    || mode === "approve"
    ? requestIdentity(row, mode)
    : undefined;
  const packageHash = ["review", "approve", "execute"].includes(mode)
    ? row.packageHash as string : undefined;
  const audition = mode === "approve"
    ? parseAudition(row.audition) : undefined;
  const alternateTake = mode === "prepare" && row.alternateTake !== undefined
    ? parseCutRepairAlternateTakeRequestV1(row.alternateTake) : undefined;
  return {
    ...(packageHash ? { packageHash } : {}),
    ...(identity ?? {}),
    ...(audition ? { audition } : {}),
    ...(alternateTake ? { alternateTake } : {}),
  };
}

/**
 * Parse each closed lifecycle mode without accepting caller-minted evidence.
 */
export function parseCutRepairDirective(
  value: unknown,
): CutRepairDirectiveV1 | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const row = value as Record<string, unknown>;
  if (row.operation !== "cut.restoreSpeech") return null;
  closed(
    row,
    [
      "schemaVersion", "operation", "mode", "target", "packageHash",
      "idempotencyKey", "requestedAt", "audition", "alternateTake",
    ],
    ["schemaVersion", "operation", "mode", "target"],
    "cut.restoreSpeech directive",
  );
  const mode = parseMode(row);
  validateModeFields(row, mode);
  return {
    schemaVersion: 1,
    operation: "cut.restoreSpeech",
    mode,
    ...modeOptions(row, mode),
    target: parseCutRepairTargetV1(row.target),
  };
}

/**
 * Detect requests that require first-class source/sample repair authority.
 *
 * This is intentionally conservative: ordinary cut requests continue through
 * the legacy writer, while obvious damaged-speech restoration fails closed.
 */
export function isWordSafeCutRepairIntent(value: unknown): boolean {
  if (typeof value !== "string") return false;
  const request = value.trim();
  return STEPPED_ON_WORD.test(request)
    || RESTORE_SPEECH.test(request)
    || DAMAGED_SPEECH.test(request);
}

export const CUT_REPAIR_ROUTE_BLOCKER =
  "Word-safe speech repair requires the first-class cut.restoreSpeech "
  + "execution route. The plan-only Ask Editor writer was not run, and no "
  + "timeline change was made.";
