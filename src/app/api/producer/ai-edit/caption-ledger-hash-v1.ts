import { createHash } from "node:crypto";
import type {
  CaptionCorrectionLedgerV1,
  CaptionTrackV1,
} from "@/lib/producer/edit-plan";

function stable(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(stable);
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, item]) => [key, stable(item)]),
  );
}

function asciiJson(value: unknown): string {
  return JSON.stringify(stable(value)).replace(/[^\x00-\x7E]/gu, (char) => {
    const code = char.codePointAt(0)!;
    if (code <= 0xffff) return `\\u${code.toString(16).padStart(4, "0")}`;
    const value = code - 0x10000;
    const high = 0xd800 + (value >> 10);
    const low = 0xdc00 + (value & 0x3ff);
    return `\\u${high.toString(16)}\\u${low.toString(16)}`;
  });
}

export function captionCorrectionLedgerHash(
  ledger: CaptionCorrectionLedgerV1,
): string {
  return createHash("sha256")
    .update(`sniper-caption-correction-ledger-v1\0${asciiJson(ledger)}`, "ascii")
    .digest("hex");
}

export function bindCaptionCorrectionHash(
  track: CaptionTrackV1,
  ledger: CaptionCorrectionLedgerV1,
): { track: CaptionTrackV1; changed: boolean } {
  if (track.transcriptCorrectionHash === undefined) {
    return { track, changed: false };
  }
  const digest = captionCorrectionLedgerHash(ledger);
  return {
    track: { ...track, transcriptCorrectionHash: digest },
    changed: track.transcriptCorrectionHash !== digest,
  };
}
