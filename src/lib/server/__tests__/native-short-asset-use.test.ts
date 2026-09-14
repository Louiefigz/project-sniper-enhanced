import assert from "node:assert/strict";
import { test } from "node:test";
import { assertNativeShortAssetUse, nativeShortAssetUseReport } from "../native-short-asset-use";
import { withAssetUse } from "./_native-short-asset-use-fixture";

const check = (f: Parameters<Parameters<typeof withAssetUse>[0]>[0]) => assertNativeShortAssetUse(f.input, f.html(), f.options);

test("explicit no-insert and still-image decisions retain unresolved review disposition", () => withAssetUse(f => {
  check(f);
  const asset = f.addMedia(); check(f);
  const report = nativeShortAssetUseReport(f.input, f.html(), f.options);
  assert.equal(report.semanticReview, "not-established-by-structural-checks");
  assert.equal(report.publicationAdmission, "not-performed-local-review-only");
  assert.equal(report.assets.find(row => row.file === asset.file)!.record.publicationDisposition, "needs-review");
  assert.equal(report.originEvidenceFiles.length, 2);
}));

test("stale words, cuts, layout, source origin and request cannot reuse earlier decisions", () => withAssetUse(f => {
  const html = f.html();
  const revisions = [() => { f.input.canvas.occurrences[0][5] = "Changed"; },
    () => { f.input.canvas.cuts[0].start = .1; }, () => { f.input.canvas.captionViews[0].box[1] += 1; },
    () => { f.input.assets[0].origin!.sha256 = "b".repeat(64); },
    () => { f.input.request = { selection: "requested", request: "TEST changed intent", supportingVideo: "off" }; }];
  for (const change of revisions) { const saved = structuredClone(f.input); change();
    assert.throws(() => assertNativeShortAssetUse(f.input, html, f.options), /stale/); Object.assign(f.input, saved); }
}));

test("no-insert is bound to exact speech even when revision hash is freshly authored", () => withAssetUse(f => {
  const decision = f.input.strategy.assetUse!.decisions[0];
  decision.speech.occurrenceIds = [0]; assert.throws(() => check(f), /exact retained speech/);
  decision.speech.occurrenceIds = [0, 1]; decision.speech.text = "TEST rewritten summary";
  assert.throws(() => check(f), /exact retained speech/);
  decision.speech.text = "Test words."; decision.speech.startFrame = 45;
  assert.throws(() => check(f), /exact retained speech/);
}));

test("style references cannot become depicted people and placement restrictions cover images", () => withAssetUse(f => {
  f.addMedia(); const decision = f.input.strategy.assetUse!.decisions[0];
  decision.entity = { name: "TEST style creator", role: "style-reference", canonicalIdentity: "https://example.com/creator" };
  assert.throws(() => check(f), /style-only/);
  decision.entity.role = "subject"; decision.purpose = "style-direction";
  assert.throws(() => check(f), /style-only/);
  decision.purpose = "identify"; f.options.expectedPolicy.placement = "off";
  assert.throws(() => check(f), /Disabled/);
}));

test("plan cannot broaden request policy, including after reauthoring its revision hash", () => withAssetUse(f => {
  f.addMedia(); f.input.strategy.assetUse!.policy = { placement: "auto", sources: "public-web" }; f.refresh();
  assert.throws(() => check(f), /cannot broaden/);
}));

test("every image/video target needs a matching source and output window", () => withAssetUse(f => {
  f.addMedia(); const selection = f.input.strategy.assetUse!.decisions[0].selection!;
  selection.endFrame = 49; assert.throws(() => check(f), /executable/);
  selection.endFrame = 50; selection.assetFile = "assets/unrelated.png";
  assert.throws(() => check(f), /executable/);
  selection.assetFile = f.input.assets.at(-1)!.file;
  f.input.strategy.assetUse!.decisions[0].decision = "no-insert";
  f.input.strategy.assetUse!.decisions[0].selection = null;
  assert.throws(() => check(f), /lacks a speech-bound/);
}));

test("CSS backgrounds, posters and unbound source-file cutaways cannot evade asset decisions", () => withAssetUse(f => {
  const source = f.input.canvas.sourceFile;
  f.input.extension = { markup: "", motion: "", css: `<style>.extra{background:url('${source}')}</style>` }; f.refresh();
  assert.throws(() => check(f), /CSS image/);
  f.input.extension.css = "";
  f.input.extension.markup = `<video id="extra" class="clip" src="${source}" data-start="0" data-duration="2" muted></video>`;
  f.refresh(); assert.throws(() => check(f), /lacks a speech-bound/);
  f.input.extension.markup = f.input.extension.markup.replace('id="extra"', 'id="source-99-99"');
  f.refresh(); assert.throws(() => check(f), /lacks a speech-bound/);
  f.input.extension.markup = f.input.extension.markup.replace(' muted', ' poster="assets/image.png" muted');
  f.refresh(); assert.throws(() => check(f), /explicit local source/);
}));

