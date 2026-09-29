/** Bind reference-vocabulary choices to actual native scenes and catalog files. */
import { readFileSync } from "node:fs";
import path from "node:path";
import { exactKeys, enumValue, objectValue, sha256, stableId, stringValue, uniqueStrings } from "@/lib/producer/contracts/validation";
import { fileSha256 } from "./auto-edit-hash";
import type { NativeCatalogFile } from "./native-catalog-files";
import { assertNativeRelatedStyle, type NativeRelatedStyleComparison } from "./native-style-related";
import { nativeStyleExecutableSignatures } from "./native-style-executable-signature";

export interface NativeStyleChoice {
  choiceId: string; sceneIndex: number; viewerNeed: string; familyId: string; contenderRef: string;
  anatomy: string; configuration: string; development: string; catalogFiles: string[]; visibleIds: string[];
  consideredContenders: string[]; selectionReason: string;
  repeatMode: "new" | "varied" | "signature" | "callback" | "necessary-repeat";
  repeatReason: string;
}
export interface NativeSupplementalStyleChoice {
  choiceId: string; sceneIndex: number; viewerNeed: string; catalogId: string;
  anatomy: string; configuration: string; development: string; catalogFiles: string[]; visibleIds: string[];
  selectionReason: string; relationshipMode: "coherent" | "justified-exception";
  relationshipEvidence: string;
  repeatMode: "new" | "varied" | "signature" | "callback" | "necessary-repeat";
  repeatReason: string;
}

export interface NativeStyleApplication {
  schemaVersion: 1;
  vocabulary: { path: string; sha256: string; referenceId: string };
  choices: NativeStyleChoice[];
  supplementalChoices?: NativeSupplementalStyleChoice[];
  relatedContext?: { path: string; sha256: string; groupId: string; currentOutputId: string };
  relatedComparisons?: NativeRelatedStyleComparison[];
  limitations: string[];
}

interface ApplicationScene { viewingNeed: string; visibleIds: string[] }
interface ApplicationInput {
  application?: NativeStyleApplication;
  packet: Record<string, unknown>;
  requestPath: string;
  html: string;
  scenes: ApplicationScene[];
  catalogFiles?: NativeCatalogFile[];
}

function vocabularyFor(input: ApplicationInput) {
  const selected = input.packet.selectedReference;
  if (selected === null || selected === undefined) return null;
  const summary = objectValue(selected, "selected reference summary");
  if (summary.styleVocabularyAvailable !== true) return null;
  const file = path.join(path.dirname(input.requestPath), "SELECTED-REFERENCE-VOCABULARY.json");
  const text = readFileSync(file, "utf8"), value = objectValue(JSON.parse(text), "selected style vocabulary");
  const digest = fileSha256(file)!;
  const pins = input.packet.selectedReferences;
  if (!Array.isArray(pins) || !pins.some(value => objectValue(value, "selected reference pin").sha256 === digest)) {
    throw new Error("Selected style vocabulary is not pinned by the prepared request");
  }
  return { file, sha256: digest, value,
    referenceId: stringValue(value.referenceId, "style vocabulary reference id", 128) };
}

function vocabularyBinding(value: unknown, expected: ReturnType<typeof vocabularyFor>) {
  if (!expected) throw new Error("Style application has no prepared vocabulary");
  const row = objectValue(value, "style vocabulary binding");
  exactKeys(row, ["path", "sha256", "referenceId"], ["path", "sha256", "referenceId"], "style vocabulary binding");
  if (row.path !== expected.file || sha256(row.sha256, "style vocabulary hash") !== expected.sha256
      || row.referenceId !== expected.referenceId) throw new Error("Style application binds a different vocabulary");
  return { path: expected.file, sha256: expected.sha256, referenceId: expected.referenceId };
}

function boundedStrings(value: unknown, label: string, maximum: number, allowEmpty = false): string[] {
  const rows = uniqueStrings(value, label, (item, itemLabel) => stringValue(item, itemLabel, 2048));
  if ((!allowEmpty && !rows.length) || rows.length > maximum) throw new Error(`${label} has invalid count`);
  return rows;
}

