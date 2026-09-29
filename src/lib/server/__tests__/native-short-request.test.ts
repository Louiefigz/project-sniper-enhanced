/** Local handoff and HTTP boundary tests; synthetic bytes are never rendered. */
import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { NextRequest } from "next/server";
import { prepareNativeShortRequest } from "../native-short-request";
import { fileSha256 } from "../auto-edit-hash";
import { refreshNativeAssetUseFixture } from "./_native-short-origin-fixture";
import { bindNativeVisualPlanFixture, nativeShortFixture,
  refreshNativePacingFixture, refreshNativePrebuildReviewFixture } from "./_native-short-project-fixture";
import { readNativeShortProject, writeNativeShortProject } from "../native-short-project";
import { POST } from "../../../app/api/producer/native-short/route";
import { refreshVisualSourceFixture } from "./_visual-source-fixture";
import { assertNativeVisualSources } from "../visual-source-admission";
import { shortDirectionInstructions } from "@/lib/producer/short-direction";

function fixture() {
  const directory = realpathSync(mkdtempSync(path.join(os.tmpdir(), "sniper-short-request-")));
  const root = path.join(directory, "project"), producerDir = path.join(root, "producer"), source = path.join(root, "source");
  mkdirSync(producerDir, { recursive: true }); mkdirSync(source);
  const plan = nativeShortFixture(source), asset = plan.assets[0];
  const intent = { mode: "short", scope: "produced", lanes: {}, shortDirection: plan.request };
  writeFileSync(path.join(root, "project.json"), JSON.stringify({ origin: "raw", history: [], intent }));
  const receipts = path.join(source, ".sniper-source-sets"); mkdirSync(receipts);
  const receipt = path.join(receipts, "seed.json"); writeFileSync(receipt, JSON.stringify({ test: "synthetic admission" }));
  const receiptSha256 = fileSha256(receipt)!, receiptPath = `.sniper-source-sets/${receiptSha256}.json`;
  writeFileSync(path.join(source, receiptPath), readFileSync(receipt));
  const transcript = path.join(source, "transcript.json"); writeFileSync(transcript, JSON.stringify({ words: ["Test", "words."] }));
  const manifest = { sources: [{ id: "test", path: asset.path, sourceSha256: asset.sha256,
    duration: 2, resolution: [1920, 1080], fps: 25, transcriptPath: "transcript.json" }], broll: [], music: [],
    sourceSetAdmission: { schemaVersion: 1, receiptPath, receiptSha256, sourceSetDigest: "a".repeat(64), entryCount: 1 } };
  writeFileSync(path.join(source, "asset_manifest.json"), JSON.stringify(manifest));
  return { directory, producerDir, plan, intent, transcript, input: { producerDir, intent, repo: process.cwd() },
    cleanup: () => rmSync(directory, { recursive: true, force: true }) };
}

test("prepare is idempotent, carries whole-source search and makes no provider call", () => {
  const f = fixture();
  try {
    const result = prepareNativeShortRequest(f.input);
    assert.deepEqual(prepareNativeShortRequest(f.input), result);
    assert.equal(result.providerCalls, 0); assert.equal(result.sourceCount, 1);
    const packet = JSON.parse(readFileSync(path.join(result.directory, "SHORT-REQUEST.json"), "utf8"));
    assert.equal(packet.sources[0].visualInspection, "pending");
    assert.match(packet.sources[0].searchScope, /entire-admitted-source/);
    assert.match(result.handoff, /authorizes no new provider transmission/);
    assert.equal(packet.editorialInstructions, shortDirectionInstructions(result.request));
    assert.ok(result.handoff.includes(packet.editorialInstructions));
    assert.match(packet.editorialInstructions, /VISUAL EXPLANATION — shared directing standard v1/);
    assert.match(packet.editorialInstructions, /SHORT FORMAT ADAPTATION/);
    assert.match(packet.editorialInstructions, /SQ01 states a claim/);
    const pacingStage = packet.stages.indexOf("map-script-and-delivery-pacing");
    assert.ok(pacingStage > packet.stages.indexOf("select-retained-passage"));
    const representationStage = packet.stages.indexOf("choose-visual-representation");
    assert.ok(pacingStage < representationStage);
    assert.ok(representationStage < packet.stages.indexOf("plan-scenes-and-treatment"));
    assert.ok(representationStage < packet.stages.indexOf("scout-supporting-shots"));
    assert.ok(packet.stages.indexOf("scout-supporting-shots") < packet.stages.indexOf("plan-scenes-and-treatment"));
    assert.ok(packet.stages.indexOf("plan-scenes-and-treatment") < packet.stages.indexOf("check-full-plan-feasibility"));
    assert.ok(packet.stages.indexOf("check-full-plan-feasibility") < packet.stages.indexOf("independent-current-plan-review"));
    assert.ok(packet.stages.indexOf("independent-current-plan-review") < packet.stages.indexOf("assemble"));
    assert.match(result.handoff, /opening-only Director critique do not satisfy/);
    assert.match(result.handoff, /visual-plan-usage\.ts register/);
    assert.ok(packet.references.length >= 2);
    writeFileSync(f.plan.assets[0].path, "changed source");
    assert.throws(() => prepareNativeShortRequest(f.input), /changed since ingest/);
  } finally { f.cleanup(); }
});

