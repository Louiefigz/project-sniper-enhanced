export interface RelatedUse {
  candidateId: string;
  modality: string;
  sourceRecordId: string | null;
  sourceSha256: string | null;
  familyId: string;
  anatomy: string;
  development: string;
  planSha256: string;
}

export interface VisualUsageProject {
  projectId: string;
  approvedAt: string;
  planSha256: string;
  applicationSha256: string;
  packetSha256: string;
  uses: RelatedUse[];
}

function object(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown> : null;
}

/** Read only allocated, non-presenter visual choices from a validated plan. */
export function selectedVisualUses(
  visual: Record<string, unknown>,
  planSha256: string,
): RelatedUse[] | null {
  const allocation = object(visual.allocation);
  const opportunities = Array.isArray(visual.opportunities) ? visual.opportunities : [];
  const decisions = Array.isArray(allocation?.decisions) ? allocation.decisions : [];
  if (allocation?.status !== "allocated" || !decisions.length || !opportunities.length) return null;
  const byId = new Map(opportunities.flatMap((raw) => {
    const row = object(raw);
    return row && typeof row.id === "string" ? [[row.id, row] as const] : [];
  }));
  const result: RelatedUse[] = [];
  for (const raw of decisions) {
    const decision = object(raw);
    const opportunity = typeof decision?.opportunityId === "string"
      ? byId.get(decision.opportunityId) : undefined;
    const candidates = Array.isArray(opportunity?.candidates) ? opportunity.candidates : [];
    const candidate = candidates.map(object).find((row) => row?.id === decision?.candidateId);
    const composition = object(candidate?.composition);
    if (!candidate || !composition || candidate.modality === "presenter" || candidate.modality === "omit") continue;
    const source = object(candidate.source), sourceRecordId = source?.recordId ?? null;
    const sourceSha256 = source?.sourceSha256 ?? source?.sha256 ?? null;
    const values = [candidate.id, candidate.modality, composition.familyId,
      composition.anatomy, composition.development];
    if (values.some((value) => typeof value !== "string" || !value)) return null;
    if ((sourceRecordId === null) !== (sourceSha256 === null)
        || (sourceRecordId !== null && (typeof sourceRecordId !== "string"
          || typeof sourceSha256 !== "string"))) return null;
    result.push({ candidateId: candidate.id as string, modality: candidate.modality as string,
      sourceRecordId: sourceRecordId as string | null, sourceSha256: sourceSha256 as string | null,
      familyId: composition.familyId as string,
      anatomy: composition.anatomy as string, development: composition.development as string,
      planSha256 });
  }
  return result;
}
