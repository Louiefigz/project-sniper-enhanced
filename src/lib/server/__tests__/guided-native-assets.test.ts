/** Required V10 images use the shared v3 gates; source/rights/visual quality are not inferred. */
import assert from "node:assert/strict";
import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { canonicalJson, fileSha256 } from "../auto-edit-hash";
import { resolveGuidedNativeAssets } from "../guided-native-assets";
import { assembleNativeShortHtml, writeNativeShortProject } from "../native-short-project";
import type { NativeShortDirection } from "../guided-native-candidate";
import type { NativeAssetOriginReceipt } from "../native-short-asset-use-types";
import { guidedBindingFixture } from "./_guided-native-binding-fixture";

type Fixture = ReturnType<typeof guidedBindingFixture>;
function withFixture(run: (f: Fixture) => void): void {
  const f = guidedBindingFixture();
  try { run(f); } finally { f.cleanup(); }
}
function resolve(f: Fixture) {
  return resolveGuidedNativeAssets(f.input, { direction: f.proposal.result.candidate!.nativeDirection as NativeShortDirection,
    policy: f.proposal.evidence.nativeSupportingPolicy, mappings: f.mappings });
}
function originChange(f: Fixture, change: (origin: NativeAssetOriginReceipt) => void): void {
  const asset = f.input.assets.find(row => row.role === "image")!, origin = JSON.parse(readFileSync(asset.origin!.path, "utf8"));
  change(origin); writeFileSync(asset.origin!.path, canonicalJson(origin)); asset.origin!.sha256 = fileSha256(asset.origin!.path)!;
}

test("exact required image resolves to one existing v3 decision with source/inventory hashes", () => withFixture(f => {
  const result = resolve(f);
  assert.equal(result.length, 1); assert.equal(result[0].decisionId, "test-use-0");
  for (const hash of [result[0].decisionHash, result[0].inventoryHash, result[0].originHash]) assert.match(hash, /^[a-f0-9]{64}$/);
}));

test("missing, duplicate, unknown and wrong-scene resolutions remain unresolved", () => {
  for (const change of [(f: Fixture) => { f.mappings.length = 0; },
    (f: Fixture) => { f.mappings.push({ ...f.mappings[0] }); },
    (f: Fixture) => { f.mappings[0].assetId = "unknown"; },
    (f: Fixture) => { f.mappings[0].sceneId = "wrong-scene"; },
    (f: Fixture) => { f.mappings[0].decisionId = "unknown"; }]) {
    withFixture(f => { change(f); assert.throws(() => resolve(f), /coverage|invents|invent|existing insert/); });
  }
});

test("one decision cannot satisfy two asset requirements", () => withFixture(f => {
  const direction = f.proposal.result.candidate!.nativeDirection as NativeShortDirection;
  direction.assetRequirements!.push({ ...direction.assetRequirements![0], assetId: "another-image" });
  f.mappings.push({ ...f.mappings[0], assetId: "another-image" });
  assert.throws(() => resolve(f), /duplicates or invents/);
}));

test("no-insert and style-reference pixels cannot fulfill a required image", () => {
  for (const change of [(f: Fixture) => { f.input.strategy.assetUse!.decisions[0].decision = "no-insert"; },
    (f: Fixture) => { f.input.assets.find(row => row.role === "image")!.role = "reference"; },
    (f: Fixture) => { f.input.strategy.assetUse!.decisions[0].selection!.assetFile = f.input.assets[3].file; }]) {
    withFixture(f => { change(f); assert.throws(() => resolve(f), /no-insert|selected admitted source/); });
  }
});

test("public acquisition cannot masquerade as supplied even when request policy permits public web", () => withFixture(f => {
  originChange(f, origin => {
    origin.acquisition.kind = "public-download"; origin.acquisition.accessScope = "public";
    origin.record.origin = "reference-derived"; origin.record.provenance.source = "https://example.com/image.png";
  });
  f.input.request = { ...f.input.request, mediaPolicy: { placement: "auto", sources: "public-web" } };
  f.proposal.evidence.nativeSupportingPolicy!.policy.sources = "public-web";
  assert.throws(() => resolve(f), /admitted origin/);
}));

test("supplied path/hash, admission evidence, MIME and measured dimensions are binding", () => {
  const changes: Array<(f: Fixture) => void> = [f => { f.proposal.evidence.nativeSupportingPolicy!.assets[0].sha256 = "d".repeat(64); },
    f => { f.proposal.evidence.nativeSupportingPolicy!.assets[0].path = path.join(f.directory, "other.png"); },
    f => originChange(f, origin => { origin.acquisition.evidence = []; }),
    f => originChange(f, origin => { origin.record.mime = "image/jpeg"; }),
    f => originChange(f, origin => { origin.record.media.width = 2; })];
  for (const change of changes) withFixture(f => { change(f); assert.throws(() => resolve(f), /selected admitted source|admitted origin|mime/); });
});

test("speech quote, kept occurrence IDs, scene target and display range must match the requirement", () => {
  const changes: Array<(f: Fixture) => void> = [f => { f.input.strategy.assetUse!.decisions[0].speech.text = "TEST other quote"; },
    f => { f.input.strategy.assetUse!.decisions[0].speech.occurrenceIds = [1]; },
    f => { f.input.strategy.assetUse!.decisions[0].selection!.endFrame = 51; },
    f => { f.input.strategy.scenes[0].visibleIds = ["source-0-0"]; },
    f => { f.input.strategy.assetUse!.decisions[0].selection!.audio = "muted"; }];
  for (const change of changes) withFixture(f => { change(f); assert.throws(() => resolve(f), /scene, speech|absent|without source audio/); });
});

test("selected media cannot shrink the compiled reading hold or postpone it past the available interval", () => withFixture(f => {
  const hold = f.input.strategy.pacing!.holds.find(row => row.targetId === "show-image")!;
  hold.endFrame = 5;
  assert.throws(() => resolve(f), /actual reading hold/);
  hold.endFrame = 50;
  hold.startFrame = 30;
  assert.throws(() => resolve(f), /actual reading hold/);
}));

test("shared assembly still rejects invalid essential crop, empty claim and executable-window substitution", () => {
  const changes: Array<(f: Fixture) => void> = [f => { f.input.strategy.assetUse!.decisions[0].selection!.essentialRegion = [0, 0, 2, 1]; },
    f => { f.input.strategy.assetUse!.decisions[0].claimLimit = ""; },
    f => { f.input.strategy.assetUse!.decisions[0].selection!.startFrame = 1; }];
  for (const change of changes) withFixture(f => {
    change(f); f.bind();
    assert.throws(() => writeNativeShortProject(f.input, path.join(f.directory, "bad"), f.dependencies));
    assert.throws(() => assembleNativeShortHtml(f.input));
  });
});

test("off/operator policy and changed request sources cannot be overridden by a valid image decision", () => {
  for (const change of [(f: Fixture) => { f.proposal.evidence.nativeSupportingPolicy!.brollEnabled = false; },
    (f: Fixture) => { f.proposal.evidence.nativeSupportingPolicy!.policy.placement = "off"; },
    (f: Fixture) => { f.input.request = { ...f.input.request, mediaPolicy: { placement: "auto", sources: "public-web" } }; }]) {
    withFixture(f => { change(f); assert.throws(() => resolve(f), /ownership|disabled|media policy/); });
  }
});
