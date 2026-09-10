import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { objectValue } from "@/lib/producer/contracts/validation";
import { SOURCE_COLOR_V2_PROFILE } from "@/lib/producer/contracts/guided-source-color-v1";
import { sourceColorExpectations } from "../guided-source-color-expectations";
import { mutateOwned, sourceColorFixture, testSha } from "./_guided-source-color-expectations-fixture";

test("metadata-only expectations preserve first-kept order, explicit mixed profiles and original raw parents", t => {
  const f = sourceColorFixture(t), held = sourceColorExpectations(f.context);
  assert.equal(held.scope, "held-source-color-expectations-not-source-observation-or-approval");
  assert.deepEqual(held.sources.map(row => [row.sourceId, row.frameCount, row.profile]), [
    ["raw-b", 48, SOURCE_COLOR_V2_PROFILE], ["raw-a", 24, null],
  ]);
  for (const row of held.sources) assert.equal(fs.existsSync(row.sourcePath), false);
  assert.equal(fs.existsSync(path.join(f.context.producerDir, ".sniper-grade-observations")), false);
  assert.equal(held.files.length, 21); assert(f.calls() > held.files.length);
  const parent = path.join(f.context.producerDir, "edit_plan.json");
  assert.equal(held.parents.planSha256, testSha(fs.readFileSync(parent)));
  assert.equal(held.parents.manifestSha256, f.context.opening.documents.manifest.sha256);
  held.assertCurrent(); assert.equal(f.context.opening.sourceBytesObserved, false);
});

test("input path must be the same exact caller-provided original raw input", t => {
  const f = sourceColorFixture(t); f.context.inputPath = f.refs.authority.path;
  assert.throws(() => sourceColorExpectations(f.context), /references conflict|raw file SHA|projection differs/);
});

test("missing or extra explicit declarations reject before any original callback", t => {
  const f = sourceColorFixture(t); delete f.context.selection.declarations["raw-a"];
  assert.throws(() => sourceColorExpectations(f.context), /cover exactly/); assert.equal(f.calls(), 0);
  const extra = sourceColorFixture(t); extra.context.selection.declarations.extra = structuredClone(extra.context.selection.declarations["raw-a"]);
  extra.context.selection.declarations.extra.declaration.sourceId = "extra";
  assert.throws(() => sourceColorExpectations(extra.context), /cover exactly/); assert.equal(extra.calls(), 0);
});

test("candidate cut mutation and omitted profile are not silently repaired", t => {
  const f = sourceColorFixture(t); f.context.opening.documents.candidatePlan.value.cutTrack = [];
  assert.throws(() => sourceColorExpectations(f.context), /unchanged nonempty/);
  const other = sourceColorFixture(t); Reflect.deleteProperty(other.context.selection.declarations["raw-b"], "profile");
  assert.throws(() => sourceColorExpectations(other.context), /source color selection/); assert.equal(other.calls(), 0);
});

for (const value of [true, "48", 0, -1, 48.5, 24001, null]) {
  test(`declaredFrames ${JSON.stringify(value)} rejects without count inference`, t => {
    const f = sourceColorFixture(t, { receipt: row => { objectValue(objectValue(row.decoded, "decoded").facts, "facts").declaredFrames = value; } });
    assert.throws(() => sourceColorExpectations(f.context), /declared frame expectation/);
  });
}

test("missing declared frames cannot be reconstructed from duration or exact manifest rate", t => {
  const f = sourceColorFixture(t, { receipt: row => { delete objectValue(objectValue(row.decoded, "decoded").facts, "facts").declaredFrames; } });
  assert.throws(() => sourceColorExpectations(f.context), /admission facts/);
});

test("rehashed admission snapshot substitution still fails the source-set and manifest joins", t => {
  const f = sourceColorFixture(t, { receipt: row => { objectValue(row.snapshot, "snapshot").sha256 = testSha("TEST other snapshot"); } });
  assert.throws(() => sourceColorExpectations(f.context), /snapshot\/declaration expectation differs/);
});

test("rehashed wrong source lane is not accepted as a kept source", t => {
  const f = sourceColorFixture(t, { entry: row => { row.lane = "broll"; } });
  assert.throws(() => sourceColorExpectations(f.context), /admitted source lane/);
});