test("prepare rejects related-output allocation without its selected vocabulary", () => {
  const f = fixture(), context = path.join(f.directory, "related-style-context.json");
  const choice = { choiceKind: "vocabulary", choiceId: "scene-0-comparison", sceneIndex: 0,
    familyId: "comparison", contenderRef: "mirror:meter-card",
    anatomy: "TEST split comparison with one result accent",
    configuration: "TEST split comparison", development: "TEST baseline then result" };
  const record = { schemaVersion: 1, scope: "related-native-short-style-context",
    groupId: "launch-set", currentOutputId: "short-two", referenceId: "reference-one",
    vocabularySha256: "a".repeat(64), planningMode: "shared-allocation",
    outputs: [{ outputId: "short-one", status: "planned", choices: [choice] },
      { outputId: "short-two", status: "planned", choices: [{ ...choice,
        choiceId: "scene-0-callout",
        contenderRef: "mirror:callout-card", configuration: "TEST centered callout",
        development: "TEST claim then evidence" }] }], limitations: [] };
  writeFileSync(context, JSON.stringify(record));
  try {
    assert.throws(() => prepareNativeShortRequest({ ...f.input, relatedStyleContextPath: context }),
      /requires a current selected reference vocabulary/);
    record.outputs.pop(); writeFileSync(context, JSON.stringify(record));
    assert.throws(() => prepareNativeShortRequest({ ...f.input, relatedStyleContextPath: context }), /current output conflicts/);
  } finally { f.cleanup(); }
});

test("requested cleanup reaches the saved project and cold reader without substitution", () => {
  const f = fixture();
  try {
    const intent = { ...f.intent, audioEnhance: { preset: "voice" as const } };
    const result = prepareNativeShortRequest({ ...f.input, intent });
    const packet = path.join(result.directory, "SHORT-REQUEST.json");
    f.plan.requestPacket = { path: packet, sha256: fileSha256(packet)! };
    bindNativeVisualPlanFixture(f.plan, f.directory);
    refreshVisualSourceFixture(f.plan);
    refreshNativeAssetUseFixture(f.plan);
    refreshNativePrebuildReviewFixture(f.plan);
    const destination = path.join(f.directory, "assembled-with-cleanup");
    assert.throws(() => writeNativeShortProject(f.plan, destination), /cleanup cannot be omitted/);
    f.plan.audioFinishing = { schemaVersion: 1, rationale: "Reduce the recording's steady fan noise.",
      audioEnhance: { preset: "voice-strong" } };
    refreshNativePrebuildReviewFixture(f.plan);
    assert.throws(() => writeNativeShortProject(f.plan, destination), /substituted/);
    f.plan.audioFinishing.audioEnhance = { preset: "voice" };
    refreshNativePrebuildReviewFixture(f.plan);
    writeNativeShortProject(f.plan, destination);
    assert.deepEqual(readNativeShortProject(destination).audioFinishing, f.plan.audioFinishing);
  } finally { f.cleanup(); }
});

test("prepared request binds the real writer and cold reader to style and transcript", () => {
  const f = fixture();
  try {
    const result = prepareNativeShortRequest(f.input), packet = path.join(result.directory, "SHORT-REQUEST.json");
    f.plan.requestPacket = { path: packet, sha256: fileSha256(packet)! };
    bindNativeVisualPlanFixture(f.plan, f.directory);
    assert.throws(() => assertNativeVisualSources(f.plan), /current request packet/);
    refreshVisualSourceFixture(f.plan);
    assert.deepEqual(f.plan.visualSources!.request, f.plan.requestPacket);
    refreshNativeAssetUseFixture(f.plan);
    refreshNativePrebuildReviewFixture(f.plan);
    const project = writeNativeShortProject(f.plan, path.join(f.directory, "assembled"));
    assert.deepEqual(readNativeShortProject(project.directory), f.plan);
    const instructions = JSON.parse(readFileSync(packet, "utf8")).editorialInstructions;
    assert.ok(readFileSync(path.join(project.directory, "BRIEF.md"), "utf8").includes(instructions));
    const changed = structuredClone(f.plan); changed.request = { selection: "requested", request: "module", supportingVideo: "source-first" };
    refreshNativePrebuildReviewFixture(changed);
    assert.throws(() => writeNativeShortProject(changed, path.join(f.directory, "substituted")), /prepared style request/);
    writeFileSync(f.transcript, "changed transcript");
    assert.throws(() => readNativeShortProject(project.directory), /transcript changed/);
  } finally { f.cleanup(); }
});

