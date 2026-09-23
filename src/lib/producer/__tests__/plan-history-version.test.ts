import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { emptyHistory, recordEdit, redoStep, restorePlanContent, undoStep } from "../plan-history";
import type { EditPlan } from "../edit-plan";
import { savePlanTransaction } from "@/app/api/producer/save-plan/transaction";

function plan(text: string, version: number): EditPlan {
  return { planVersion: version, target: { mode: "longform", scope: "produced", width: 1920, height: 1080, fps: 30 },
    cutTrack: [{ sourceId: "raw-1", start: 0, end: 12, speed: 1 }],
    graphicsTrack: [{ id: "g-00000001", kind: "line-swap", outStart: 1, outEnd: 3.5,
      anchor: "own-screen", spec: { text } }] } as EditPlan;
}

test("saved Studio import -> Undo -> Save -> Redo -> Save preserves live CAS and all cut content", async () => {
  const directory = mkdtempSync(path.join(os.tmpdir(), "sniper-import-undo-"));
  const filePath = path.join(directory, "edit_plan.json");
  const original = plan("Original statement", 1);
  writeFileSync(filePath, JSON.stringify(original));
  try {
    const imported = await savePlanTransaction({ filePath, plan: plan("Imported statement", 1), timebase: "full-plan" });
    assert.equal(imported.planVersion, 2);
    const history = recordEdit(emptyHistory<EditPlan>(), original, 20);
    const undo = undoStep(history, imported.plan)!;
    await assert.rejects(savePlanTransaction({ filePath, plan: undo.plan, timebase: "auto" }), /version changed/);
    const restored = restorePlanContent(undo.plan, imported.plan);
    assert.equal(restored.planVersion, 2); assert.equal(original.planVersion, 1);
    const savedUndo = await savePlanTransaction({ filePath, plan: restored, timebase: "auto" });
    assert.equal(savedUndo.planVersion, 3);
    assert.equal(savedUndo.plan.graphicsTrack![0].spec!.text, "Original statement");
    const redo = redoStep(undo.history, savedUndo.plan)!;
    const redone = restorePlanContent(redo.plan, savedUndo.plan);
    const savedRedo = await savePlanTransaction({ filePath, plan: redone, timebase: "auto" });
    assert.equal(savedRedo.planVersion, 4);
    assert.equal(savedRedo.plan.graphicsTrack![0].spec!.text, "Imported statement");
    assert.deepEqual(savedRedo.plan.cutTrack, original.cutTrack);
    const beforeConflict = readFileSync(filePath);
    await assert.rejects(savePlanTransaction({ filePath, plan: restorePlanContent(original, imported.plan), timebase: "auto" }), /version changed/);
    assert.deepEqual(readFileSync(filePath), beforeConflict, "external/later saved versions still fence stale history");
  } finally { rmSync(directory, { recursive: true, force: true }); }
});

test("legacy and malformed live version authority cannot be replaced by a historical version", () => {
  const historical = plan("old", 9), current = plan("current", 2);
  assert.equal(restorePlanContent(historical, current).planVersion, 2);
  const legacy = { ...current }; delete legacy.planVersion;
  assert.equal(restorePlanContent(historical, legacy).planVersion, undefined);
  for (const version of [-1, NaN, Infinity, 1.5]) {
    assert.throws(() => restorePlanContent(historical, { ...current, planVersion: version }), /authority/);
  }
});
