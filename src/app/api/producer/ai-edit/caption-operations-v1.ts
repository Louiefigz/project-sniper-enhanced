import { createHash } from "node:crypto";
import type {
  CaptionCorrectionLedgerV1,
  CaptionGroupV1,
  CaptionTrackV1,
  EditPlan,
} from "@/lib/producer/edit-plan";
import { bindCaptionCorrectionHash } from "./caption-ledger-hash-v1";
import { captionTextWithinLimit } from "./caption-text-contract-v1";

const WORD_ID = /^w-[0-9a-f]{16}$/u;
const STYLE_ID = /^[a-z][a-z0-9._-]{0,63}$/u;
const MODES = ["line", "karaoke-word", "karaoke-phrase"] as const;
const PLACEMENTS = [
  "bottom-center", "lower-third", "center", "top-center",
] as const;

export interface SetCaptionRangeV1 {
  kind: "set-caption-range";
  wordIds: string[];
  styleId: string;
  mode: typeof MODES[number];
  placement: typeof PLACEMENTS[number];
  language?: string;
  suppressUnderSceneIds?: string[];
}

export interface CorrectCaptionWordsV1 {
  kind: "correct-caption-words";
  sourceWordIds: string[];
  displayTokens: string[];
  reason?: string;
}

export interface CaptionReconcileResult {
  plan: EditPlan;
  stampedGroups: number;
  stampedCorrections: number;
  stampedCorrectionHash: boolean;
}
function exactKeys(
  row: Record<string, unknown>,
  allowed: readonly string[],
  label: string,
): void {
  const unknown = Object.keys(row).filter((key) => !allowed.includes(key));
  if (unknown.length) throw new Error(`${label} has unknown fields: ${unknown.join(", ")}`);
}

function stableId(prefix: "cg" | "cc", domain: string, values: string[]): string {
  const digest = createHash("sha256")
    .update(`${domain}\0${values.join("\0")}`)
    .digest("hex")
    .slice(0, 16);
  return `${prefix}-${digest}`;
}

type StringArrayRules = { pattern?: RegExp; unique?: boolean; maximum?: number };
function strings(
  value: unknown, label: string, rules: StringArrayRules = {},
): string[] {
  const unique = rules.unique ?? true;
  const maximum = rules.maximum ?? Number.MAX_SAFE_INTEGER;
  if (!Array.isArray(value) || !value.length
      || value.some((item) => typeof item !== "string" || !item
        || Array.from(item).length > maximum
        || (rules.pattern ? !rules.pattern.test(item) : false))
      || (unique && new Set(value).size !== value.length)) {
    throw new Error(`${label} must be a non-empty string array`);
  }
  return [...value] as string[];
}

function member<T extends readonly string[]>(
  value: unknown,
  choices: T,
  label: string,
): T[number] {
  if (typeof value !== "string" || !choices.includes(value)) {
    throw new Error(`${label} is unsupported`);
  }
  return value as T[number];
}

function group(value: unknown): CaptionGroupV1 {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("caption group must be an object");
  }
  const row = value as Record<string, unknown>;
  exactKeys(row, [
    "groupId", "anchor", "styleId", "mode", "placement", "language",
    "suppressUnderSceneIds",
  ], "caption group");
  const anchor = row.anchor as Record<string, unknown> | undefined;
  if (!anchor || anchor.kind !== "word-range") {
    throw new Error("caption group anchor must be word-range");
  }
  exactKeys(anchor, ["kind", "wordIds"], "caption anchor");
  const wordIds = strings(anchor.wordIds, "caption wordIds", { pattern: WORD_ID });
  if (typeof row.styleId !== "string" || !STYLE_ID.test(row.styleId)) {
    throw new Error("caption styleId is malformed");
  }
  const expectedId = stableId("cg", "sniper-caption-group-v1", wordIds);
  if (row.language !== undefined
      && (typeof row.language !== "string"
        || !/^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$/u.test(row.language))) {
    throw new Error("caption language is malformed");
  }
  return {
    groupId: expectedId,
    anchor: { kind: "word-range", wordIds },
    styleId: row.styleId,
    mode: member(row.mode, MODES, "caption mode"),
    placement: member(row.placement, PLACEMENTS, "caption placement"),
    ...(typeof row.language === "string" ? { language: row.language } : {}),
    ...(row.suppressUnderSceneIds === undefined ? {} : {
      suppressUnderSceneIds: strings(row.suppressUnderSceneIds,
        "caption suppression scene ids", { maximum: 128 }),
    }),
  };
}

function track(value: unknown): CaptionTrackV1 {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("captionsTrack must be CaptionTrackV1");
  }
  const row = value as Record<string, unknown>;
  exactKeys(row, [
    "schemaVersion", "source", "defaultPolicy", "groups",
    "transcriptCorrectionHash",
  ], "captionsTrack");
  if (row.schemaVersion !== 1 || row.source !== "kept-transcript"
      || !Array.isArray(row.groups)) {
    throw new Error("captionsTrack version, source, or groups are invalid");
  }
  const groups = row.groups.map(group);
  const claimed = groups.flatMap((item) => item.anchor.wordIds);
  if (new Set(claimed).size !== claimed.length) {
    throw new Error("caption ranges overlap on stable word ids");
  }
  const correctionHash = row.transcriptCorrectionHash;
  if (correctionHash !== undefined
      && (typeof correctionHash !== "string"
        || !/^[0-9a-f]{64}$/u.test(correctionHash))) {
    throw new Error("caption correction hash is malformed");
  }
  return {
    schemaVersion: 1,
    source: "kept-transcript",
    defaultPolicy: member(
      row.defaultPolicy,
      ["off", "line", "karaoke"] as const,
      "caption default policy",
    ),
    groups,
    ...(typeof correctionHash === "string"
      ? { transcriptCorrectionHash: correctionHash } : {}),
  };
}

