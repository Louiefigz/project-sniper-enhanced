/** One controller-owned allocation shared by two to four related native Shorts. */
import { createHash } from "node:crypto";
import { existsSync, lstatSync, mkdirSync, realpathSync, writeFileSync } from "node:fs";
import path from "node:path";
import { observeCutPreviewFile } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { storedAutoEditIntent } from "@/app/api/producer/auto-edit/operator-intent-authority";
import { resolveReferenceContext } from "@/app/api/producer/auto-edit/saved-plan-request";
import { parseAutoEditIntent } from "@/app/api/producer/auto-edit/stream";
import { canonicalProducerDir, workspaceRoot } from "@/app/api/_lib/workspace";
import { exactKeys, objectValue, sha256, stableId, stringValue } from "@/lib/producer/contracts/validation";
import { canonicalJson, canonicalJsonSha256 } from "./auto-edit-hash";
import { nativeReferenceInputs } from "./longform-reference-inputs";
import { parseRelatedStyleChoice, type RelatedStyleChoice, type RelatedStyleOutput } from "./native-related-style-context";
import { prepareNativeShortRequest } from "./native-short-request";
import { readNativeShortProject } from "./native-short-project";
import { nativeStyleExecutableSignatures } from "./native-style-executable-signature";

interface GroupTarget { outputId: string; producerDir: string; choices: RelatedStyleChoice[] }
interface GroupDraft {
  groupId: string; referenceId: string; vocabularySha256: string;
  outputs: GroupTarget[]; completed: Array<{ outputId: string; projectDir: string }>;
  limitations: string[];
}
interface GroupServices {
  selectedVocabulary(target: GroupTarget, draft: GroupDraft): unknown;
  prepareRequest(input: Parameters<typeof prepareNativeShortRequest>[0]): ReturnType<typeof prepareNativeShortRequest>;
  completedOutput(row: GroupDraft["completed"][number], draft: GroupDraft): ReturnType<typeof completedOutput>;
}
interface CompletedManifest { sha256: string; projectHash: string; files: Map<string, string> }
const MAX_JSON_BYTES = 16 * 1024 * 1024;
const MAX_HTML_BYTES = 16 * 1024 * 1024;

function observedText(file: string, maximum: number): ReturnType<typeof observeCutPreviewFile> & { text: string } {
  const observed = observeCutPreviewFile(file, maximum, true);
  return { ...observed, text: new TextDecoder("utf-8", { fatal: true }).decode(observed.bytes) };
}

function observedJson(file: string, label: string, maximum = MAX_JSON_BYTES) {
  const observed = observedText(file, maximum);
  return { ...observed, value: objectValue(JSON.parse(observed.text), label) };
}

function strings(value: unknown, label: string, maximum: number): string[] {
  if (!Array.isArray(value) || value.length > maximum) throw new Error(`${label} is invalid`);
  const rows = value.map(item => stringValue(item, label, 4000));
  if (new Set(rows).size !== rows.length) throw new Error(`${label} contains duplicates`);
  return rows;
}

function canonicalDirectory(value: unknown, label: string): string {
  const directory = stringValue(value, label, 4096);
  if (!path.isAbsolute(directory) || realpathSync(directory) !== directory
      || !lstatSync(directory).isDirectory()) throw new Error(`${label} must be a canonical directory`);
  return directory;
}

function target(value: unknown): GroupTarget {
  const row = objectValue(value, "related group target");
  const fields = ["outputId", "producerDir", "choices"];
  exactKeys(row, fields, fields, "related group target");
  const choices = Array.isArray(row.choices) ? row.choices.map(parseRelatedStyleChoice) : [];
  if (!choices.length || choices.length > 64
      || new Set(choices.map(choice => choice.choiceId)).size !== choices.length) {
    throw new Error("Related group target choices are invalid");
  }
  return { outputId: stableId(row.outputId, "related output id"),
    producerDir: canonicalDirectory(row.producerDir, "related producer directory"), choices };
}

function completed(value: unknown) {
  const row = objectValue(value, "completed related output");
  exactKeys(row, ["outputId", "projectDir"], ["outputId", "projectDir"], "completed related output");
  return { outputId: stableId(row.outputId, "completed related output id"),
    projectDir: canonicalDirectory(row.projectDir, "completed related project") };
}

function readDraft(file: string): GroupDraft {
  const absolute = path.resolve(file);
  if (absolute !== file) {
    throw new Error("Related group draft must be one bounded canonical file");
  }
  const row = observedJson(absolute, "related group draft", 2 * 1024 * 1024).value;
  const fields = ["schemaVersion", "scope", "groupId", "referenceId", "vocabularySha256",
    "outputs", "completed", "limitations"];
  exactKeys(row, fields, fields, "related group draft");
  if (row.schemaVersion !== 1 || row.scope !== "native-short-related-group-draft"
      || !Array.isArray(row.outputs) || row.outputs.length < 2 || row.outputs.length > 4
      || !Array.isArray(row.completed) || row.completed.length > 16) {
    throw new Error("Related group draft envelope is invalid");
  }
  const outputs = row.outputs.map(target), history = row.completed.map(completed);
  const ids = [...outputs.map(item => item.outputId), ...history.map(item => item.outputId)];
  if (new Set(ids).size !== ids.length || new Set(outputs.map(item => item.producerDir)).size !== outputs.length) {
    throw new Error("Related group outputs must have unique identities and targets");
  }
  return { groupId: stableId(row.groupId, "related group id"),
    referenceId: stableId(row.referenceId, "related group reference"),
    vocabularySha256: sha256(row.vocabularySha256, "related vocabulary hash"), outputs,
    completed: history, limitations: strings(row.limitations, "related group limitations", 64) };
}