test("source bytes and snapshot paths must match every original metadata occurrence", t => {
  const f = sourceColorFixture(t, { entry: row => { row.sizeBytes = 1025; } });
  assert.throws(() => sourceColorExpectations(f.context), /snapshot expectation differ/);
  const other = sourceColorFixture(t, { entry: row => { row.snapshotPath = "/private/tmp/TEST-unselected.media"; } });
  assert.throws(() => sourceColorExpectations(other.context), /snapshot expectation differ/);
});

test("duplicate manifest IDs fail before metadata reads", t => {
  const f = sourceColorFixture(t, { manifest: row => { const sources = row.sources as unknown[]; sources.push(structuredClone(sources[1])); } });
  assert.throws(() => sourceColorExpectations(f.context), /missing or duplicated/); assert.equal(f.calls(), 0);
});

test("VFR and missing exact source rate are not inferred from other metadata", t => {
  const f = sourceColorFixture(t, { manifest: row => { objectValue((row.sources as unknown[])[1], "source").vfr = true; } });
  assert.throws(() => sourceColorExpectations(f.context), /non-VFR source rate/);
});

for (const value of ["48/2", "0/1", "24.0", "9007199254740992/1", "24/0", false,
  "120/1", "1/2", "9007199254740991/9007199254740989"]) {
  test(`malformed source rate ${JSON.stringify(value)} rejects before callbacks`, t => {
    const f = sourceColorFixture(t, { manifest: row => { objectValue((row.sources as unknown[])[1], "source").frameRate = value; } });
    assert.throws(() => sourceColorExpectations(f.context)); assert.equal(f.calls(), 0);
  });
}

test("existing exact integral rate strings remain metadata-compatible without normalization writes", t => {
  const f = sourceColorFixture(t, { manifest: row => { objectValue((row.sources as unknown[])[1], "source").frameRate = "24"; } });
  const original = structuredClone(f.context.opening.documents.manifest.value);
  sourceColorExpectations(f.context); assert.deepEqual(f.context.opening.documents.manifest.value, original);
});

for (const [key, value] of [["width", "1920"], ["width", 3842], ["height", 2162], ["height", 1079],
  ["audioStreams", true], ["streamCount", 1], ["durationSeconds", "2"]] as const) {
  test(`typed profile metadata rejects ${key}=${JSON.stringify(value)}`, t => {
    const f = sourceColorFixture(t, { receipt: row => { objectValue(objectValue(row.decoded, "decoded").facts, "facts")[key] = value; } });
    assert.throws(() => sourceColorExpectations(f.context), /Source color/);
  });
}

test("V2 exact full-source pixel boundary is permitted as an expectation only", t => {
  const f = sourceColorFixture(t, { receipt: row => { Object.assign(objectValue(objectValue(row.decoded, "decoded").facts, "facts"),
    { width: 3840, height: 2160, declaredFrames: 24000 }); } });
  f.context.selection.declarations["raw-b"].declaration.lightingGroups[0].endFrame = 24000;
  const held = sourceColorExpectations(f.context); assert.equal(held.sources[0].frameCount, 24000);
  assert.equal(fs.existsSync(held.sources[0].sourcePath), false);
});

test("V1 existing aggregate pixel limit rejects before any job creation", t => {
  const f = sourceColorFixture(t, { receipt: row => { Object.assign(objectValue(objectValue(row.decoded, "decoded").facts, "facts"),
    { width: 1920, height: 1080, declaredFrames: 18001 }); } });
  const selected = f.context.selection.declarations["raw-b"];
  selected.profile = null; Object.assign(selected.declaration, { schemaVersion: 1, sourceProfile: "bt709-sdr", historyState: "known" });
  selected.declaration.lightingGroups[0].endFrame = 18001;
  assert.throws(() => sourceColorExpectations(f.context), /pixel expectation exceeds/);
});

for (const count of [21600, 21601]) {
  test(`existing six-hour exact source boundary at ${count} frames/1 fps`, t => {
    const f = sourceColorFixture(t, {
      manifest: row => { objectValue((row.sources as unknown[])[1], "source").frameRate = "1/1"; },
      receipt: row => { Object.assign(objectValue(objectValue(row.decoded, "decoded").facts, "facts"),
        { width: 2, height: 2, declaredFrames: count }); },
    });
    f.context.selection.declarations["raw-b"].declaration.lightingGroups[0].endFrame = count;
    if (count === 21600) assert.equal(sourceColorExpectations(f.context).sources[0].frameCount, count);
    else assert.throws(() => sourceColorExpectations(f.context), /six-hour grade class/);
  });
}

