/** Validate frozen related-Short allocations and semantic variation evidence. */
import path from "node:path";
import { canonicalJsonSha256, fileSha256 } from "./auto-edit-hash";
import { loadNativeRelatedStyleContext, type RelatedStyleChoice,
  type RelatedStyleSnapshot } from "./native-related-style-context";
import type { NativeStyleChoice, NativeSupplementalStyleChoice } from "./native-style-application";
import { exactKeys, enumValue, objectValue, sha256, stableId, stringValue } from "@/lib/producer/contracts/validation";

export interface NativeRelatedStyleComparison {
  currentChoiceId: string; outputId: string; siblingChoiceId: string;
  relationship: "varied" | "different-purpose" | "signature" | "callback" | "necessary-repeat";
  compositionDifference: string; developmentDifference: string; reason: string;
}

interface RelatedInput {
  packet: Record<string, unknown>; requestPath: string; vocabulary: Record<string, unknown>;
  referenceId: string; vocabularySha256: string;
  choices: Array<NativeStyleChoice | NativeSupplementalStyleChoice>;
  executableSignatures: Record<string, string>;
  context: unknown; comparisons: unknown;
}

function relatedFor(input: RelatedInput) {
  const summary = input.packet.relatedStyleContext;
  if (summary === null || summary === undefined) return null;
  const expected = objectValue(summary, "related style context summary");
  const file = path.join(path.dirname(input.requestPath), "RELATED-STYLE-CONTEXT.json");
  const snapshot = loadNativeRelatedStyleContext(file);
  const source = objectValue(expected.source, "related style context source");
  const original = loadNativeRelatedStyleContext(stringValue(source.path, "related style source path", 4096));
  if (original.source.sha256 !== sha256(source.sha256, "related style source hash")
      || canonicalJsonSha256(original.record) !== canonicalJsonSha256(snapshot.record)) {
    throw new Error("Prepared related style context differs from its frozen source");
  }
  if (snapshot.record.groupId !== expected.groupId || snapshot.record.currentOutputId !== expected.currentOutputId
      || snapshot.record.referenceId !== expected.referenceId
      || snapshot.record.vocabularySha256 !== expected.vocabularySha256
      || snapshot.record.planningMode !== expected.planningMode) throw new Error("Related style context differs from its request");
  return { file, sha256: fileSha256(file)!, snapshot };
}

function relatedBinding(value: unknown, expected: NonNullable<ReturnType<typeof relatedFor>>) {
  const row = objectValue(value, "related style context binding");
  const fields = ["path", "sha256", "groupId", "currentOutputId"];
  exactKeys(row, fields, fields, "related style context binding");
  if (row.path !== expected.file || sha256(row.sha256, "related style context hash") !== expected.sha256
      || row.groupId !== expected.snapshot.record.groupId
      || row.currentOutputId !== expected.snapshot.record.currentOutputId) {
    throw new Error("Style application binds a different related context");
  }
  return { path: expected.file, sha256: expected.sha256, groupId: expected.snapshot.record.groupId,
    currentOutputId: expected.snapshot.record.currentOutputId };
}

function comparison(value: unknown): NativeRelatedStyleComparison {
  const row = objectValue(value, "related style comparison");
  const fields = ["currentChoiceId", "outputId", "siblingChoiceId", "relationship",
    "compositionDifference", "developmentDifference", "reason"];
  exactKeys(row, fields, fields, "related style comparison");
  return { currentChoiceId: stableId(row.currentChoiceId, "current related style choice"),
    outputId: stableId(row.outputId, "related comparison output"),
    siblingChoiceId: stableId(row.siblingChoiceId, "sibling related style choice"),
    relationship: enumValue(row.relationship,
      ["varied", "different-purpose", "signature", "callback", "necessary-repeat"] as const,
      "related style relationship"),
    compositionDifference: stringValue(row.compositionDifference, "related composition difference", 4000),
    developmentDifference: stringValue(row.developmentDifference, "related development difference", 4000),
    reason: stringValue(row.reason, "related style comparison reason", 4000) };
}

function identity(row: RelatedStyleChoice | NativeStyleChoice | NativeSupplementalStyleChoice): string {
  if ("choiceKind" in row) return row.choiceKind === "vocabulary" ? row.contenderRef : row.catalogId;
  return "contenderRef" in row ? row.contenderRef : row.catalogId;
}

function applicable(left: NativeStyleChoice | NativeSupplementalStyleChoice, right: RelatedStyleChoice): boolean {
  const sameFamily = "familyId" in left && right.choiceKind === "vocabulary" && left.familyId === right.familyId;
  return sameFamily || identity(left) === identity(right) || left.anatomy === right.anatomy;
}

function relatedPairs(snapshot: RelatedStyleSnapshot,
  choices: Array<NativeStyleChoice | NativeSupplementalStyleChoice>) {
  const current = snapshot.record.currentOutputId;
  return choices.flatMap(choice => snapshot.record.outputs
    .filter(output => output.outputId !== current)
    .flatMap(output => output.choices.filter(sibling => applicable(choice, sibling))
      .map(sibling => ({ choice, outputId: output.outputId, sibling }))));
}

function summarized(row: NativeStyleChoice | NativeSupplementalStyleChoice): RelatedStyleChoice {
  const common = { choiceId: row.choiceId, sceneIndex: row.sceneIndex, anatomy: row.anatomy,
    configuration: row.configuration, development: row.development };
  return "familyId" in row ? { ...common, choiceKind: "vocabulary", familyId: row.familyId,
    contenderRef: row.contenderRef } : { ...common, choiceKind: "supplemental", catalogId: row.catalogId };
}