function choice(value: unknown): NativeStyleChoice {
  const row = objectValue(value, "style choice");
  const fields = ["choiceId", "sceneIndex", "viewerNeed", "familyId", "contenderRef", "anatomy", "configuration", "development",
    "catalogFiles", "visibleIds", "consideredContenders", "selectionReason", "repeatMode", "repeatReason"];
  exactKeys(row, fields, fields, "style choice");
  if (!Number.isSafeInteger(row.sceneIndex) || (row.sceneIndex as number) < 0) throw new Error("Style choice sceneIndex is invalid");
  return { choiceId: stableId(row.choiceId, "style choice id"), sceneIndex: row.sceneIndex as number,
    viewerNeed: stringValue(row.viewerNeed, "style choice viewer need", 2400),
    familyId: stableId(row.familyId, "style choice family"),
    contenderRef: stringValue(row.contenderRef, "style choice contender", 256),
    anatomy: stringValue(row.anatomy, "style choice anatomy", 4000),
    configuration: stringValue(row.configuration, "style choice configuration", 4000),
    development: stringValue(row.development, "style choice development", 4000),
    catalogFiles: boundedStrings(row.catalogFiles, "style choice catalog files", 16),
    visibleIds: boundedStrings(row.visibleIds, "style choice visible ids", 64),
    consideredContenders: boundedStrings(row.consideredContenders, "considered contenders", 8),
    selectionReason: stringValue(row.selectionReason, "style choice reason", 4000),
    repeatMode: enumValue(row.repeatMode, ["new", "varied", "signature", "callback", "necessary-repeat"] as const,
      "style choice repeat mode"),
    repeatReason: stringValue(row.repeatReason, "style choice repeat reason", 4000) };
}

function supplementalChoice(value: unknown): NativeSupplementalStyleChoice {
  const row = objectValue(value, "supplemental style choice");
  const fields = ["choiceId", "sceneIndex", "viewerNeed", "catalogId", "anatomy", "configuration", "development",
    "catalogFiles", "visibleIds", "selectionReason", "relationshipMode", "relationshipEvidence", "repeatMode", "repeatReason"];
  exactKeys(row, fields, fields, "supplemental style choice");
  if (!Number.isSafeInteger(row.sceneIndex) || (row.sceneIndex as number) < 0) throw new Error("Supplemental style sceneIndex is invalid");
  return { choiceId: stableId(row.choiceId, "supplemental style choice id"), sceneIndex: row.sceneIndex as number,
    viewerNeed: stringValue(row.viewerNeed, "supplemental viewer need", 2400),
    catalogId: stableId(row.catalogId, "supplemental catalog id"),
    anatomy: stringValue(row.anatomy, "supplemental anatomy", 4000),
    configuration: stringValue(row.configuration, "supplemental configuration", 4000),
    development: stringValue(row.development, "supplemental development", 4000),
    catalogFiles: boundedStrings(row.catalogFiles, "supplemental catalog files", 16),
    visibleIds: boundedStrings(row.visibleIds, "supplemental visible ids", 64),
    selectionReason: stringValue(row.selectionReason, "supplemental selection reason", 4000),
    relationshipMode: enumValue(row.relationshipMode, ["coherent", "justified-exception"] as const,
      "supplemental relationship mode"),
    relationshipEvidence: stringValue(row.relationshipEvidence, "supplemental relationship evidence", 4000),
    repeatMode: enumValue(row.repeatMode, ["new", "varied", "signature", "callback", "necessary-repeat"] as const,
      "supplemental repeat mode"),
    repeatReason: stringValue(row.repeatReason, "supplemental repeat reason", 4000) };
}

function familyMap(vocabulary: Record<string, unknown>) {
  if (!Array.isArray(vocabulary.families)) throw new Error("Selected style vocabulary has no families");
  return new Map(vocabulary.families.map(value => {
    const family = objectValue(value, "style family"), id = stableId(family.id, "style family id");
    if (!Array.isArray(family.contenders)) throw new Error("Style family has no contenders");
    const refs = family.contenders.map(item => stringValue(objectValue(item, "style contender").catalogRef,
      "style contender ref", 256));
    return [id, refs] as const;
  }));
}

function catalogId(vocabulary: Record<string, unknown>, contenderRef: string): string {
  const candidates = objectValue(vocabulary.candidates, "style vocabulary candidates");
  const candidate = objectValue(candidates[contenderRef], "selected style candidate");
  const record = objectValue(candidate.record, "selected style candidate record");
  return stringValue(record.id, "selected catalog id", 128);
}

