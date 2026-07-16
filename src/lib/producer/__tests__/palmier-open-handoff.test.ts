import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  activePalmierHandoffBlock,
  loadHandoff,
} from "../../../app/api/producer/palmier/open/route";
import { beginProducerRun, clearProducerRun } from "../../server/producer-run-registry";

const root = mkdtempSync(path.join(os.tmpdir(), "sniper-open-handoff-"));
try {
  const producer = path.join(root, "producer");
  const palmierProject = path.join(root, "palmier-project");
  mkdirSync(producer, { recursive: true });
  mkdirSync(palmierProject, { recursive: true });
  const state = {
    schemaVersion: 4,
    ownership: "sniper",
    mirrorMode: "visual-master",
    projectPath: palmierProject,
    latestTimelineId: "timeline-1",
    lastPushPlanHash: "plan-1",
    parity: { fullyEditable: false, mirrorReady: true },
    verification: { ok: true, timelineId: "timeline-1", planHash: "plan-1" },
  };
  const statePath = path.join(producer, "palmier.sync.json");
  beginProducerRun(producer, "auto_edit", "rendering", "Rendering review copy");
  assert.match(activePalmierHandoffBlock(producer) ?? "", /Stop and keep its checkpoint/);
  clearProducerRun(producer);
  assert.equal(activePalmierHandoffBlock(producer), null);
  writeFileSync(statePath, JSON.stringify(state));
  const handoff = loadHandoff(producer);
  assert.ok(!("error" in handoff));
  if (!("error" in handoff)) {
    assert.equal(handoff.ownership, "sniper");
    assert.equal(handoff.timelineId, "timeline-1");
  }
  writeFileSync(statePath, JSON.stringify({
    ...state,
    ownership: "palmier",
  }));
  const owned = loadHandoff(producer);
  assert.ok(!("error" in owned));
  if (!("error" in owned)) assert.equal(owned.ownership, "palmier");
  writeFileSync(statePath, JSON.stringify({
    ...state,
    parity: { fullyEditable: false, mirrorReady: false },
  }));
  assert.match((loadHandoff(producer) as { error: string }).error, /proof is incomplete/);
} finally {
  rmSync(root, { recursive: true, force: true });
}

console.log("palmier-open-handoff.test.ts: all assertions passed");