test("HTTP uses stored intent and rejects cross-origin requests and outside projects", async () => {
  const f = fixture(), previous = process.env.SNIPER_WORKSPACE_ROOT;
  process.env.SNIPER_WORKSPACE_ROOT = f.directory;
  const request = (dir: string, origin = "http://127.0.0.1:3000") => new NextRequest("http://127.0.0.1:3000/api/producer/native-short", {
    method: "POST", headers: { host: "127.0.0.1:3000", origin, "content-type": "application/json" }, body: JSON.stringify({ dir }) });
  try {
    const response = await POST(request(f.producerDir));
    const packet = await response.json(); assert.equal(response.status, 200, JSON.stringify(packet));
    assert.deepEqual(packet.request, f.intent.shortDirection); assert.equal(packet.providerCalls, 0);
    assert.equal((await POST(request(f.producerDir, "https://unrelated.example"))).status, 403);
    assert.equal((await POST(request(os.tmpdir()))).status, 400);
  } finally {
    if (previous === undefined) delete process.env.SNIPER_WORKSPACE_ROOT; else process.env.SNIPER_WORKSPACE_ROOT = previous;
    f.cleanup();
  }
});

test("native assembly cannot silently discard requested audio work or override disabled captions", () => {
  const f = fixture();
  try {
    for (const extra of [{ music: true }, { lanes: { captions: "off" } }]) {
      const result = prepareNativeShortRequest({ ...f.input, intent: { ...f.intent, ...extra } });
      const packet = path.join(result.directory, "SHORT-REQUEST.json");
      f.plan.requestPacket = { path: packet, sha256: fileSha256(packet)! };
      bindNativeVisualPlanFixture(f.plan, f.directory);
      refreshVisualSourceFixture(f.plan);
      refreshNativeAssetUseFixture(f.plan);
      refreshNativePrebuildReviewFixture(f.plan);
      assert.throws(() => writeNativeShortProject(f.plan, path.join(f.directory, "blocked")), /requested music|lane ownership/);
    }
  } finally { f.cleanup(); }
});

function suppliedPicture(f: ReturnType<typeof fixture>, include = true) {
  const source = path.dirname(f.plan.assets[0].path), file = path.join(source, "supplied.png");
  writeFileSync(file, "TEST supplied image; no render or image inspection");
  const sha256 = fileSha256(file)!;
  const asset = { file: "assets/supplied.png", path: file, sha256, role: "image" as const };
  if (include) {
    const manifestFile = path.join(source, "asset_manifest.json"), manifest = JSON.parse(readFileSync(manifestFile, "utf8"));
    manifest.broll.push({ id: "provided-picture", path: file, sourceSha256: sha256 });
    writeFileSync(manifestFile, JSON.stringify(manifest));
  }
  f.plan.assets.push(asset);
  f.plan.extension = { css: "", motion: "", markup: `<img id="provided-picture" class="clip" src="${asset.file}" data-start="0" data-duration="2">` };
  f.plan.request.mediaPolicy = { placement: "auto", sources: "provided-only" };
  refreshNativePacingFixture(f.plan);
  return asset;
}

function admittedExternal(f: ReturnType<typeof fixture>) {
  const source = path.dirname(f.plan.assets[0].path);
  const original = path.join(source, "external-original.mp4");
  const snapshot = path.join(source, "external-snapshot.media");
  const receipt = path.join(source, "external-admission.json");
  writeFileSync(original, "TEST original external media");
  writeFileSync(snapshot, "TEST admitted external snapshot");
  writeFileSync(receipt, "TEST external admission receipt");
  const manifestFile = path.join(source, "asset_manifest.json");
  const manifest = JSON.parse(readFileSync(manifestFile, "utf8"));
  manifest.externalMedia = [{ id: "external-1", path: snapshot,
    originalPath: original, sourceSha256: fileSha256(snapshot)!,
    sourceSizeBytes: readFileSync(snapshot).byteLength,
    admissionReceiptPath: receipt, admissionReceiptSha256: fileSha256(receipt)! }];
  writeFileSync(manifestFile, JSON.stringify(manifest));
  return { original, snapshot, receipt };
}