function selectedVocabulary(target: GroupTarget, draft: GroupDraft) {
  const stored = storedAutoEditIntent(target.producerDir);
  const intent = parseAutoEditIntent(stored as unknown as Record<string, unknown>);
  const selected = nativeReferenceInputs(resolveReferenceContext(intent));
  const text = selected.files["SELECTED-REFERENCE-VOCABULARY.json"];
  const digest = text ? createHash("sha256").update(text).digest("hex") : null;
  if (selected.selected?.id !== draft.referenceId || digest !== draft.vocabularySha256) {
    throw new Error(`Related target ${target.outputId} does not select the shared reference vocabulary`);
  }
  return stored;
}

function summarized(application: Record<string, unknown>): RelatedStyleChoice[] {
  const vocabulary = Array.isArray(application.choices) ? application.choices : [];
  const supplemental = Array.isArray(application.supplementalChoices) ? application.supplementalChoices : [];
  return [...vocabulary.map(value => ({ ...objectValue(value, "authored style choice"), choiceKind: "vocabulary" })),
    ...supplemental.map(value => ({ ...objectValue(value, "authored supplemental choice"),
      choiceKind: "supplemental" }))].map(value => parseRelatedStyleChoice(value));
}

function completedManifest(directory: string): CompletedManifest {
  const observed = observedJson(path.join(directory, "PROJECT-MANIFEST.json"), "completed project manifest");
  const row = observed.value;
  if (row.schemaVersion !== 1 || row.scope !== "native-short-review-project"
      || !Array.isArray(row.files) || !row.files.length || row.files.length > 512) {
    throw new Error("Completed related project manifest is invalid");
  }
  const files = new Map(row.files.map(value => {
    const binding = objectValue(value, "completed project manifest file");
    exactKeys(binding, ["file", "sha256"], ["file", "sha256"], "completed project manifest file");
    return [stringValue(binding.file, "completed project manifest path", 256),
      sha256(binding.sha256, "completed project manifest hash")];
  }));
  if (files.size !== row.files.length) throw new Error("Completed related project manifest repeats a file");
  return { sha256: observed.sha256,
    projectHash: sha256(row.projectHash, "completed project hash"), files };
}

function expectedManifestHash(manifest: CompletedManifest, file: string): string {
  const digest = manifest.files.get(file);
  if (!digest) throw new Error(`Completed related project manifest omits ${file}`);
  return digest;
}

function completedOutput(row: GroupDraft["completed"][number], draft: GroupDraft) {
  const manifest = completedManifest(row.projectDir);
  const validated = readNativeShortProject(row.projectDir);
  if (completedManifest(row.projectDir).sha256 !== manifest.sha256) {
    throw new Error(`Completed output ${row.outputId} manifest changed while reopening`);
  }
  const projectPath = path.join(row.projectDir, "SHORT-PROJECT.json");
  const projectPin = observedJson(projectPath, "completed related project");
  if (projectPin.sha256 !== expectedManifestHash(manifest, "SHORT-PROJECT.json")
      || canonicalJsonSha256(projectPin.value) !== manifest.projectHash
      || canonicalJsonSha256(validated) !== canonicalJsonSha256(projectPin.value)) {
    throw new Error(`Completed output ${row.outputId} changed while reopening`);
  }
  const project = validated;
  const application = objectValue(project.strategy.styleApplication, "completed related style application");
  const vocabulary = objectValue(application.vocabulary, "completed related vocabulary");
  if (vocabulary.referenceId !== draft.referenceId || vocabulary.sha256 !== draft.vocabularySha256) {
    throw new Error(`Completed output ${row.outputId} uses a different reference vocabulary`);
  }
  const applicationPath = path.join(row.projectDir, "STYLE-APPLICATION.json");
  const applicationPin = observedJson(applicationPath, "completed related style application");
  if (applicationPin.sha256 !== expectedManifestHash(manifest, "STYLE-APPLICATION.json")
      || canonicalJsonSha256(application) !== canonicalJsonSha256(applicationPin.value)) {
    throw new Error(`Completed output ${row.outputId} application changed`);
  }
  const choices = summarized(application);
  const fullChoices = [...(application.choices as object[]),
    ...((application.supplementalChoices as object[] | undefined) ?? [])] as never;
  for (const binding of project.catalogFiles ?? []) {
    const staged = observedText(path.join(row.projectDir, binding.file), MAX_HTML_BYTES);
    if (staged.sha256 !== binding.sha256
        || staged.sha256 !== expectedManifestHash(manifest, binding.file)) {
      throw new Error("Completed related catalog bytes changed");
    }
  }
  const index = observedText(path.join(row.projectDir, "index.html"), MAX_HTML_BYTES);
  if (index.sha256 !== expectedManifestHash(manifest, "index.html")) {
    throw new Error("Completed related executable index changed");
  }
  const signatures = nativeStyleExecutableSignatures(fullChoices, project.catalogFiles ?? [], index.text);
  return { output: { outputId: row.outputId, status: "authored" as const,
    application: { path: applicationPath, sha256: applicationPin.sha256 }, choices },
  receipt: { outputId: row.outputId,
    project: { path: projectPath, sha256: projectPin.sha256 },
    application: { path: applicationPath, sha256: applicationPin.sha256 },
    signatures: Object.entries(signatures).map(([choiceId, digest]) => ({ choiceId, sha256: digest })) } };
}