test("mixed source frame rates preserve speed-1 ranges and audible excerpts fail explicitly", () => withAssetUse(f => {
  const asset = f.addMedia("video"), selection = f.input.strategy.assetUse!.decisions[0].selection!;
  const receipt = f.receipts.get(asset.file)!; receipt.record.media.durationFrames = 60; receipt.acquisition.sourceFrameRate = "30000/1001";
  f.saveOrigin(asset); f.refresh(); selection.sourceRange!.frameRate = "30000/1001"; check(f);
  selection.sourceRange!.endSeconds = 3; assert.throws(() => check(f), /speed-1/);
  selection.sourceRange!.endSeconds = 2;
  Object.assign(selection, { audio: "audible-quote" }); assert.throws(() => check(f), /audible quotes need/);
}));

test("essential regions and required attribution remain explicit without declaring readability", () => withAssetUse(f => {
  const asset = f.addMedia(), receipt = f.receipts.get(asset.file)!;
  const selection = f.input.strategy.assetUse!.decisions[0].selection!;
  selection.essentialRegion = [1000, 0, 100, 100]; assert.throws(() => check(f), /essential region/);
  selection.essentialRegion = [0, 0, 100, 100];
  receipt.record.rights.attributionRequired = true; receipt.record.rights.attribution = "TEST source credit";
  f.saveOrigin(asset); f.refresh(); assert.throws(() => check(f), /required source attribution/);
  selection.attribution = { text: "TEST source credit", placement: "TEST planned description credit" }; check(f);
  const report = nativeShortAssetUseReport(f.input, f.html(), f.options);
  assert.ok(report.reviewRequired.some(row => row.includes("essential regions")));
}));

test("legacy absence is cold-readable but required plans and forged verification flags fail", () => withAssetUse(f => {
  Object.assign(f.input.strategy.assetUse!.decisions[0].inspection, { verified: true });
  assert.throws(() => check(f), /unsupported fields.*verified/);
  delete f.input.strategy.assetUse;
  assert.doesNotThrow(() => assertNativeShortAssetUse(f.input, f.html(), { ...f.options, required: false }));
  assert.throws(() => check(f), /require a speech-bound/);
}));

test("runtime role and font filenames cannot disguise a CSS image insert", () => withAssetUse(f => {
  const asset = f.addMedia(); asset.role = "runtime";
  f.input.extension!.markup = "";
  const decision = f.input.strategy.assetUse!.decisions[0]; decision.decision = "no-insert"; decision.selection = null;
  f.input.extension!.css = `<style>.untracked{background:url('${asset.file}')}</style>`;
  f.refresh(); assert.throws(() => check(f), /CSS image sources/);
  f.input.extension!.css = '<style>.untracked{background:url("assets/Inter-Bold.ttf")}</style>';
  f.refresh(); assert.throws(() => check(f), /CSS image sources/);
  f.input.extension!.css = `<style>@font-face{font-family:Forged;src:url('${asset.file}')}</style>`;
  f.refresh(); assert.throws(() => check(f), /actual shared font/);
  f.input.extension!.css = '<style>@font-face{font-family:Inter;src:url("assets/Inter-Bold.ttf") format("truetype")}</style>';
  f.refresh(); check(f);
}));

test("native inserts reject playback-start and playback-rate aliases even if declared timing matches", () => withAssetUse(f => {
  f.addMedia("video");
  const markup = f.input.extension!.markup;
  for (const alias of ['data-playback-start="1"', 'data-playback-rate="2"', 'data-playback-rate="1"']) {
    f.input.extension!.markup = markup.replace(' muted', ` ${alias} muted`); f.refresh();
    assert.throws(() => check(f), /cannot override.*playback aliases/);
  }
}));

test("encoded CSS and imported styles cannot display assets while placement is off", () => withAssetUse(f => {
  const asset = f.addMedia();
  const decision = f.input.strategy.assetUse!.decisions[0]; decision.decision = "no-insert"; decision.selection = null;
  f.options.expectedPolicy.placement = "off";
  const styles = [
    `<style>.extra{background:u\\72l('${asset.file}')}</style>`,
    `<div style="background:u&#114;l('${asset.file}')"></div>`,
    `<div style='background:u\\72l("${asset.file}")'></div>`,
    `<div style=background:u\\72l(${asset.file})></div>`,
    '<style>@import "assets/extra.css";</style>',
    '<link rel="stylesheet" href="assets/extra.css">',
  ];
  for (const markup of styles) {
    f.input.extension = { markup, css: "", motion: "" }; f.refresh();
    assert.throws(() => check(f), /literal style syntax|additional stylesheets/);
  }
}));

test("non-scalar source policy cannot bypass origin restrictions", () => withAssetUse(f => {
  const asset = f.addMedia(); f.makePublic(asset);
  Object.assign(f.options.expectedPolicy, { sources: ["provided-only"] });
  assert.throws(() => check(f), /scalar supported media policy/);
}));
