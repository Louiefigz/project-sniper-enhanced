import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  assertIntentMatches,
  authoritativeAutoEditIntent,
  reconcileStoredIntentCapabilities,
} from "../../../app/api/producer/auto-edit/operator-intent-authority";
import { readProjectJson } from "../../../app/api/_lib/workspace";
import type { ProjectIntent } from "../intent-presets";

const stored: ProjectIntent = {
  mode: "longform",
  scope: "produced",
  lanes: { broll: "off" },
  brief: "Keep the three proof points.",
  music: false,
  audioEnhance: { preset: "voice" },
  preset: "longform-produced",
};

assert.doesNotThrow(() => assertIntentMatches(stored, { ...stored, preset: undefined }));
assert.throws(
  () => assertIntentMatches(stored, { ...stored, scope: "light" }),
  /scope/,
);
assert.throws(
  () => assertIntentMatches(stored, { ...stored, lanes: {} }),
  /lanes/,
);
assert.throws(
  () => assertIntentMatches(stored, { ...stored, mode: "short" }),
  /mode/,
);

const allFields: ProjectIntent = {
  ...stored,
  pace: "jadenly",
  style: "jadenly",
  reference: {
    id: "reference-1",
    title: "Measured reference",
    mode: "longform",
    strategy: "extend",
    targetStyle: "jadenly",
  },
};
const fieldMutations: Array<[keyof ProjectIntent, unknown]> = [
  ["brief", "Different direction"],
  ["pace", "caleb"],
  ["style", "caleb"],
  ["reference", { ...allFields.reference, id: "reference-2" }],
  ["music", true],
  ["audioEnhance", { preset: "voice-rnn" }],
];
for (const [field, value] of fieldMutations) {
  const changed = { ...allFields, [field]: value } as ProjectIntent;
  assert.throws(
    () => assertIntentMatches(allFields, changed),
    new RegExp(String(field)),
    `launch mismatch for ${field} must fail closed`,
  );
}

const root = mkdtempSync(path.join(os.tmpdir(), "sniper-intent-authority-"));
const producer = path.join(root, "producer");
const manifestPath = path.join(root, "asset_manifest.json");
mkdirSync(producer);
writeFileSync(manifestPath, JSON.stringify({ sources: [], broll: [] }));
writeFileSync(path.join(root, "project.json"), JSON.stringify({
  origin: "raw",
  history: [],
  intent: stored,
}));
try {
  assert.deepEqual(reconcileStoredIntentCapabilities(producer, stored, manifestPath), stored);
  const legacyProduced = { ...stored, lanes: {} };
  assert.equal(
    reconcileStoredIntentCapabilities(producer, legacyProduced, manifestPath).lanes.broll,
    "off",
  );
  let migrated = readProjectJson(root)!;
  assert.deepEqual(migrated.requestedIntent?.lanes, {});
  assert.equal(migrated.resolvedIntent?.lanes.broll, "off");
  assert.equal(migrated.intentDecisions?.[0].status, "resolved");
  const legacyFull = { ...stored, scope: "full" as const, lanes: {} };
  assert.equal(
    reconcileStoredIntentCapabilities(producer, legacyFull, manifestPath).lanes.broll,
    "off",
  );
  migrated = readProjectJson(root)!;
  assert.equal(migrated.requestedIntent?.scope, "full");
  assert.match(migrated.intentDecisions?.[0].message ?? "", /rest of the Full edit remains enabled/);
  writeFileSync(path.join(root, "project.json"), JSON.stringify({
    origin: "raw", history: [], intent: legacyProduced,
  }));
  assert.deepEqual(authoritativeAutoEditIntent(producer, {
    dir: producer,
    mode: legacyProduced.mode,
    scope: legacyProduced.scope,
    lanes: { broll: "off" },
    brief: legacyProduced.brief,
    music: legacyProduced.music,
    audioEnhance: legacyProduced.audioEnhance,
  }, manifestPath).lanes, {}, "project-card effective intent may launch a legacy request");
  writeFileSync(path.join(root, "project.json"), JSON.stringify({
    origin: "raw", history: [], intent: stored,
  }));
  assert.equal(authoritativeAutoEditIntent(producer, {
    dir: producer,
    mode: stored.mode,
    scope: stored.scope,
    lanes: stored.lanes,
    brief: stored.brief,
    music: stored.music,
    audioEnhance: stored.audioEnhance,
  }).scope, "produced");
  assert.throws(
    () => authoritativeAutoEditIntent(producer, {
      mode: "longform", scope: "light", lanes: { broll: "off" },
      brief: stored.brief, music: false, audioEnhance: stored.audioEnhance,
    }),
    /differs from stored operator intent: scope/,
  );
  writeFileSync(path.join(root, "project.json"), JSON.stringify({ origin: "raw", history: [] }));
  assert.throws(() => authoritativeAutoEditIntent(producer, {}), /no stored edit intent/);
} finally {
  rmSync(root, { recursive: true, force: true });
}

console.log("operator-intent-authority.test.ts: all assertions passed");
