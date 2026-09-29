/** Related Shorts share one frozen allocation and executable sibling signatures. */
import assert from "node:assert/strict";
import { copyFileSync, mkdtempSync, mkdirSync, readFileSync, realpathSync, rmSync,
  symlinkSync, unlinkSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { canonicalJson, fileSha256 } from "../auto-edit-hash";
import { loadNativeRelatedStyleContext } from "../native-related-style-context";
import { prepareNativeRelatedStyleGroup, prepareRelatedGroupWithServices } from "../native-related-style-group";
import { nativeStyleExecutableSignatures } from "../native-style-executable-signature";

const HASH = "a".repeat(64);
function choice(output: string) {
  return { choiceKind: "vocabulary", choiceId: `${output}-card`, sceneIndex: 0,
    familyId: "family-cards", contenderRef: `mirror:${output}-card`,
    anatomy: `TEST ${output} hierarchy`, configuration: `TEST ${output} placement`,
    development: `TEST ${output} reveal` };
}

function draftFixture(count = 2) {
  const root = realpathSync(mkdtempSync(path.join(os.tmpdir(), "related-style-group-")));
  const producers = Array.from({ length: count }, (_, index) => {
    const directory = path.join(root, `producer-${index + 1}`); mkdirSync(directory); return directory;
  });
  const draft = { schemaVersion: 1, scope: "native-short-related-group-draft",
    groupId: "launch-set", referenceId: "reference-one", vocabularySha256: HASH,
    outputs: producers.map((producerDir, index) => ({ outputId: `short-${index + 1}`,
      producerDir, choices: [choice(`short-${index + 1}`)] })),
    completed: [] as Array<{ outputId: string; projectDir: string }>, limitations: [] };
  const file = path.join(root, "group-draft.json"); writeFileSync(file, JSON.stringify(draft));
  return { root, file, destination: path.join(root, "frozen-group"), draft,
    cleanup: () => rmSync(root, { recursive: true, force: true }) };
}

test("group controller freezes one allocation and binds every request projection", () => {
  const fixture = draftFixture(), prepared: string[] = [];
  const services = { selectedVocabulary: () => ({ mode: "short" }),
    completedOutput: () => { throw new Error("TEST no completed projects"); },
    prepareRequest: (input: { relatedStyleContextPath?: string }) => {
      const file = input.relatedStyleContextPath!; prepared.push(file);
      const snapshot = loadNativeRelatedStyleContext(file);
      return { status: "ready-for-local-strategy", directory: path.dirname(file), requestHash: HASH,
        request: {}, handoff: "TEST", sourceCount: 1, providerCalls: 0,
        currentOutputId: snapshot.record.currentOutputId };
    } };
  try {
    const result = prepareRelatedGroupWithServices(fixture.file, fixture.destination, fixture.root, services as never);
    assert.equal(result.outputCount, 2); assert.equal(prepared.length, 2);
    const snapshots = prepared.map(loadNativeRelatedStyleContext);
    assert.deepEqual(snapshots.map(row => row.record.currentOutputId), ["short-1", "short-2"]);
    assert.equal(snapshots[0].record.groupAllocation?.path, result.allocation.path);
    assert.equal(snapshots[1].record.groupAllocation?.sha256, result.allocation.sha256);
    assert.equal(readFileSync(result.allocation.path, "utf8").includes("usageReceipts"), true);
    const replay = prepareRelatedGroupWithServices(fixture.file, fixture.destination, fixture.root, services as never);
    assert.equal(replay.allocation.sha256, result.allocation.sha256);
  } finally { fixture.cleanup(); }
});

test("group controller requires two to four unique producer targets", () => {
  const fixture = draftFixture(2);
  const services = { selectedVocabulary: () => ({}), completedOutput: () => ({}), prepareRequest: () => ({}) };
  try {
    fixture.draft.outputs.pop(); writeFileSync(fixture.file, JSON.stringify(fixture.draft));
    assert.throws(() => prepareRelatedGroupWithServices(fixture.file, fixture.destination, fixture.root,
      services as never), /envelope/);
    fixture.draft.outputs.push(fixture.draft.outputs[0]); writeFileSync(fixture.file, JSON.stringify(fixture.draft));
    assert.throws(() => prepareRelatedGroupWithServices(fixture.file, fixture.destination, fixture.root,
      services as never), /unique/);
  } finally { fixture.cleanup(); }
});

function executableReceiptFixture() {
  const fixture = draftFixture(), project = path.join(fixture.root, "completed"); mkdirSync(project);
  const application = { schemaVersion: 1,
    vocabulary: { path: "/TEST/vocabulary.json", sha256: HASH, referenceId: "reference-one" },
    choices: [{ choiceId: "prior-card", sceneIndex: 0, viewerNeed: "TEST show proof",
      familyId: "family-cards", contenderRef: "mirror:prior-card", anatomy: "TEST evidence card",
      configuration: "TEST right rail", development: "TEST proof then label",
      catalogFiles: ["compositions/prior-card.html"], visibleIds: ["prior-card"],
      consideredContenders: ["mirror:prior-card"], selectionReason: "TEST", repeatMode: "new",
      repeatReason: "TEST first use" }], limitations: [] };
  const implementation = path.join(project, "compositions"); mkdirSync(implementation);
  const staged = path.join(implementation, "prior-card.html"); writeFileSync(staged, "<template>TEST</template>");
  const catalogFiles = [{ file: "compositions/prior-card.html", path: staged,
    sha256: fileSha256(staged)!, catalogId: "prior-card", sourceSha256: "b".repeat(64) }];
  const html = '<div id="prior-card" data-start="0" data-duration="30" data-composition-src="compositions/prior-card.html"></div>';
  const projectFile = path.join(project, "SHORT-PROJECT.json");
  writeFileSync(projectFile, JSON.stringify({ strategy: { styleApplication: application }, catalogFiles }));
  const applicationFile = path.join(project, "STYLE-APPLICATION.json"); writeFileSync(applicationFile, JSON.stringify(application));
  writeFileSync(path.join(project, "index.html"), html);
  return { fixture, project, application, applicationFile, projectFile, catalogFiles, html };
}

function executableContextFixture() {
  const f = executableReceiptFixture();
  const summary = { choiceKind: "vocabulary", choiceId: "prior-card", sceneIndex: 0,
    familyId: "family-cards", contenderRef: "mirror:prior-card", anatomy: "TEST evidence card",
    configuration: "TEST right rail", development: "TEST proof then label" };
  const signatures = nativeStyleExecutableSignatures(f.application.choices, f.catalogFiles, f.html);
  const outputs = [{ outputId: "prior-short", status: "authored", application: {
    path: f.applicationFile, sha256: fileSha256(f.applicationFile)! }, choices: [summary] },
  { outputId: "short-1", status: "planned", choices: [choice("short-1")] }];
  const allocation = { schemaVersion: 1, scope: "native-short-related-group-allocation",
    groupId: "launch-set", referenceId: "reference-one", vocabularySha256: HASH,
    planningMode: "shared-allocation", outputs, limitations: [], usageReceipts: [{ outputId: "prior-short",
      project: { path: f.projectFile, sha256: fileSha256(f.projectFile)! },
      application: { path: f.applicationFile, sha256: fileSha256(f.applicationFile)! },
      signatures: [{ choiceId: "prior-card", sha256: signatures["prior-card"] }] }] };
  const allocationFile = path.join(f.fixture.root, "allocation.json");
  writeFileSync(allocationFile, canonicalJson(allocation));
  const contextFile = path.join(f.fixture.root, "context.json");
  writeFileSync(contextFile, canonicalJson({ schemaVersion: 1,
    scope: "related-native-short-style-context", groupId: "launch-set",
    currentOutputId: "short-1", referenceId: "reference-one", vocabularySha256: HASH,
    planningMode: "shared-allocation", groupAllocation: { path: allocationFile,
      sha256: fileSha256(allocationFile)! }, outputs, limitations: [] }));
  return { ...f, contextFile, allocationFile, signatures };
}

test("shared allocation verifies completed usage from executable bytes and mounted tags", () => {
  const f = executableContextFixture();
  try {
    const snapshot = loadNativeRelatedStyleContext(f.contextFile);
    assert.equal(snapshot.executableSignatures.get("prior-short")?.get("prior-card"), f.signatures["prior-card"]);
    writeFileSync(path.join(f.project, "index.html"), f.html.replace(
      'data-duration="30"', 'data-duration="30" data-layout="stack"'));
    assert.throws(() => loadNativeRelatedStyleContext(f.contextFile), /signatures changed/);
  } finally { f.fixture.cleanup(); }
});

test("related context rejects symlink substitution for every pinned executable input", () => {
  const paths = [(f: ReturnType<typeof executableContextFixture>) => f.contextFile,
    (f: ReturnType<typeof executableContextFixture>) => f.allocationFile,
    (f: ReturnType<typeof executableContextFixture>) => f.applicationFile,
    (f: ReturnType<typeof executableContextFixture>) => f.projectFile,
    (f: ReturnType<typeof executableContextFixture>) => f.catalogFiles[0].path,
    (f: ReturnType<typeof executableContextFixture>) => path.join(f.project, "index.html")];
  for (const select of paths) {
    const f = executableContextFixture();
    try {
      const original = select(f), replacement = `${original}.replacement`;
      copyFileSync(original, replacement); unlinkSync(original); symlinkSync(replacement, original);
      assert.throws(() => loadNativeRelatedStyleContext(f.contextFile));
    } finally { f.fixture.cleanup(); }
  }
});

function productionWorkspaceFixture() {
  const root = realpathSync(mkdtempSync(path.join(os.tmpdir(), "related-style-workspace-")));
  const workspace = path.join(root, "workspace"); mkdirSync(workspace);
  const producers = ["one", "two"].map(name => {
    const project = path.join(workspace, name); mkdirSync(project); mkdirSync(path.join(project, "producer"));
    writeFileSync(path.join(project, "project.json"), JSON.stringify({ origin: "raw", history: [] }));
    return path.join(project, "producer");
  });
  const draft = { schemaVersion: 1, scope: "native-short-related-group-draft",
    groupId: "launch-set", referenceId: "reference-one", vocabularySha256: HASH,
    outputs: producers.map((producerDir, index) => ({ outputId: `short-${index + 1}`,
      producerDir, choices: [choice(`short-${index + 1}`)] })),
    completed: [] as Array<{ outputId: string; projectDir: string }>, limitations: [] };
  const file = path.join(workspace, "draft.json"); writeFileSync(file, JSON.stringify(draft));
  return { root, workspace, file, draft, destination: path.join(workspace, "frozen-group"),
    cleanup: () => rmSync(root, { recursive: true, force: true }) };
}

test("production wrapper confines targets, completed projects and destination to its workspace", () => {
  const f = productionWorkspaceFixture(), prior = process.env.SNIPER_WORKSPACE_ROOT;
  process.env.SNIPER_WORKSPACE_ROOT = f.workspace;
  try {
    const outsideProject = path.join(f.root, "outside-project");
    mkdirSync(outsideProject); mkdirSync(path.join(outsideProject, "producer"));
    writeFileSync(path.join(outsideProject, "project.json"), JSON.stringify({ origin: "raw", history: [] }));
    f.draft.outputs[0].producerDir = path.join(outsideProject, "producer");
    writeFileSync(f.file, JSON.stringify(f.draft));
    assert.throws(() => prepareNativeRelatedStyleGroup(f.file, f.destination, f.root), /configured local workspace/);
    f.draft.outputs[0].producerDir = path.join(f.workspace, "one", "producer");
    writeFileSync(f.file, JSON.stringify(f.draft));
    assert.throws(() => prepareNativeRelatedStyleGroup(f.file, path.join(f.root, "outside"), f.root),
      /destination must be inside/);
    const completed = path.join(f.root, "completed"); mkdirSync(completed);
    f.draft.completed = [{ outputId: "completed-short", projectDir: completed }];
    writeFileSync(f.file, JSON.stringify(f.draft));
    assert.throws(() => prepareNativeRelatedStyleGroup(f.file, f.destination, f.root),
      /Completed related project must be inside/);
  } finally {
    if (prior === undefined) delete process.env.SNIPER_WORKSPACE_ROOT;
    else process.env.SNIPER_WORKSPACE_ROOT = prior;
    f.cleanup();
  }
});

test("executable signature ignores timing and IDs but detects real configuration changes", () => {
  const root = realpathSync(mkdtempSync(path.join(os.tmpdir(), "style-signature-")));
  try {
    const first = path.join(root, "first.html"), second = path.join(root, "second.html");
    writeFileSync(first, "<template>TEST same implementation</template>");
    writeFileSync(second, readFileSync(first));
    const files = [first, second].map((file, index) => ({
      file: `compositions/${index}.html`, path: file, sha256: fileSha256(file)!,
      catalogId: "same-catalog-item", sourceSha256: "b".repeat(64),
    }));
    const left = nativeStyleExecutableSignatures([{ choiceId: "left", sceneIndex: 0,
      catalogFiles: ["compositions/0.html"], visibleIds: ["left-id"] }], files,
    '<div id="left-id" data-start="0" data-duration="1" data-composition-src="compositions/0.html" data-layout="split"></div>');
    const right = nativeStyleExecutableSignatures([{ choiceId: "right", sceneIndex: 5,
      catalogFiles: ["compositions/1.html"], visibleIds: ["right-id"] }], files,
    '<div id="right-id" data-start="9" data-duration="2" data-composition-src="compositions/1.html" data-layout="split"></div>');
    assert.equal(left.left, right.right);
    const configured = nativeStyleExecutableSignatures([{ choiceId: "right", sceneIndex: 5,
      catalogFiles: ["compositions/1.html"], visibleIds: ["right-id"] }], files,
    '<div id="right-id" data-start="9" data-duration="2" data-composition-src="compositions/1.html" data-layout="stack"></div>');
    assert.notEqual(left.left, configured.right);
  } finally { rmSync(root, { recursive: true, force: true }); }
});