function writeExact(file: string, value: unknown): void {
  const content = canonicalJson(value);
  if (existsSync(file)) {
    if (observedText(file, MAX_JSON_BYTES).text !== content) throw new Error(`Related group file changed: ${file}`);
    return;
  }
  writeFileSync(file, content, { flag: "wx", mode: 0o600 });
}

function contextFilename(outputId: string): string {
  return `output-${createHash("sha256").update(outputId).digest("hex").slice(0, 20)}.json`;
}

function assertInsideWorkspace(workspace: string, directory: string, label: string): void {
  const relative = path.relative(workspace, directory);
  if (!relative || relative.startsWith("..") || path.isAbsolute(relative)) {
    throw new Error(`${label} must be inside the configured canonical workspace`);
  }
}

function assertProductionWorkspace(draft: GroupDraft, destination: string): void {
  const workspace = canonicalDirectory(workspaceRoot({ initialize: false }), "related group workspace");
  for (const output of draft.outputs) {
    if (canonicalProducerDir(output.producerDir) !== output.producerDir) {
      throw new Error("Related target must be an approved canonical producer directory");
    }
  }
  for (const prior of draft.completed) assertInsideWorkspace(workspace, prior.projectDir, "Completed related project");
  const root = path.resolve(destination);
  if (root !== destination) throw new Error("Related group destination must be absolute and normalized");
  assertInsideWorkspace(workspace, root, "Related group destination");
  canonicalDirectory(existsSync(root) ? root : path.dirname(root), "related group destination parent");
}

/** Freeze one allocation and prepare every target request against its own projection. */
export function prepareNativeRelatedStyleGroup(draftFile: string, destination: string, repo: string) {
  const services: GroupServices = { selectedVocabulary, prepareRequest: prepareNativeShortRequest, completedOutput };
  const draft = readDraft(draftFile);
  assertProductionWorkspace(draft, destination);
  return prepareRelatedGroup(draft, destination, repo, services);
}

/** Test seam keeps provider/auth integration outside deterministic group freezing. */
export function prepareRelatedGroupWithServices(draftFile: string, destination: string, repo: string,
  services: GroupServices) {
  return prepareRelatedGroup(readDraft(draftFile), destination, repo, services);
}

function prepareRelatedGroup(draft: GroupDraft, destination: string, repo: string, services: GroupServices) {
  const intents = draft.outputs.map(output => services.selectedVocabulary(output, draft));
  const prior = draft.completed.map(row => services.completedOutput(row, draft));
  const outputs: RelatedStyleOutput[] = [...prior.map(row => row.output), ...draft.outputs.map(row => ({
    outputId: row.outputId, status: "planned" as const, choices: row.choices }))];
  const allocation = { schemaVersion: 1, scope: "native-short-related-group-allocation",
    groupId: draft.groupId, referenceId: draft.referenceId, vocabularySha256: draft.vocabularySha256,
    planningMode: "shared-allocation", outputs, limitations: draft.limitations,
    usageReceipts: prior.map(row => row.receipt) };
  const root = path.resolve(destination);
  if (!existsSync(root)) mkdirSync(root, { recursive: false, mode: 0o700 });
  if (realpathSync(root) !== root || !lstatSync(root).isDirectory()) throw new Error("Related group destination must be canonical");
  const allocationPath = path.join(root, "RELATED-STYLE-GROUP.json");
  writeExact(allocationPath, allocation);
  const allocationPin = { path: allocationPath, sha256: observedText(allocationPath, MAX_JSON_BYTES).sha256 };
  const requests = draft.outputs.map((target, index) => {
    const contextPath = path.join(root, contextFilename(target.outputId));
    writeExact(contextPath, { schemaVersion: 1, scope: "related-native-short-style-context",
      groupId: draft.groupId, currentOutputId: target.outputId, referenceId: draft.referenceId,
      vocabularySha256: draft.vocabularySha256, planningMode: "shared-allocation",
      groupAllocation: allocationPin, outputs, limitations: draft.limitations });
    return { outputId: target.outputId, ...services.prepareRequest({ producerDir: target.producerDir,
      intent: intents[index], repo, relatedStyleContextPath: contextPath }) };
  });
  return { status: "related-group-ready-for-local-strategy", allocation: allocationPin,
    outputCount: requests.length, requests };
}
