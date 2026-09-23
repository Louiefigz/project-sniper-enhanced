import type { ReferenceStrategy } from "./intent-presets";

export const VERIFIED_MIMIC_RELEASED = false as const;

export const VERIFIED_MIMIC_BLOCKERS = [
  "three materially different approved packs with explicit waiver coverage",
  "retained reviewer-disagreement adjudication evidence",
  "proved-scene closure for every realized mechanic",
  "itemized unsupported-mechanic disclosure before execution",
  "rights evidence for every reference-derived identity asset",
  "unseen-footage frozen-tolerance and three-reviewer no-regression evidence",
  "separate onboarding and approved-pack editing-time receipts",
] as const;

export type ReferenceExecutionClass =
  | "reference-inspired"
  | "provisional-style-candidate";

/** Translate the legacy strategy ID into the truthful current product promise. */
export function referenceExecutionClass(
  strategy: ReferenceStrategy,
): ReferenceExecutionClass {
  if (strategy === "mimic") return "reference-inspired";
  if (strategy === "new-style") return "provisional-style-candidate";
  throw new Error("Legacy style extension is retired; select the actual reference video");
}