function assertAllocation(snapshot: RelatedStyleSnapshot,
  choices: Array<NativeStyleChoice | NativeSupplementalStyleChoice>): void {
  if (snapshot.record.planningMode !== "shared-allocation") return;
  const planned = snapshot.record.outputs.find(row => row.outputId === snapshot.record.currentOutputId)!;
  const actual: RelatedStyleChoice[] = choices.map(summarized);
  if (canonicalJsonSha256(actual) !== canonicalJsonSha256(planned.choices)) {
    throw new Error("Style application differs from the shared group allocation");
  }
}

function assertComparisons(snapshot: RelatedStyleSnapshot,
  choices: Array<NativeStyleChoice | NativeSupplementalStyleChoice>, values: unknown,
  currentSignatures: Record<string, string>) {
  if (!Array.isArray(values) || values.length > 4096) throw new Error("Related style comparisons are invalid");
  const comparisons = values.map(comparison), pairs = relatedPairs(snapshot, choices);
  const key = (current: string, output: string, sibling: string) => `${current}\0${output}\0${sibling}`;
  const expected = new Map(pairs.map(pair => [key(pair.choice.choiceId, pair.outputId, pair.sibling.choiceId), pair]));
  if (new Set(comparisons.map(row => key(row.currentChoiceId, row.outputId, row.siblingChoiceId))).size
      !== comparisons.length || comparisons.length !== expected.size) throw new Error("Related style comparisons omit or duplicate applicable siblings");
  for (const row of comparisons) {
    const pair = expected.get(key(row.currentChoiceId, row.outputId, row.siblingChoiceId));
    if (!pair) throw new Error("Related style comparison names an inapplicable sibling");
    const identical = pair.choice.anatomy === pair.sibling.anatomy
      && pair.choice.configuration === pair.sibling.configuration
      && pair.choice.development === pair.sibling.development;
    const executableIdentical = snapshot.executableSignatures.get(pair.outputId)?.get(pair.sibling.choiceId)
      === currentSignatures[pair.choice.choiceId];
    const repeat = ["signature", "callback", "necessary-repeat"].includes(row.relationship);
    if ((identity(pair.choice) === identity(pair.sibling)
        || pair.choice.anatomy === pair.sibling.anatomy) && pair.choice.repeatMode === "new") {
      throw new Error("Related output reuses a contender or composition anatomy without an intentional repeat mode");
    }
    if ((identical || executableIdentical) && (!repeat || pair.choice.repeatMode !== row.relationship)) {
      throw new Error("Identical related treatment needs an explicit matching signature or callback decision");
    }
  }
  return comparisons;
}

function assertVocabulary(snapshot: RelatedStyleSnapshot, vocabulary: Record<string, unknown>): void {
  if (!Array.isArray(vocabulary.families)) throw new Error("Selected style vocabulary has no families");
  const families = new Map(vocabulary.families.map(value => {
    const family = objectValue(value, "style family"), id = stableId(family.id, "style family id");
    if (!Array.isArray(family.contenders)) throw new Error("Style family has no contenders");
    return [id, new Map(family.contenders.map(item => {
      const contender = objectValue(item, "style contender");
      return [stringValue(contender.catalogRef, "style contender ref", 256), contender.availability];
    }))] as const;
  }));
  const candidates = objectValue(vocabulary.candidates, "style vocabulary candidates");
  for (const row of snapshot.record.outputs.flatMap(output => output.choices)
    .filter(row => row.choiceKind === "vocabulary")) {
    const availability = families.get(row.familyId)?.get(row.contenderRef);
    if (availability === undefined || !candidates[row.contenderRef]) {
      throw new Error("Related style allocation names an unknown family contender");
    }
    if (availability !== "ready") throw new Error("Related style allocation selects a contender that is not ready");
  }
}

/** Validate an optional related context and return its exact application fields. */
export function assertNativeRelatedStyle(input: RelatedInput) {
  const related = relatedFor(input);
  if (!related) {
    if (input.context !== undefined || input.comparisons !== undefined) {
      throw new Error("Style application claims an absent related context");
    }
    return { external: { identities: new Set<string>(), anatomies: new Set<string>(), signatures: new Set<string>() } };
  }
  if (related.snapshot.record.referenceId !== input.referenceId
      || related.snapshot.record.vocabularySha256 !== input.vocabularySha256) {
    throw new Error("Related style context belongs to a different vocabulary");
  }
  if (input.context === undefined || input.comparisons === undefined) {
    throw new Error("Related style context requires application comparisons");
  }
  assertVocabulary(related.snapshot, input.vocabulary);
  assertAllocation(related.snapshot, input.choices);
  return { relatedContext: relatedBinding(input.context, related),
    relatedComparisons: assertComparisons(related.snapshot, input.choices, input.comparisons,
      input.executableSignatures),
    external: { identities: new Set(related.snapshot.record.outputs.filter(output =>
      output.outputId !== related.snapshot.record.currentOutputId).flatMap(output => output.choices.map(identity))),
      anatomies: new Set(related.snapshot.record.outputs.filter(output =>
        output.outputId !== related.snapshot.record.currentOutputId).flatMap(output => output.choices.map(row =>
        row.anatomy.trim().toLowerCase().replace(/\s+/gu, " ")))),
      signatures: new Set(related.snapshot.record.outputs.filter(output =>
        output.outputId !== related.snapshot.record.currentOutputId).flatMap(output => output.choices.map(row =>
        related.snapshot.executableSignatures.get(output.outputId)?.get(row.choiceId)
          ?? [row.anatomy, row.configuration, row.development]
            .map(value => value.trim().toLowerCase().replace(/\s+/gu, " ")).join("\0")))) } };
}
