/** Style choices bind analyzed vocabulary to executable native scene evidence. */
import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { fileSha256 } from "../auto-edit-hash";
import { assertNativeStyleApplication, type NativeStyleApplication } from "../native-style-application";
import { nativeStyleExecutableSignatures } from "../native-style-executable-signature";

function fixture() {
  const directory = realpathSync(mkdtempSync(path.join(os.tmpdir(), "native-style-application-")));
  const requestPath = path.join(directory, "SHORT-REQUEST.json");
  const vocabularyPath = path.join(directory, "SELECTED-REFERENCE-VOCABULARY.json");
  const vocabulary = { referenceId: "test-ref", candidates: {
    "mirror:meter-card": { record: { id: "meter-card" } },
    "mirror:callout-card": { record: { id: "callout-card" } },
  }, families: [{ id: "comparison", contenders: [
    { catalogRef: "mirror:meter-card", availability: "ready" },
    { catalogRef: "mirror:callout-card", availability: "ready" },
  ] }] };
  writeFileSync(vocabularyPath, JSON.stringify(vocabulary));
  const vocabularySha256 = fileSha256(vocabularyPath)!;
  writeFileSync(requestPath, JSON.stringify({ selectedReference: { id: "test-ref", styleVocabularyAvailable: true },
    selectedReferences: [{ path: vocabularyPath, sha256: vocabularySha256 }] }));
  const application: NativeStyleApplication = { schemaVersion: 1,
    vocabulary: { path: vocabularyPath, sha256: vocabularySha256, referenceId: "test-ref" },
    choices: [{ choiceId: "scene-0-comparison", sceneIndex: 0,
      viewerNeed: "TEST compare two states", familyId: "comparison",
      contenderRef: "mirror:meter-card", configuration: "TEST compact copy and timing",
      anatomy: "TEST two-panel comparison with result accent",
      development: "TEST reveal baseline and then result", catalogFiles: ["compositions/meter-card.html"],
      visibleIds: ["comparison-panel"], consideredContenders: ["mirror:meter-card", "mirror:callout-card"],
      selectionReason: "TEST meter preserves simultaneous quantities", repeatMode: "new",
      repeatReason: "TEST first use in this plan" }], limitations: ["TEST structure only"] };
  const packet: Record<string, unknown> = { selectedReference: { id: "test-ref", styleVocabularyAvailable: true },
    selectedReferences: [{ path: vocabularyPath, sha256: vocabularySha256 }] };
  const input = { application, packet,
    requestPath, scenes: [{ viewingNeed: "TEST compare two states", visibleIds: ["comparison-panel"] }],
    html: '<div id="comparison-panel" data-composition-src="compositions/meter-card.html"></div>',
    catalogFiles: [{ file: "compositions/meter-card.html", path: "/TEST/not-read.html", sha256: "0".repeat(64),
      catalogId: "meter-card", sourceSha256: "1".repeat(64) }] };
  return { directory, application, input, cleanup: () => rmSync(directory, { recursive: true, force: true }) };
}