test("declared lighting coverage must end at the retained admission expectation", t => {
  const f = sourceColorFixture(t); f.context.selection.declarations["raw-b"].declaration.lightingGroups[0].endFrame = 47;
  assert.throws(() => sourceColorExpectations(f.context), /snapshot\/declaration expectation differs/);
});

test("first callback cannot rebaseline the input, selected request or source metadata", t => {
  const f = sourceColorFixture(t);
  f.onGuard(() => { f.context.selection.declarations["raw-b"].declaration.cameraProfile = "TEST invented camera"; });
  assert.throws(() => sourceColorExpectations(f.context), /original context or metadata changed/);
  assert.equal(f.calls(), 1);
});

test("all receipt and parent refs are captured before the first callback", t => {
  const f = sourceColorFixture(t);
  f.onGuard(() => mutateOwned(f, f.setPath, `${fs.readFileSync(f.setPath, "utf8")} `));
  assert.throws(() => sourceColorExpectations(f.context), /held metadata file or parent changed/); assert.equal(f.calls(), 1);
});

test("changed original file bytes reject even when mutation occurred before the projector holds stats", t => {
  const f = sourceColorFixture(t); mutateOwned(f, f.setPath, `${fs.readFileSync(f.setPath, "utf8")} `);
  assert.throws(() => sourceColorExpectations(f.context), /original raw file SHA differs/);
});

test("unchanged original raw values cannot be silently replaced by edited in-memory documents", t => {
  const f = sourceColorFixture(t); f.context.opening.documents.readinessPacket.value.TEST = "TEST changed before hold";
  assert.throws(() => sourceColorExpectations(f.context), /original document projection differs/);
});

for (const field of ["sha256", "sizeBytes"] as const) {
  test(`original observer ${field} must equal its same-pass raw document reference`, t => {
    const f = sourceColorFixture(t), authority = f.context.opening.documents.authority;
    if (field === "sha256") authority.sha256 = "0".repeat(64);
    else authority.sizeBytes = 999999;
    assert.throws(() => sourceColorExpectations(f.context), /original document projection differs/);
  });
}

test("late assertCurrent catches receipt mutation and typed context drift", t => {
  const f = sourceColorFixture(t), held = sourceColorExpectations(f.context);
  mutateOwned(f, held.sources[0].admissionReceiptPath, "{}");
  assert.throws(() => held.assertCurrent(), /held metadata file or parent changed/);
  const other = sourceColorFixture(t), second = sourceColorExpectations(other.context);
  other.context.opening.documents.acceptedPlan.sizeBytes += 1;
  assert.throws(() => second.assertCurrent(), /original context or metadata changed/);
});

test("the final original callback and its failure remain mandatory without retries", t => {
  const baseline = sourceColorFixture(t); sourceColorExpectations(baseline.context); const count = baseline.calls();
  const f = sourceColorFixture(t), error = new Error("TEST original deadline expired at final check");
  f.onGuard(() => { if (f.calls() === count) throw error; });
  assert.throws(() => sourceColorExpectations(f.context), value => value === error); assert.equal(f.calls(), count);
});

test("returned data is detached/frozen and cannot replace the original callback", t => {
  const f = sourceColorFixture(t), held = sourceColorExpectations(f.context);
  assert(Object.isFrozen(held.sources[0].declaration.lightingGroups[0]));
  assert.equal(Reflect.set(held.sources[0], "frameCount", 49), false); assert.equal(held.sources[0].frameCount, 48);
  f.context.guard = () => undefined;
  assert.throws(() => held.assertCurrent(), /original context or metadata changed/);
});

test("symlink and hardlink receipt aliases reject before callbacks", t => {
  const f = sourceColorFixture(t), alias = path.join(f.root, "TEST-set-copy.json");
  fs.renameSync(f.setPath, alias); fs.symlinkSync(alias, f.setPath);
  assert.throws(() => sourceColorExpectations(f.context), /regular single-link/); assert.equal(f.calls(), 0);
  const other = sourceColorFixture(t); fs.linkSync(other.setPath, path.join(other.root, "TEST-hardlink.json"));
  assert.throws(() => sourceColorExpectations(other.context), /regular single-link/); assert.equal(other.calls(), 0);
});

test("the TEST fault helper refuses any external or aliased mutation target", t => {
  const f = sourceColorFixture(t), external = sourceColorFixture(t), file = external.refs.authority.path;
  const original = fs.readFileSync(file);
  assert.throws(() => mutateOwned(f, file, "TEST forbidden")); assert.deepEqual(fs.readFileSync(file), original);
});