function contenderAvailability(vocabulary: Record<string, unknown>, familyId: string, contenderRef: string): string {
  if (!Array.isArray(vocabulary.families)) throw new Error("Selected style vocabulary has no families");
  for (const value of vocabulary.families) {
    const family = objectValue(value, "style family");
    if (family.id !== familyId || !Array.isArray(family.contenders)) continue;
    const contender = family.contenders.map(item => objectValue(item, "style contender"))
      .find(item => item.catalogRef === contenderRef);
    if (contender) return stringValue(contender.availability, "style contender availability", 32);
  }
  throw new Error("Style choice names an unknown family contender");
}

function mountedInScene(html: string, files: string[], visibleIds: string[]): boolean {
  const tags = html.match(/<[^>]{1,8192}>/gu) ?? [];
  return files.every(file => visibleIds.some(id => tags.some(tag =>
    tag.includes(`id="${id}"`) && tag.includes(`data-composition-src="${file}"`))));
}

function assertCatalogCoverage(input: ApplicationInput,
  rows: Array<NativeStyleChoice | NativeSupplementalStyleChoice>): void {
  for (const file of input.catalogFiles ?? []) {
    input.scenes.forEach((scene, sceneIndex) => {
      const mounted = scene.visibleIds.filter(id => mountedInScene(input.html, [file.file], [id]));
      const owners = rows.filter(row => row.sceneIndex === sceneIndex
        && row.catalogFiles.includes(file.file) && row.visibleIds.some(id => mounted.includes(id)));
      if (mounted.length && owners.length !== 1) {
        throw new Error("Style application must bind every mounted catalog treatment exactly once");
      }
    });
  }
}

function assertChoice(input: ApplicationInput, vocabulary: Record<string, unknown>, families: Map<string, string[]>, row: NativeStyleChoice) {
  const scene = input.scenes[row.sceneIndex];
  if (!scene || row.viewerNeed !== scene.viewingNeed) throw new Error("Style choice differs from its scene viewer need");
  if (row.visibleIds.some(id => !scene.visibleIds.includes(id))) throw new Error("Style choice names a visual outside its scene");
  const contenders = families.get(row.familyId);
  if (!contenders || !contenders.includes(row.contenderRef)
      || row.consideredContenders.some(ref => !contenders.includes(ref))
      || !row.consideredContenders.includes(row.contenderRef)
      || row.consideredContenders.length < Math.min(2, contenders.length)) {
    throw new Error("Style choice does not compare the selected family contenders");
  }
  const wanted = catalogId(vocabulary, row.contenderRef), files = input.catalogFiles ?? [];
  if (contenderAvailability(vocabulary, row.familyId, row.contenderRef) !== "ready") {
    throw new Error("Style choice selects a contender that is not ready");
  }
  if (!row.catalogFiles.every(file => files.some(item => item.file === file && item.catalogId === wanted))) {
    throw new Error("Style choice is not bound to its mounted catalog treatment");
  }
  if (!mountedInScene(input.html, row.catalogFiles, row.visibleIds)) {
    throw new Error("Style choice catalog treatment is not mounted on a scene-visible element");
  }
}

function assertSupplemental(input: ApplicationInput, row: NativeSupplementalStyleChoice): void {
  const scene = input.scenes[row.sceneIndex];
  if (!scene || row.viewerNeed !== scene.viewingNeed) throw new Error("Supplemental style choice differs from its scene viewer need");
  if (row.visibleIds.some(id => !scene.visibleIds.includes(id))) throw new Error("Supplemental style choice names a visual outside its scene");
  const files = input.catalogFiles ?? [];
  if (!row.catalogFiles.every(file => files.some(item => item.file === file && item.catalogId === row.catalogId))) {
    throw new Error("Supplemental style choice differs from its mounted catalog treatment");
  }
  if (!mountedInScene(input.html, row.catalogFiles, row.visibleIds)) {
    throw new Error("Supplemental catalog treatment is not mounted on a scene-visible element");
  }
}

function normalized(value: string): string { return value.trim().toLowerCase().replace(/\s+/gu, " "); }