function relatedFixture(mode: "serialized" | "shared-allocation" = "serialized") {
  const f = fixture(), siblingFile = path.join(f.directory, "sibling-style-application.json");
  writeFileSync(siblingFile, JSON.stringify(f.application));
  const summary = f.application.choices.map(row => ({ choiceKind: "vocabulary" as const, choiceId: row.choiceId,
    sceneIndex: row.sceneIndex, familyId: row.familyId,
    contenderRef: row.contenderRef, anatomy: row.anatomy,
    configuration: row.configuration, development: row.development }));
  const sibling = { outputId: "short-1", status: mode === "serialized" ? "authored" : "planned",
    ...(mode === "serialized" ? { application: { path: siblingFile, sha256: fileSha256(siblingFile)! } } : {}),
    choices: summary };
  f.application.choices[0].configuration = "TEST alternate side-by-side composition";
  f.application.choices[0].development = "TEST reveal result before the baseline annotation";
  f.application.choices[0].repeatMode = "varied";
  const current = { outputId: "short-2", status: "planned", choices: f.application.choices.map(row => ({
    choiceKind: "vocabulary" as const,
    choiceId: row.choiceId, sceneIndex: row.sceneIndex, familyId: row.familyId, contenderRef: row.contenderRef,
    anatomy: row.anatomy, configuration: row.configuration, development: row.development })) };
  const contextFile = path.join(f.directory, "RELATED-STYLE-CONTEXT.json");
  writeFileSync(contextFile, JSON.stringify({ schemaVersion: 1, scope: "related-native-short-style-context",
    groupId: "launch-set", currentOutputId: "short-2", referenceId: "test-ref",
    vocabularySha256: f.application.vocabulary.sha256, planningMode: mode,
    outputs: mode === "serialized" ? [sibling] : [sibling, current], limitations: [] }));
  f.input.packet = { ...f.input.packet, relatedStyleContext: { source: { path: contextFile,
    sha256: fileSha256(contextFile)! }, groupId: "launch-set", currentOutputId: "short-2",
    referenceId: "test-ref", vocabularySha256: f.application.vocabulary.sha256, planningMode: mode } };
  f.application.relatedContext = { path: contextFile, sha256: fileSha256(contextFile)!,
    groupId: "launch-set", currentOutputId: "short-2" };
  f.application.relatedComparisons = [{ currentChoiceId: "scene-0-comparison", outputId: "short-1",
    siblingChoiceId: "scene-0-comparison",
    relationship: "varied", compositionDifference: "TEST side-by-side replaces the meter stack",
    developmentDifference: "TEST result appears before baseline annotation",
    reason: "TEST this claim benefits from result-first development" }];
  return f;
}
test("accepts an evidence-bound choice from the prepared family", () => {
  const f = fixture();
  try {
    assert.deepEqual(assertNativeStyleApplication(f.input), f.application);
  } finally { f.cleanup(); }
});
test("requires an application exactly when the request has a vocabulary", () => {
  const f = fixture();
  try {
    assert.throws(() => assertNativeStyleApplication({ ...f.input, application: undefined }), /requires a style application/);
    assert.throws(() => assertNativeStyleApplication({ ...f.input,
      packet: { selectedReference: null } }), /absent prepared vocabulary/);
    assert.equal(assertNativeStyleApplication({ ...f.input, application: undefined,
      packet: { selectedReference: null } }), null);
  } finally { f.cleanup(); }
});
test("rejects a family mismatch, unavailable or unmounted treatment, or unrelated scene visual", () => {
  const f = fixture();
  try {
    const changed = structuredClone(f.application);
    changed.choices[0].familyId = "evidence";
    assert.throws(() => assertNativeStyleApplication({ ...f.input, application: changed }), /family contenders/);
    changed.choices[0].familyId = "comparison"; changed.choices[0].catalogFiles = ["compositions/other.html"];
    assert.throws(() => assertNativeStyleApplication({ ...f.input, application: changed }), /mounted catalog/);
    changed.choices[0].catalogFiles = ["compositions/meter-card.html"]; changed.choices[0].visibleIds = ["outside"];
    assert.throws(() => assertNativeStyleApplication({ ...f.input, application: changed }), /outside its scene/);
    changed.choices[0].visibleIds = ["comparison-panel"];
    assert.throws(() => assertNativeStyleApplication({ ...f.input, application: changed,
      html: '<div id="comparison-panel"></div><div id="elsewhere" data-composition-src="compositions/meter-card.html"></div>' }),
    /scene-visible/);
    const vocabulary = JSON.parse(readFileSync(f.application.vocabulary.path, "utf8"));
    vocabulary.families[0].contenders[0].availability = "research-only";
    writeFileSync(f.application.vocabulary.path, JSON.stringify(vocabulary));
    changed.vocabulary.sha256 = fileSha256(f.application.vocabulary.path)!;
    (f.input.packet.selectedReferences as Array<{ sha256: string }>)[0].sha256 = changed.vocabulary.sha256;
    assert.throws(() => assertNativeStyleApplication({ ...f.input, application: changed }), /not ready/);
  } finally { f.cleanup(); }
});
test("repeated contenders require an explicit repeat or variation decision", () => {
  const f = fixture();
  try {
    const application = structuredClone(f.application);
    application.choices.push({ ...structuredClone(application.choices[0]), choiceId: "scene-1-comparison",
      sceneIndex: 1, repeatMode: "new" });
    const input = { ...f.input, application,
      scenes: [...f.input.scenes, { viewingNeed: "TEST compare two states", visibleIds: ["comparison-panel"] }] };
    assert.throws(() => assertNativeStyleApplication(input), /repeat mode/);
    application.choices[1].repeatMode = "callback";
    assert.equal(assertNativeStyleApplication(input)?.choices[1].repeatMode, "callback");
  } finally { f.cleanup(); }
});
test("different catalog ids cannot fake a new composition formula", () => {
  const f = fixture();
  try {
    const application = structuredClone(f.application);
    application.choices.push({ ...structuredClone(application.choices[0]), choiceId: "scene-1-callout",
      sceneIndex: 1, contenderRef: "mirror:callout-card", catalogFiles: ["compositions/callout-card.html"],
      visibleIds: ["callout-panel"], repeatMode: "new" });
    const input = { ...f.input, application,
      html: f.input.html + '<div id="callout-panel" data-composition-src="compositions/callout-card.html"></div>',
      scenes: [...f.input.scenes, { viewingNeed: "TEST compare two states", visibleIds: ["callout-panel"] }],
      catalogFiles: [...f.input.catalogFiles, { file: "compositions/callout-card.html", path: "/TEST/callout.html",
        sha256: "2".repeat(64), catalogId: "callout-card", sourceSha256: "3".repeat(64) }] };
    assert.throws(() => assertNativeStyleApplication(input), /repeat mode/);
    application.choices[1].repeatMode = "callback";
    assert.equal(assertNativeStyleApplication(input)?.choices[1].repeatMode, "callback");
  } finally { f.cleanup(); }
});
test("native supplemental choices bind full-catalog treatments and may replace all vocabulary choices", () => {
  const f = fixture();
  try {
    const application = structuredClone(f.application);
    application.choices = [];
    application.supplementalChoices = [{ choiceId: "scene-0-catalog", sceneIndex: 0,
      viewerNeed: "TEST compare two states", catalogId: "meter-card",
      anatomy: "TEST evidence card with one result accent", configuration: "TEST compact card at right",
      development: "TEST evidence enters then the result holds", catalogFiles: ["compositions/meter-card.html"],
      visibleIds: ["comparison-panel"], selectionReason: "TEST full catalog fits this claim better",
      relationshipMode: "coherent", relationshipEvidence: "TEST retains compact hierarchy and accent",
      repeatMode: "new", repeatReason: "TEST first use" }];
    const result = assertNativeStyleApplication({ ...f.input, application });
    assert.equal(result?.choices.length, 0); assert.equal(result?.supplementalChoices?.length, 1);
    application.supplementalChoices[0].catalogId = "callout-card";
    assert.throws(() => assertNativeStyleApplication({ ...f.input, application }), /mounted catalog/);
  } finally { f.cleanup(); }
});
test("shared related allocation can vary full-catalog supplemental choices", () => {
  const f = fixture();
  try {
    f.application.choices = [];
    f.application.supplementalChoices = [{ choiceId: "scene-0-catalog", sceneIndex: 0,
      viewerNeed: "TEST compare two states", catalogId: "meter-card",
      anatomy: "TEST evidence card with one result accent", configuration: "TEST compact right card",
      development: "TEST result enters before support", catalogFiles: ["compositions/meter-card.html"],
      visibleIds: ["comparison-panel"], selectionReason: "TEST content fit",
      relationshipMode: "coherent", relationshipEvidence: "TEST compact hierarchy",
      repeatMode: "varied", repeatReason: "TEST varies the earlier left card" }];
    const sibling = { choiceKind: "supplemental", choiceId: "scene-0-sibling", sceneIndex: 0,
      catalogId: "meter-card", anatomy: "TEST evidence card with one result accent",
      configuration: "TEST compact left card", development: "TEST support enters before result" };
    const current = { choiceKind: "supplemental", choiceId: "scene-0-catalog", sceneIndex: 0,
      catalogId: "meter-card", anatomy: f.application.supplementalChoices[0].anatomy,
      configuration: f.application.supplementalChoices[0].configuration,
      development: f.application.supplementalChoices[0].development };
    const contextFile = path.join(f.directory, "RELATED-STYLE-CONTEXT.json");
    writeFileSync(contextFile, JSON.stringify({ schemaVersion: 1, scope: "related-native-short-style-context",
      groupId: "catalog-set", currentOutputId: "short-2", referenceId: "test-ref",
      vocabularySha256: f.application.vocabulary.sha256, planningMode: "shared-allocation",
      outputs: [{ outputId: "short-1", status: "planned", choices: [sibling] },
        { outputId: "short-2", status: "planned", choices: [current] }], limitations: [] }));
    f.input.packet = { ...f.input.packet, relatedStyleContext: { source: { path: contextFile,
      sha256: fileSha256(contextFile)! }, groupId: "catalog-set", currentOutputId: "short-2",
      referenceId: "test-ref", vocabularySha256: f.application.vocabulary.sha256,
      planningMode: "shared-allocation" } };
    f.application.relatedContext = { path: contextFile, sha256: fileSha256(contextFile)!,
      groupId: "catalog-set", currentOutputId: "short-2" };
    f.application.relatedComparisons = [{ currentChoiceId: "scene-0-catalog", outputId: "short-1",
      siblingChoiceId: "scene-0-sibling", relationship: "varied",
      compositionDifference: "TEST right replaces left", developmentDifference: "TEST result leads",
      reason: "TEST the claim benefits from result-first development" }];
    assert.equal(assertNativeStyleApplication(f.input)?.supplementalChoices?.length, 1);
    f.application.supplementalChoices[0].development = "TEST drifts from allocation";
    assert.throws(() => assertNativeStyleApplication(f.input), /shared group allocation/);
  } finally { f.cleanup(); }
});
test("presenter or restraint can record zero style selections", () => {
  const f = fixture();
  try {
    const application = structuredClone(f.application); application.choices = [];
    assert.deepEqual(assertNativeStyleApplication({ ...f.input, application, catalogFiles: [],
      html: '<div id="comparison-panel"></div>' })?.choices, []);
  } finally { f.cleanup(); }
});
test("one scene can carry several choices and cannot omit a mounted vocabulary treatment", () => {
  const f = fixture();
  try {
    const callout = { ...structuredClone(f.application.choices[0]), choiceId: "scene-0-callout",
      contenderRef: "mirror:callout-card", catalogFiles: ["compositions/callout-card.html"],
      visibleIds: ["callout-panel"], anatomy: "TEST single result callout with accent rule",
      selectionReason: "TEST callout isolates the conclusion" };
    const application = structuredClone(f.application); application.choices.push(callout);
    const input = { ...f.input, application,
      html: f.input.html + '<div id="callout-panel" data-composition-src="compositions/callout-card.html"></div>',
      scenes: [{ ...f.input.scenes[0], visibleIds: ["comparison-panel", "callout-panel"] }],
      catalogFiles: [...f.input.catalogFiles, { file: "compositions/callout-card.html",
        path: "/TEST/not-read-callout.html", sha256: "2".repeat(64),
        catalogId: "callout-card", sourceSha256: "3".repeat(64) }] };
    assert.equal(assertNativeStyleApplication(input)?.choices.length, 2);
    assert.throws(() => assertNativeStyleApplication({ ...input, application: f.application }), /every mounted/);
  } finally { f.cleanup(); }
});
test("changed vocabulary bytes stale the authored application", () => {
  const f = fixture();
  try {
    writeFileSync(f.application.vocabulary.path, JSON.stringify({ referenceId: "test-ref", families: [], candidates: {} }));
    assert.throws(() => assertNativeStyleApplication(f.input), /not pinned by the prepared request/);
  } finally { f.cleanup(); }
});
test("serialized sibling choices require semantic comparisons", () => {
  const f = relatedFixture();
  try {
    assert.equal(assertNativeStyleApplication(f.input)?.relatedComparisons?.length, 1);
    const missing = structuredClone(f.application); delete missing.relatedComparisons;
    assert.throws(() => assertNativeStyleApplication({ ...f.input, application: missing }), /requires application comparisons/);
    const context = JSON.parse(readFileSync(f.application.relatedContext!.path, "utf8"));
    const siblingPath = context.outputs[0].application.path;
    const sibling = JSON.parse(readFileSync(siblingPath, "utf8"));
    sibling.choices[0].contenderRef = "mirror:unknown";
    writeFileSync(siblingPath, JSON.stringify(sibling));
    context.outputs[0].choices[0].contenderRef = "mirror:unknown";
    context.outputs[0].application.sha256 = fileSha256(siblingPath)!;
    writeFileSync(f.application.relatedContext!.path, JSON.stringify(context));
    f.application.relatedContext!.sha256 = fileSha256(f.application.relatedContext!.path)!;
    const summary = f.input.packet.relatedStyleContext as { source: { sha256: string } };
    summary.source.sha256 = f.application.relatedContext!.sha256;
    assert.throws(() => assertNativeStyleApplication(f.input), /unknown family contender/);
  } finally { f.cleanup(); }
});
test("identical related treatments need an explicit matching callback", () => {
  const f = relatedFixture();
  try {
    f.application.choices[0].configuration = "TEST compact copy and timing";
    f.application.choices[0].development = "TEST reveal baseline and then result";
    assert.throws(() => assertNativeStyleApplication(f.input), /explicit matching signature or callback/);
    f.application.choices[0].repeatMode = "callback";
    f.application.relatedComparisons![0].relationship = "callback";
    assert.equal(assertNativeStyleApplication(f.input)?.choices[0].repeatMode, "callback");
  } finally { f.cleanup(); }
});
test("related outputs compare composition signatures across different contender ids", () => {
  const f = relatedFixture();
  try {
    const context = JSON.parse(readFileSync(f.application.relatedContext!.path, "utf8"));
    const siblingPath = context.outputs[0].application.path;
    const sibling = JSON.parse(readFileSync(siblingPath, "utf8"));
    sibling.choices[0].contenderRef = "mirror:callout-card";
    writeFileSync(siblingPath, JSON.stringify(sibling));
    context.outputs[0].choices[0].contenderRef = "mirror:callout-card";
    context.outputs[0].application.sha256 = fileSha256(siblingPath)!;
    writeFileSync(f.application.relatedContext!.path, JSON.stringify(context));
    f.application.relatedContext!.sha256 = fileSha256(f.application.relatedContext!.path)!;
    const summary = f.input.packet.relatedStyleContext as { source: { sha256: string } };
    summary.source.sha256 = f.application.relatedContext!.sha256;
    f.application.choices[0].configuration = "TEST compact copy and timing";
    f.application.choices[0].development = "TEST reveal baseline and then result";
    assert.throws(() => assertNativeStyleApplication(f.input), /explicit matching signature or callback/);
    f.application.choices[0].repeatMode = "callback";
    f.application.relatedComparisons![0].relationship = "callback";
    assert.equal(assertNativeStyleApplication(f.input)?.choices[0].repeatMode, "callback");
  } finally { f.cleanup(); }
});
test("shared allocation freezes each current output choice", () => {
  const f = relatedFixture("shared-allocation");
  try {
    assert.equal(assertNativeStyleApplication(f.input)?.relatedContext?.groupId, "launch-set");
    f.application.choices[0].development = "TEST unallocated development";
    assert.throws(() => assertNativeStyleApplication(f.input), /differs from the shared group allocation/);
  } finally { f.cleanup(); }
});

