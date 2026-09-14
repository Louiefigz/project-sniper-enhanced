import assert from "node:assert/strict";
import {
  INTENT_CAPABILITY_CODES,
  eligibleBrollAssets,
  reconcileIntentCapabilities,
} from "../intent-capabilities";
import { resolveLanes, type ProjectIntent } from "../intent-presets";
import type { ShortDirectionRequest } from "../short-direction";
import type { AssetManifest } from "../types";

const manifest = (broll: AssetManifest["broll"]): Pick<AssetManifest, "broll"> => ({ broll });

const produced: ProjectIntent = {
  mode: "longform",
  scope: "produced",
  lanes: {},
  preset: "longform-produced",
};

const nativeShort: ProjectIntent = {
  ...produced, mode: "short", preset: "produced-short",
  shortDirection: { selection: "auto", supportingVideo: "source-first" },
};

function assertScoutingPreserved(shortDirection: ShortDirectionRequest): void {
  const intent = { ...nativeShort, shortDirection }, before = structuredClone(intent);
  const result = reconcileIntentCapabilities(intent, manifest([]));
  assert.equal(result.ok, true);
  assert.deepEqual(result.requestedIntent, before);
  assert.deepEqual(result.resolvedIntent, before);
  assert.deepEqual(result.decisions, []);
  assert.deepEqual(intent, before, "scouting must not mutate source policy or request");
}

// Source footage itself can contain useful cutaways, including provided-only jobs.
assertScoutingPreserved(nativeShort.shortDirection!);
for (const sources of ["provided-only", "local-only", "public-web"] as const) {
  assertScoutingPreserved({ selection: "auto", supportingVideo: "source-first",
    mediaPolicy: { placement: "auto", sources } });
  assertScoutingPreserved({ selection: "requested", request: "Show the actual website",
    supportingVideo: "source-first", mediaPolicy: { placement: "auto", sources } });
}

for (const broll of ["off", "operator"] as const) {
  const intent = { ...nativeShort, lanes: { broll } };
  const result = reconcileIntentCapabilities(intent, manifest([]));
  assert.deepEqual(result.resolvedIntent, intent);
  assert.deepEqual(result.decisions, []);
}

for (const shortDirection of [
  { selection: "auto", supportingVideo: "off" },
  { selection: "auto", supportingVideo: "source-first",
    mediaPolicy: { placement: "off", sources: "public-web" } },
] satisfies ShortDirectionRequest[]) {
  const intent = { ...nativeShort, shortDirection };
  const result = reconcileIntentCapabilities(intent, manifest([]));
  assert.equal(result.resolvedIntent?.lanes.broll, "off");
  assert.deepEqual(result.resolvedIntent?.shortDirection, shortDirection);
  assert.equal(result.decisions[0].code, INTENT_CAPABILITY_CODES.BROLL_UNAVAILABLE_RESOLVED);
}

for (const scope of ["trim", "light"] as const) {
  const intent = { ...nativeShort, scope, lanes: { broll: "auto" as const } };
  const result = reconcileIntentCapabilities(intent, manifest([]));
  assert.deepEqual(result.resolvedIntent, intent, "scouting cannot activate a scope-disabled lane");
  assert.equal(resolveLanes(result.resolvedIntent!.scope, result.resolvedIntent!.lanes).broll, "off");
  assert.deepEqual(result.decisions, []);
}

{
  const before = structuredClone(produced);
  const result = reconcileIntentCapabilities(produced, manifest([]));
  assert.equal(result.ok, true);
  assert.deepEqual(result.requestedIntent, before);
  assert.deepEqual(produced, before, "reconciliation must not mutate requested intent");
  assert.deepEqual(result.resolvedIntent?.lanes, { broll: "off" });
  assert.equal(result.resolvedIntent?.preset, "custom");
  assert.equal(result.decisions[0].code, INTENT_CAPABILITY_CODES.BROLL_UNAVAILABLE_RESOLVED);
  assert.equal(result.decisions[0].status, "resolved");
  assert.match(result.decisions[0].message, /Text cards, graphics, captions, and motion remain enabled/);
}

{
  const result = reconcileIntentCapabilities(produced, manifest([
    { id: "broll-1", path: "/project/broll/example.mp4" },
  ]));
  assert.equal(result.ok, true);
  assert.deepEqual(result.resolvedIntent, produced);
  assert.deepEqual(result.decisions, []);
}

{
  const explicitOff: ProjectIntent = { ...produced, lanes: { broll: "off" } };
  const result = reconcileIntentCapabilities(explicitOff, manifest([]));
  assert.equal(result.ok, true);
  assert.deepEqual(result.resolvedIntent, explicitOff);
  assert.deepEqual(result.decisions, []);
}

{
  const full: ProjectIntent = { ...produced, scope: "full", preset: "custom" };
  const result = reconcileIntentCapabilities(full, manifest([]));
  assert.equal(result.ok, true);
  assert.equal(result.resolvedIntent?.lanes.broll, "off");
  assert.equal(result.decisions[0].code, INTENT_CAPABILITY_CODES.BROLL_UNAVAILABLE_RESOLVED);
  assert.match(result.decisions[0].message, /rest of the Full edit remains enabled/);
}

{
  const fullOff: ProjectIntent = {
    ...produced,
    scope: "full",
    lanes: { broll: "off" },
    preset: "custom",
  };
  const result = reconcileIntentCapabilities(fullOff, manifest([]));
  assert.equal(result.ok, true);
  assert.deepEqual(result.resolvedIntent, fullOff);
}

{
  const mimic: ProjectIntent = {
    ...produced,
    mode: "short",
    reference: {
      id: "ref-1",
      title: "Measured reference",
      mode: "short",
      strategy: "mimic",
    },
  };
  const result = reconcileIntentCapabilities(mimic, manifest([]));
  assert.equal(result.ok, true);
  assert.equal(result.resolvedIntent?.lanes.broll, "off");
  assert.match(result.decisions[0].message, /cutaway pattern cannot be matched exactly/);
}

{
  const malformed = manifest([
    { id: "", path: "/project/broll/a.mp4" },
    { id: "broll-2" },
  ]);
  assert.deepEqual(eligibleBrollAssets(malformed), []);
  assert.equal(reconcileIntentCapabilities(produced, malformed).decisions.length, 1);
}

console.log("intent-capabilities.test.ts: all assertions passed");