function bindPrepared(f: ReturnType<typeof fixture>) {
  const result = prepareNativeShortRequest(f.input), packet = path.join(result.directory, "SHORT-REQUEST.json");
  f.plan.requestPacket = { path: packet, sha256: fileSha256(packet)! };
  bindNativeVisualPlanFixture(f.plan, f.directory);
  refreshVisualSourceFixture(f.plan);
  refreshNativeAssetUseFixture(f.plan);
  refreshNativePrebuildReviewFixture(f.plan);
  return JSON.parse(readFileSync(packet, "utf8"));
}

test("provided picture policy and hashes survive preparation, v3 writer and cold read", () => {
  const f = fixture();
  try {
    const picture = suppliedPicture(f), packet = bindPrepared(f);
    assert.equal(packet.availableSupportingAssets[0].sha256, picture.sha256);
    assert.equal(packet.availableSupportingAssets[0].visualInspection, "pending");
    assert.deepEqual(packet.intent.shortDirection.mediaPolicy, { placement: "auto", sources: "provided-only" });
    const { directory } = writeNativeShortProject(f.plan, path.join(f.directory, "supplied-project"));
    assert.deepEqual(readNativeShortProject(directory), f.plan);
    writeFileSync(picture.path, "TEST changed supplied image after preparation");
    assert.throws(() => readNativeShortProject(directory),
      /missing, changed|changed|Asset origin record differs from the frozen asset identity/);
    assert.throws(() => prepareNativeShortRequest(f.input), /B-roll changed since ingest/);
  } finally { f.cleanup(); }
});

test("unselected prepared B-roll bytes are still checked at cold read", () => {
  const f = fixture();
  try {
    const picture = suppliedPicture(f);
    f.plan.assets.pop(); f.plan.extension = undefined; refreshNativePacingFixture(f.plan);
    bindPrepared(f);
    const { directory } = writeNativeShortProject(f.plan, path.join(f.directory, "unselected-project"));
    writeFileSync(picture.path, "TEST changed unselected supplied image");
    assert.throws(() => readNativeShortProject(directory), /Prepared supplied B-roll changed/);
  } finally { f.cleanup(); }
});

test("external media stays a pinned prerequisite and is rechecked without becoming supplied B-roll", () => {
  const f = fixture();
  try {
    const external = admittedExternal(f), packet = bindPrepared(f);
    assert.equal(packet.availableSupportingAssets.length, 0);
    assert.equal(packet.availableExternalMedia.length, 1);
    assert.equal(packet.availableExternalMedia[0].path, external.snapshot);
    assert.equal(packet.availableExternalMedia[0].originalPath, external.original);
    assert.equal(packet.availableExternalMedia[0].modality, "external-media");
    assert.equal(packet.availableExternalMedia[0].recordId, "external-1");
    assert.equal(packet.availableExternalMedia[0].sourceSetLane, "external");
    assert.equal(packet.availableExternalMedia[0].sourceSetEvidence.sha256,
      packet.availableExternalMedia[0].admissionReceiptSha256);
    assert.equal(packet.availableExternalMedia[0].authorizationEvidence, null);
    assert.equal(packet.availableExternalMedia[0].availability,
      "prerequisite-awaiting-controller-authorization");
    assert.equal(packet.availableExternalMedia[0].admissionReceipt.path, external.receipt);
    const { directory } = writeNativeShortProject(f.plan, path.join(f.directory, "external-project"));
    writeFileSync(external.snapshot, "TEST changed admitted external snapshot");
    assert.throws(() => readNativeShortProject(directory),
      /external-media inventory changed/);
    writeFileSync(external.snapshot, "TEST admitted external snapshot");
    writeFileSync(external.receipt, "TEST changed external admission receipt");
    assert.throws(() => readNativeShortProject(directory),
      /external-media admission receipt changed/);
  } finally { f.cleanup(); }
});

test("labeling an unlisted image as provided cannot broaden a prepared request", () => {
  const f = fixture();
  try {
    suppliedPicture(f, false); bindPrepared(f);
    assert.throws(() => writeNativeShortProject(f.plan, path.join(f.directory, "unlisted")), /absent from the prepared request inventory/);
    f.plan.strategy.assetUse!.policy = { placement: "auto", sources: "public-web" };
    refreshNativePrebuildReviewFixture(f.plan);
    assert.throws(() => writeNativeShortProject(f.plan, path.join(f.directory, "broadened")), /cannot broaden the requested media policy/);
  } finally { f.cleanup(); }
});