test("completed sibling executable signatures defeat prose-only variation", () => {
  const f = relatedFixture();
  try {
    const context = JSON.parse(readFileSync(f.application.relatedContext!.path, "utf8"));
    const siblingPath = context.outputs[0].application.path;
    const sibling = JSON.parse(readFileSync(siblingPath, "utf8"));
    const project = path.join(f.directory, "completed-short");
    const compositions = path.join(project, "compositions");
    mkdirSync(compositions, { recursive: true });
    const staged = path.join(compositions, "meter-card.html");
    writeFileSync(staged, "<template>TEST exact component</template>");
    f.input.catalogFiles[0].sha256 = fileSha256(staged)!;
    const catalogFiles = [{ ...f.input.catalogFiles[0], path: staged }];
    const projectFile = path.join(project, "SHORT-PROJECT.json");
    writeFileSync(projectFile, JSON.stringify({ strategy: { styleApplication: sibling }, catalogFiles }));
    writeFileSync(path.join(project, "index.html"), f.input.html);
    const signatures = nativeStyleExecutableSignatures(sibling.choices, catalogFiles, f.input.html);
    const allocationFile = path.join(f.directory, "RELATED-STYLE-GROUP.json");
    writeFileSync(allocationFile, JSON.stringify({ schemaVersion: 1,
      scope: "native-short-related-group-allocation", groupId: context.groupId,
      referenceId: context.referenceId, vocabularySha256: context.vocabularySha256,
      planningMode: context.planningMode, outputs: context.outputs, limitations: context.limitations,
      usageReceipts: [{ outputId: "short-1", project: { path: projectFile, sha256: fileSha256(projectFile)! },
        application: { path: siblingPath, sha256: fileSha256(siblingPath)! },
        signatures: [{ choiceId: "scene-0-comparison", sha256: signatures["scene-0-comparison"] }] }] }));
    context.groupAllocation = { path: allocationFile, sha256: fileSha256(allocationFile)! };
    writeFileSync(f.application.relatedContext!.path, JSON.stringify(context));
    f.application.relatedContext!.sha256 = fileSha256(f.application.relatedContext!.path)!;
    const summary = f.input.packet.relatedStyleContext as { source: { sha256: string } };
    summary.source.sha256 = f.application.relatedContext!.sha256;
    assert.throws(() => assertNativeStyleApplication(f.input), /explicit matching signature or callback/);
    f.application.choices[0].repeatMode = "callback";
    f.application.relatedComparisons![0].relationship = "callback";
    assert.equal(assertNativeStyleApplication(f.input)?.choices[0].repeatMode, "callback");
  } finally { f.cleanup(); }
});
