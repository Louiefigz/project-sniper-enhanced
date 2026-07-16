import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  readProjectJson,
  setProjectIntentResolution,
  writeProjectJson,
} from "../../../app/api/_lib/workspace";
import { reconcileIntentCapabilities } from "../intent-capabilities";
import type { ProjectIntent } from "../intent-presets";

const root = mkdtempSync(path.join(os.tmpdir(), "sniper-intent-capability-"));
const requested: ProjectIntent = {
  mode: "longform",
  scope: "produced",
  lanes: {},
  preset: "longform-produced",
};

try {
  writeProjectJson(root, { origin: "raw", history: [] });
  const resolution = reconcileIntentCapabilities(requested, { broll: [] });
  setProjectIntentResolution(root, resolution);
  const stored = readProjectJson(root)!;
  assert.deepEqual(stored.requestedIntent, requested);
  assert.deepEqual(stored.resolvedIntent?.lanes, { broll: "off" });
  assert.deepEqual(stored.intent, stored.resolvedIntent, "legacy intent must mirror resolved authority");
  assert.equal(stored.intentDecisions?.[0].status, "resolved");

  const full = reconcileIntentCapabilities({ ...requested, scope: "full" }, { broll: [] });
  setProjectIntentResolution(root, full);
  const fullStored = readProjectJson(root)!;
  assert.equal(fullStored.intent?.lanes.broll, "off");
  assert.equal(fullStored.resolvedIntent?.lanes.broll, "off");
  assert.equal(fullStored.requestedIntent?.scope, "full");
  assert.equal(fullStored.intentDecisions?.[0].status, "resolved");
} finally {
  rmSync(root, { recursive: true, force: true });
}

console.log("intent-capability-persistence.test.ts: all assertions passed");
