import { canonicalJsonSha256 } from "@/lib/server/auto-edit-hash";

const PICTURE_TARGET_FIELDS = [
  "mode", "aspect", "width", "height", "fps",
] as const;

function pictureTarget(plan: Record<string, unknown>): Record<string, unknown> | null {
  const target = plan.target;
  if (!target || typeof target !== "object" || Array.isArray(target)) return null;
  const source = target as Record<string, unknown>;
  return Object.fromEntries(
    PICTURE_TARGET_FIELDS
      .filter((field) => Object.hasOwn(source, field))
      .map((field) => [field, source[field]]),
  );
}

/** Bind delivery geometry/mode and cut identity, excluding visual treatment. */
export function compatibilityPlanHash(
  plan: Record<string, unknown>,
  cutTrackDigest: string,
  cutDecisionsDigest: string,
): string {
  return canonicalJsonSha256({
    target: pictureTarget(plan),
    cutTrackDigest,
    cutDecisionsDigest,
  });
}
