import assert from "node:assert/strict";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { projectedIntentStatus } from "../../server/project-status-projection";
import type { ProjectJson } from "../../../app/api/_lib/workspace";

const dir = mkdtempSync(path.join(os.tmpdir(), "sniper-intent-status-"));
const manifestPath = path.join(dir, "asset_manifest.json");
const legacy: ProjectJson = {
  origin: "raw",
  history: [],
  intent: { mode: "longform", scope: "produced", lanes: {} },
};

try {
  writeFileSync(manifestPath, JSON.stringify({ sources: [], broll: [] }));
  const projected = projectedIntentStatus(legacy, manifestPath);
  assert.deepEqual(projected.requestedIntent?.lanes, {});
  assert.equal(projected.intent?.lanes.broll, "off");
  assert.equal(projected.intentDecisions[0].status, "resolved");
  assert.deepEqual(legacy.intent?.lanes, {}, "status projection must not mutate project state");

  const persistedOldCopy: ProjectJson = {
    ...legacy,
    requestedIntent: legacy.intent,
    resolvedIntent: { ...legacy.intent!, lanes: { broll: "off" } },
    intentDecisions: [{
      ...projected.intentDecisions[0],
      message: "obsolete persisted copy",
    }],
  };
  const refreshed = projectedIntentStatus(persistedOldCopy, manifestPath);
  assert.match(refreshed.intentDecisions[0].message, /Text cards, graphics, captions, and motion remain enabled/);

  writeFileSync(manifestPath, JSON.stringify({
    sources: [], broll: [{ id: "cutaway-1", path: "/tmp/cutaway.mp4" }],
  }));
  const available = projectedIntentStatus(legacy, manifestPath);
  assert.deepEqual(available.intent?.lanes, {});
  assert.deepEqual(available.intentDecisions, []);
} finally {
  rmSync(dir, { recursive: true, force: true });
}

console.log("intent-status-projection.test.ts: all assertions passed");
