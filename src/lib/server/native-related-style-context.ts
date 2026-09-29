/** Frozen semantic style allocations for explicitly related native Shorts. */
import path from "node:path";
import { observeCutPreviewFile } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { nativeStyleExecutableSignatures } from "./native-style-executable-signature";
import { exactKeys, enumValue, objectValue, sha256, stableId, stringValue } from "@/lib/producer/contracts/validation";

interface RelatedStyleChoiceBase {
  choiceId: string; sceneIndex: number; familyId: string; contenderRef: string;
  anatomy: string; configuration: string; development: string;
}
export interface RelatedVocabularyStyleChoice extends RelatedStyleChoiceBase {
  choiceKind: "vocabulary"; familyId: string; contenderRef: string;
}
export interface RelatedSupplementalStyleChoice {
  choiceKind: "supplemental"; choiceId: string; sceneIndex: number; catalogId: string;
  anatomy: string; configuration: string; development: string;
}
export type RelatedStyleChoice = RelatedVocabularyStyleChoice | RelatedSupplementalStyleChoice;
export interface RelatedStyleOutput {
  outputId: string; status: "planned" | "authored";
  application?: { path: string; sha256: string };
  choices: RelatedStyleChoice[];
}
export interface NativeRelatedStyleContext {
  schemaVersion: 1; scope: "related-native-short-style-context";
  groupId: string; currentOutputId: string; referenceId: string; vocabularySha256: string;
  planningMode: "shared-allocation" | "serialized";
  groupAllocation?: { path: string; sha256: string };
  outputs: RelatedStyleOutput[]; limitations: string[];
}
export interface RelatedStyleSnapshot {
  record: NativeRelatedStyleContext; source: { path: string; sha256: string };
  executableSignatures: Map<string, Map<string, string>>;
}

const MAX_JSON_BYTES = 16 * 1024 * 1024;
const MAX_HTML_BYTES = 16 * 1024 * 1024;
interface FilePin { path: string; sha256: string }

function observedFile(file: string, label: string, maximum: number) {
  if (!path.isAbsolute(file) || path.resolve(file) !== file) {
    throw new Error(`${label} must be a canonical absolute file`);
  }
  const observed = observeCutPreviewFile(file, maximum, true);
  return { ...observed, text: new TextDecoder("utf-8", { fatal: true }).decode(observed.bytes) };
}

function pinnedFile(binding: FilePin, label: string, maximum: number) {
  const observed = observedFile(binding.path, label, maximum);
  if (observed.sha256 !== binding.sha256) throw new Error(`${label} changed`);
  return observed;
}

function pinnedJson(binding: FilePin, label: string) {
  return objectValue(JSON.parse(pinnedFile(binding, label, MAX_JSON_BYTES).text), label);
}

function strings(value: unknown, label: string, maximum: number, empty = false): string[] {
  if (!Array.isArray(value) || (!empty && !value.length) || value.length > maximum) {
    throw new Error(`${label} has invalid count`);
  }
  const result = value.map(item => stringValue(item, label, 4000));
  if (new Set(result).size !== result.length) throw new Error(`${label} contains duplicates`);
  return result;
}

export function parseRelatedStyleChoice(value: unknown): RelatedStyleChoice {
  const row = objectValue(value, "related style choice");
  const kind = enumValue(row.choiceKind, ["vocabulary", "supplemental"] as const, "related style choice kind");
  const common = ["choiceKind", "choiceId", "sceneIndex", "anatomy", "configuration", "development"];
  const fields = kind === "vocabulary" ? [...common, "familyId", "contenderRef"] : [...common, "catalogId"];
  exactKeys(row, fields, fields, "related style choice");
  if (!Number.isSafeInteger(row.sceneIndex) || (row.sceneIndex as number) < 0) {
    throw new Error("Related style choice scene index is invalid");
  }
  const base = { choiceKind: kind, choiceId: stableId(row.choiceId, "related style choice"),
    sceneIndex: row.sceneIndex as number, anatomy: stringValue(row.anatomy, "related style anatomy", 4000),
    configuration: stringValue(row.configuration, "related style configuration", 4000),
    development: stringValue(row.development, "related style development", 4000) };
  return kind === "vocabulary" ? { ...base, choiceKind: kind,
    familyId: stableId(row.familyId, "related style family"),
    contenderRef: stringValue(row.contenderRef, "related style contender", 256) }
    : { ...base, choiceKind: kind, catalogId: stableId(row.catalogId, "related style catalog id") };
}