function correction(value: unknown) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("caption correction must be an object");
  }
  const row = value as Record<string, unknown>;
  exactKeys(row, [
    "correctionId", "sourceWordIds", "displayTokens", "timingPolicy", "reason",
  ], "caption correction");
  const wordIds = strings(row.sourceWordIds, "correction wordIds",
    { pattern: WORD_ID });
  const displayTokens = strings(row.displayTokens, "displayTokens",
    { unique: false, maximum: 256 });
  if (displayTokens.some((item) => !captionTextWithinLimit(item, 256) || /[\\\r\n\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]/u.test(item))) throw new Error("displayTokens contain invalid text or caption control characters");
  if (row.timingPolicy !== undefined
      && row.timingPolicy !== "proportional-codepoints") {
    throw new Error("caption correction timingPolicy is unsupported");
  }
  if (row.reason !== undefined
      && !captionTextWithinLimit(row.reason, 500)) {
    throw new Error("caption correction reason is invalid");
  }
  return {
    correctionId: stableId(
      "cc", "sniper-caption-correction-v1", wordIds,
    ),
    sourceWordIds: wordIds,
    displayTokens,
    timingPolicy: "proportional-codepoints" as const,
    ...(captionTextWithinLimit(row.reason, 500)
      ? { reason: row.reason } : {}),
  };
}

function ledger(value: unknown): CaptionCorrectionLedgerV1 {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("captionCorrectionLedger must be an object");
  }
  const row = value as Record<string, unknown>;
  exactKeys(
    row,
    ["schemaVersion", "kind", "corrections"],
    "caption correction ledger",
  );
  if (row.schemaVersion !== 1 || row.kind !== "caption-correction-ledger"
      || !Array.isArray(row.corrections)) {
    throw new Error("caption correction ledger is invalid");
  }
  const corrections = row.corrections.map(correction);
  const words = corrections.flatMap((item) => item.sourceWordIds);
  if (new Set(words).size !== words.length) {
    throw new Error("caption corrections overlap on stable word ids");
  }
  return {
    schemaVersion: 1, kind: "caption-correction-ledger", corrections,
  };
}

export function reconcileCaptionAuthority(
  plan: EditPlan,
): CaptionReconcileResult {
  if (plan.captionsTrack === undefined) {
    if (plan.captionCorrectionLedger !== undefined || plan.captionStyles !== undefined) {
      throw new Error("caption sidecars require captionsTrack");
    }
    return { plan, stampedGroups: 0, stampedCorrections: 0, stampedCorrectionHash: false };
  }
  const normalizedTrack = track(plan.captionsTrack);
  const hasLedger = plan.captionCorrectionLedger !== undefined;
  const normalizedLedger = ledger(plan.captionCorrectionLedger ?? {
    schemaVersion: 1, kind: "caption-correction-ledger", corrections: [],
  });
  const oldGroups = plan.captionsTrack.groups ?? [];
  const oldCorrections = plan.captionCorrectionLedger?.corrections ?? [];
  const binding = bindCaptionCorrectionHash(normalizedTrack, normalizedLedger);
  const stampedGroups = normalizedTrack.groups.filter(
    (item, index) => item.groupId !== oldGroups[index]?.groupId,
  ).length;
  const stampedCorrections = normalizedLedger.corrections.filter(
    (item, index) => item.correctionId !== oldCorrections[index]?.correctionId,
  ).length;
  return {
    plan: {
      ...plan,
      captionsTrack: binding.track,
      ...(hasLedger ? { captionCorrectionLedger: normalizedLedger } : {}),
    },
    stampedGroups,
    stampedCorrections,
    stampedCorrectionHash: binding.changed,
  };
}

export function setCaptionRange(
  plan: EditPlan,
  operation: SetCaptionRangeV1,
): EditPlan {
  const current = plan.captionsTrack ?? {
    schemaVersion: 1, source: "kept-transcript",
    defaultPolicy: "off", groups: [],
  };
  const next = group({
    anchor: { kind: "word-range", wordIds: operation.wordIds },
    styleId: operation.styleId,
    mode: operation.mode,
    placement: operation.placement,
    ...(operation.language ? { language: operation.language } : {}),
    ...(operation.suppressUnderSceneIds ? {
      suppressUnderSceneIds: operation.suppressUnderSceneIds,
    } : {}),
  });
  const groups = current.groups.filter((item) => item.groupId !== next.groupId);
  return reconcileCaptionAuthority({
    ...plan, captionsTrack: { ...current, groups: [...groups, next] },
  }).plan;
}

export function correctCaptionWords(
  plan: EditPlan,
  operation: CorrectCaptionWordsV1,
): EditPlan {
  const current = plan.captionCorrectionLedger ?? {
    schemaVersion: 1, kind: "caption-correction-ledger", corrections: [],
  };
  const next = correction({
    sourceWordIds: operation.sourceWordIds,
    displayTokens: operation.displayTokens,
    ...(operation.reason ? { reason: operation.reason } : {}),
  });
  const corrections = current.corrections.filter(
    (item) => item.correctionId !== next.correctionId,
  );
  return reconcileCaptionAuthority({
    ...plan,
    captionCorrectionLedger: { ...current, corrections: [...corrections, next] },
    captionsTrack: plan.captionsTrack ?? {
      schemaVersion: 1, source: "kept-transcript",
      defaultPolicy: "off", groups: [],
    },
  }).plan;
}
