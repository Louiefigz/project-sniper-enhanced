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
import { nativeShortFixture, refreshNativePacingFixture, refreshNativePrebuildReviewFixture } from "./_native-short-project-fixture";
import { readNativeShortProject, writeNativeShortProject } from "../native-short-project";
import { POST } from "../../../app/api/producer/native-short/route";
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
    assert.match(packet.editorialInstructions, /CR07 develops problem/);
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
    assert.ok(packet.references.length >= 2);
    writeFileSync(f.plan.assets[0].path, "changed source");
    assert.throws(() => prepareNativeShortRequest(f.input), /changed since ingest/);
  } finally { f.cleanup(); }
});

test("requested cleanup reaches the saved project and cold reader without substitution", () => {
  const f = fixture();
  try {
    const intent = { ...f.intent, audioEnhance: { preset: "voice" as const } };
    const result = prepareNativeShortRequest({ ...f.input, intent });
    const packet = path.join(result.directory, "SHORT-REQUEST.json");
    f.plan.requestPacket = { path: packet, sha256: fileSha256(packet)! };
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
    refreshNativeAssetUseFixture(f.plan);
    refreshNativePrebuildReviewFixture(f.plan);
    const project = writeNativeShortProject(f.plan, path.join(f.directory, "assembled"));
    assert.deepEqual(readNativeShortProject(project.directory), f.plan);
    const instructions = JSON.parse(readFileSync(packet, "utf8")).editorialInstructions;
    assert.ok(readFileSync(path.join(project.directory, "BRIEF.md"), "utf8").includes(instructions));
    const changed = structuredClone(f.plan); changed.request = { selection: "requested", request: "Nate", supportingVideo: "source-first" };
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

function bindPrepared(f: ReturnType<typeof fixture>) {
  const result = prepareNativeShortRequest(f.input), packet = path.join(result.directory, "SHORT-REQUEST.json");
  f.plan.requestPacket = { path: packet, sha256: fileSha256(packet)! };
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
