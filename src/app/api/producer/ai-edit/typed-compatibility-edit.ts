import type { EditPlan, GraphicEntry } from "@/lib/producer/edit-plan";
import { canonicalJson, canonicalJsonSha256 } from "@/lib/server/auto-edit-hash";
import {
  compileSetGraphicTextV1,
  type SetGraphicTextV1,
} from "@/lib/producer/set-graphic-text-v1";
import { GRAPHIC_ID_RE } from "@/lib/producer/graphic-ids";

export interface TypedCompatibilityEdit {
  adapterVersion: 1;
  kind: "set-graphic-text";
  operation: SetGraphicTextV1;
  operationHash: string;
}

function text(entry: GraphicEntry | undefined): unknown {
  const spec = entry?.spec;
  if (!spec || typeof spec !== "object" || Array.isArray(spec)) return undefined;
  return (spec as Record<string, unknown>).text;
}

function requestsStatementTextChange(
  parent: EditPlan,
  candidate: EditPlan,
): boolean {
  const before = parent.graphicsTrack;
  const after = candidate.graphicsTrack;
  if (!Array.isArray(before) || !Array.isArray(after)) return false;
  const counts = (track: GraphicEntry[]) => {
    const result = new Map<string, number>();
    for (const entry of track) {
      if (typeof entry.id === "string") {
        result.set(entry.id, (result.get(entry.id) ?? 0) + 1);
      }
    }
    return result;
  };
  const beforeCounts = counts(before);
  const afterCounts = counts(after);
  const hasUnaddressableStatement = before.some((entry) =>
    entry.kind === "statement-card"
      && (typeof entry.id !== "string" || !GRAPHIC_ID_RE.test(entry.id)
        || beforeCounts.get(entry.id) !== 1));
  if (hasUnaddressableStatement
      && canonicalJson(before) !== canonicalJson(after)) return true;
  const afterById = new Map(
    after
      .filter((entry) => typeof entry.id === "string")
      .map((entry) => [entry.id as string, entry]),
  );
  return before.some((entry, index) => {
    if (entry.kind !== "statement-card") return false;
    const stable = typeof entry.id === "string" && GRAPHIC_ID_RE.test(entry.id)
      && beforeCounts.get(entry.id) === 1 && afterCounts.get(entry.id) === 1;
    const compared = stable
      ? afterById.get(entry.id as string) : after[index];
    return text(entry) !== text(compared);
  });
}

/**
 * Select the one released typed adapter by deterministic candidate shape.
 * Once selected, any adjacent change rejects; it never falls back to an open
 * graphics mutation after touching statement-card text.
 */
export function compileTypedCompatibilityEdit(
  parent: EditPlan,
  candidate: EditPlan,
): TypedCompatibilityEdit | null {
  if (!requestsStatementTextChange(parent, candidate)) return null;
  const operation = compileSetGraphicTextV1(parent, candidate);
  return {
    adapterVersion: 1,
    kind: "set-graphic-text",
    operation,
    operationHash: canonicalJsonSha256(operation),
  };
}
