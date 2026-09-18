/**
 * LEGACY Director plan v1 field values, kept only to read retained records.
 *
 * Plans saved before 2026-09-18 used these audit keys and awareness levels. They
 * are data-format identifiers for old JSON, not current guidance: no current
 * prompt, criterion, library entry or document uses them, and every new decision
 * is plan v2 (native-director-v2.ts, resources/director/README.md). Removing this
 * file makes every retained v1 plan unreadable.
 */
export const LEGACY_V1_AUDIT_KEYS = ["knowledgeGap", "belief", "novelty", "relevance", "clarity"] as const;
export const LEGACY_V1_AWARENESS = ["unaware", "problem_aware", "solution_aware", "product_aware", "most_aware"] as const;