function assertRepeats(rows: Array<{ row: NativeStyleChoice | NativeSupplementalStyleChoice;
  identity: string; signature: string }>,
  external = { identities: new Set<string>(), anatomies: new Set<string>(), signatures: new Set<string>() }): void {
  const seen = { identities: new Set(external.identities), anatomies: new Set(external.anatomies),
    signatures: new Set(external.signatures) };
  for (const { row, identity, signature } of [...rows].sort((a, b) => a.row.sceneIndex - b.row.sceneIndex)) {
    const anatomy = normalized(row.anatomy);
    const repeatedId = seen.identities.has(identity), repeatedAnatomy = seen.anatomies.has(anatomy);
    const repeatedSignature = seen.signatures.has(signature);
    const intentional = ["signature", "callback", "necessary-repeat"].includes(row.repeatMode);
    if ((repeatedSignature && !intentional) || (row.repeatMode === "new" && (repeatedId || repeatedAnatomy))
        || (intentional && !repeatedId && !repeatedAnatomy)
        || (row.repeatMode === "varied" && !repeatedId && !repeatedAnatomy)) {
      throw new Error("Style choice repeat mode differs from prior use in this plan");
    }
    seen.identities.add(identity); seen.anatomies.add(anatomy); seen.signatures.add(signature);
  }
}

/** Require a current application exactly when the prepared request carries a vocabulary. */
export function assertNativeStyleApplication(input: ApplicationInput): NativeStyleApplication | null {
  const expected = vocabularyFor(input);
  if (!expected) {
    if (input.application) throw new Error("Style application cannot claim an absent prepared vocabulary");
    return null;
  }
  if (!input.application) throw new Error("Vocabulary-enabled request requires a style application");
  const value = objectValue(input.application, "style application");
  const required = ["schemaVersion", "vocabulary", "choices", "limitations"];
  exactKeys(value, [...required, "supplementalChoices", "relatedContext", "relatedComparisons"], required, "style application");
  if (value.schemaVersion !== 1 || !Array.isArray(value.choices)
      || (value.supplementalChoices !== undefined && !Array.isArray(value.supplementalChoices))) {
    throw new Error("Style application envelope is invalid");
  }
  const binding = vocabularyBinding(value.vocabulary, expected);
  const choices = value.choices.map(choice);
  const supplemental = (value.supplementalChoices ?? []).map(supplementalChoice);
  const all = [...choices, ...supplemental];
  if (all.length > 64 || new Set(all.map(row => row.choiceId)).size !== all.length) {
    throw new Error("Style application has too many choices or duplicates a choice id");
  }
  const families = familyMap(expected.value);
  for (const row of choices) assertChoice(input, expected.value, families, row);
  for (const row of supplemental) assertSupplemental(input, row);
  assertCatalogCoverage(input, all);
  const signatures = nativeStyleExecutableSignatures(all, input.catalogFiles ?? [], input.html);
  const related = assertNativeRelatedStyle({ packet: input.packet, requestPath: input.requestPath,
    vocabulary: expected.value, referenceId: expected.referenceId, vocabularySha256: expected.sha256!, choices: all,
    executableSignatures: signatures,
    context: value.relatedContext, comparisons: value.relatedComparisons });
  const candidates = objectValue(expected.value.candidates, "style candidates");
  const rows: Array<{ row: NativeStyleChoice | NativeSupplementalStyleChoice;
    identity: string; signature: string }> = [
    ...choices.map(row => ({ row, identity: stringValue(objectValue(
      objectValue(candidates[row.contenderRef], "style candidate").record, "style candidate record").id,
    "style candidate id", 128), signature: signatures[row.choiceId] })),
    ...supplemental.map(row => ({ row, identity: row.catalogId, signature: signatures[row.choiceId] })),
  ];
  assertRepeats(rows, related.external);
  return { schemaVersion: 1, vocabulary: binding, choices,
    ...(supplemental.length ? { supplementalChoices: supplemental } : {}),
    ...(related.relatedContext ? { relatedContext: related.relatedContext } : {}),
    ...(related.relatedComparisons ? { relatedComparisons: related.relatedComparisons } : {}),
    limitations: boundedStrings(value.limitations, "style application limitations", 64, true) };
}