function applicationBinding(value: unknown) {
  const row = objectValue(value, "related style application pin");
  exactKeys(row, ["path", "sha256"], ["path", "sha256"], "related style application pin");
  const file = stringValue(row.path, "related style application path", 4096);
  const expected = sha256(row.sha256, "related style application hash");
  pinnedFile({ path: file, sha256: expected }, "related style application", MAX_JSON_BYTES);
  return { path: file, sha256: expected };
}

function applicationChoices(binding: { path: string; sha256: string }): RelatedStyleChoice[] {
  const application = pinnedJson(binding, "related style application");
  if (application.schemaVersion !== 1 || !Array.isArray(application.choices)) {
    throw new Error("Related authored application is invalid");
  }
  const vocabulary = application.choices.map(value => {
    const row = objectValue(value, "related authored choice");
    return parseRelatedStyleChoice({ choiceKind: "vocabulary", choiceId: row.choiceId, sceneIndex: row.sceneIndex,
      familyId: row.familyId, contenderRef: row.contenderRef,
      anatomy: row.anatomy, configuration: row.configuration, development: row.development });
  });
  const supplemental = Array.isArray(application.supplementalChoices)
    ? application.supplementalChoices.map(value => {
      const row = objectValue(value, "related authored supplemental choice");
      return parseRelatedStyleChoice({ choiceKind: "supplemental", choiceId: row.choiceId, sceneIndex: row.sceneIndex,
        catalogId: row.catalogId, anatomy: row.anatomy,
        configuration: row.configuration, development: row.development });
    }) : [];
  return [...vocabulary, ...supplemental];
}

function output(value: unknown, mode: NativeRelatedStyleContext["planningMode"]): RelatedStyleOutput {
  const row = objectValue(value, "related style output");
  const required = ["outputId", "status", "choices"];
  exactKeys(row, [...required, "application"], required, "related style output");
  const status = enumValue(row.status, ["planned", "authored"] as const, "related style output status");
  const choices = Array.isArray(row.choices) ? row.choices.map(parseRelatedStyleChoice) : [];
  if (!choices.length || choices.length > 64 || new Set(choices.map(item => item.choiceId)).size !== choices.length) {
    throw new Error("Related style output has invalid choices");
  }
  if (status === "planned") {
    if (mode !== "shared-allocation" || row.application !== undefined) {
      throw new Error("Only shared allocation may contain unbound planned outputs");
    }
    return { outputId: stableId(row.outputId, "related output id"), status, choices };
  }
  const application = applicationBinding(row.application);
  if (canonicalJsonSha256(applicationChoices(application)) !== canonicalJsonSha256(choices)) {
    throw new Error("Related output summary differs from its authored application");
  }
  return { outputId: stableId(row.outputId, "related output id"), status, application, choices };
}

function filePin(value: unknown, label: string) {
  const row = objectValue(value, label);
  exactKeys(row, ["path", "sha256"], ["path", "sha256"], label);
  const file = stringValue(row.path, `${label} path`, 4096);
  const digest = sha256(row.sha256, `${label} hash`);
  pinnedFile({ path: file, sha256: digest }, label, MAX_JSON_BYTES);
  return { path: file, sha256: digest };
}

function receiptSignatures(value: unknown, authored: RelatedStyleOutput): Map<string, string> {
  const row = objectValue(value, "related executable usage receipt");
  const fields = ["outputId", "project", "application", "signatures"];
  exactKeys(row, fields, fields, "related executable usage receipt");
  if (row.outputId !== authored.outputId) throw new Error("Related executable receipt output differs");
  const project = filePin(row.project, "related executable project");
  const application = filePin(row.application, "related executable application");
  if (canonicalJsonSha256(application) !== canonicalJsonSha256(authored.application)) {
    throw new Error("Related executable receipt binds a different application");
  }
  const plan = pinnedJson(project, "related executable project");
  const strategy = objectValue(plan.strategy, "related executable strategy");
  const actual = objectValue(strategy.styleApplication, "related executable style application");
  if (canonicalJsonSha256(actual) !== canonicalJsonSha256(pinnedJson(application, "related executable application"))) {
    throw new Error("Related executable project differs from its style application");
  }
  const choices = [...(actual.choices as object[]), ...((actual.supplementalChoices as object[] | undefined) ?? [])]
    .map(item => objectValue(item, "related executable choice"));
  const files = Array.isArray(plan.catalogFiles) ? plan.catalogFiles : [];
  const projectRoot = path.dirname(project.path);
  for (const binding of files.map(item => objectValue(item, "related catalog binding"))) {
    const file = stringValue(binding.file, "related staged catalog file", 256);
    if (!/^compositions\/[a-z0-9][a-z0-9-]*\.html$/u.test(file)) {
      throw new Error("Related executable catalog bytes changed");
    }
    const expected = sha256(binding.sha256, "related staged catalog hash");
    pinnedFile({ path: path.join(projectRoot, file), sha256: expected },
      "related staged catalog file", MAX_HTML_BYTES);
  }
  const index = observedFile(path.join(projectRoot, "index.html"), "related executable index", MAX_HTML_BYTES);
  const derived = nativeStyleExecutableSignatures(choices as never, files as never,
    index.text);
  if (!Array.isArray(row.signatures)) throw new Error("Related executable signatures are invalid");
  const declared = new Map(row.signatures.map(item => {
    const entry = objectValue(item, "related executable signature");
    exactKeys(entry, ["choiceId", "sha256"], ["choiceId", "sha256"], "related executable signature");
    return [stableId(entry.choiceId, "related executable choice id"),
      sha256(entry.sha256, "related executable signature hash")];
  }));
  if (declared.size !== choices.length || canonicalJsonSha256(Object.fromEntries(declared))
      !== canonicalJsonSha256(derived)) throw new Error("Related executable signatures changed");
  return declared;
}

function groupAllocation(value: unknown, expected: Omit<NativeRelatedStyleContext, "groupAllocation">) {
  if (value === undefined) return new Map<string, Map<string, string>>();
  const pin = filePin(value, "related group allocation");
  const raw = pinnedJson(pin, "related group allocation");
  const fields = ["schemaVersion", "scope", "groupId", "referenceId", "vocabularySha256",
    "planningMode", "outputs", "limitations", "usageReceipts"];
  exactKeys(raw, fields, fields, "related group allocation");
  if (raw.schemaVersion !== 1 || raw.scope !== "native-short-related-group-allocation"
      || !Array.isArray(raw.outputs) || !Array.isArray(raw.usageReceipts)) {
    throw new Error("Related group allocation envelope is invalid");
  }
  const base = { groupId: raw.groupId, referenceId: raw.referenceId,
    vocabularySha256: raw.vocabularySha256, planningMode: raw.planningMode,
    outputs: raw.outputs, limitations: raw.limitations };
  const wanted = { groupId: expected.groupId, referenceId: expected.referenceId,
    vocabularySha256: expected.vocabularySha256, planningMode: expected.planningMode,
    outputs: expected.outputs, limitations: expected.limitations };
  if (canonicalJsonSha256(base) !== canonicalJsonSha256(wanted)) {
    throw new Error("Related context differs from its shared group allocation");
  }
  const authored = new Map(expected.outputs.filter(row => row.status === "authored")
    .map(row => [row.outputId, row]));
  const signatures = new Map<string, Map<string, string>>();
  for (const receipt of raw.usageReceipts) {
    const row = objectValue(receipt, "related executable usage receipt");
    const prior = authored.get(String(row.outputId));
    if (!prior || signatures.has(prior.outputId)) throw new Error("Related executable receipt is duplicate or unowned");
    signatures.set(prior.outputId, receiptSignatures(receipt, prior));
  }
  if (signatures.size !== authored.size) throw new Error("Related group omits an authored executable receipt");
  return signatures;
}

/** Read a bounded immutable sibling allocation; it remains planning evidence only. */
export function loadNativeRelatedStyleContext(file: string): RelatedStyleSnapshot {
  const observed = observedFile(file, "related style context", MAX_JSON_BYTES);
  const source = { path: file, sha256: observed.sha256 };
  const raw = objectValue(JSON.parse(observed.text), "related style context");
  const fields = ["schemaVersion", "scope", "groupId", "currentOutputId", "referenceId", "vocabularySha256",
    "planningMode", "outputs", "limitations"];
  exactKeys(raw, [...fields, "groupAllocation"], fields, "related style context");
  const planningMode = enumValue(raw.planningMode, ["shared-allocation", "serialized"] as const,
    "related style planning mode");
  if (raw.schemaVersion !== 1 || raw.scope !== "related-native-short-style-context"
      || !Array.isArray(raw.outputs) || raw.outputs.length < 1 || raw.outputs.length > 32) {
    throw new Error("Related style context envelope is invalid");
  }
  const outputs = raw.outputs.map(value => output(value, planningMode));
  if (outputs.reduce((sum, row) => sum + row.choices.length, 0) > 256) {
    throw new Error("Related style choice inventory exceeds its bound");
  }
  const groupId = stableId(raw.groupId, "related style group"), currentOutputId = stableId(raw.currentOutputId,
    "current related output"), referenceId = stableId(raw.referenceId, "related style reference");
  const vocabularySha256 = sha256(raw.vocabularySha256, "related style vocabulary hash");
  if (new Set(outputs.map(row => row.outputId)).size !== outputs.length
      || new Set(outputs.flatMap(row => row.application?.path ?? [])).size
      !== outputs.filter(row => row.application).length) throw new Error("Related style outputs contain duplicate identities");
  const current = outputs.filter(row => row.outputId === currentOutputId);
  if ((planningMode === "shared-allocation" && (current.length !== 1 || current[0].status !== "planned"))
      || (planningMode === "serialized" && current.length !== 0)
      || (planningMode === "shared-allocation" && outputs.length < 2)) {
    throw new Error("Related style current output conflicts with its planning mode");
  }
  for (const row of outputs.filter(row => row.status === "authored")) {
    const authored = pinnedJson(row.application!, "related style application");
    const vocabulary = objectValue(authored.vocabulary, "prior style vocabulary binding");
    if (vocabulary.referenceId !== referenceId || vocabulary.sha256 !== vocabularySha256) {
      throw new Error("Related application uses a different reference vocabulary");
    }
    const related = authored.relatedContext;
    if (related !== undefined && objectValue(related, "prior related context").currentOutputId !== row.outputId) {
      throw new Error("Related application belongs to a different output or circular allocation");
    }
  }
  const limitations = strings(raw.limitations, "related style limitations", 64, true);
  const base = { schemaVersion: 1 as const, scope: "related-native-short-style-context" as const,
    groupId, currentOutputId, referenceId, vocabularySha256, planningMode, outputs, limitations };
  const executableSignatures = groupAllocation(raw.groupAllocation, base);
  return { source, record: { ...base, ...(raw.groupAllocation
    ? { groupAllocation: filePin(raw.groupAllocation, "related group allocation") } : {}) }, executableSignatures };
}
