import assert from "node:assert/strict";
import { test } from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ProjectCard from "@/components/producer/project-card";
import EditorView from "@/components/producer/editor/editor-view";
import { confirmedBack } from "@/components/producer/editor/editor-view-sections";
import { canResumeAutoEdit, projectPhaseCopy, type ProducerRunState } from "../project-state";
import { isGuidedCheckpoint, isTreatmentCheckpoint, treatmentCheckpointLockReason,
  treatmentCheckpointLabel, TREATMENT_INTEGRATION_NOTICE } from "../guided-checkpoint-state";
import type { ProjectStatus } from "@/components/producer/use-project-status";

Object.assign(globalThis, { React });
const dir = "/private/tmp/synthetic-guided-treatment-ui/producer";
const stages = { ingested: true, transcribed: true, plan: true, base: true, final: true };
const states = ["awaiting_cut_approval", "awaiting_treatment_brief", "treatment_admitted", "failed", "interrupted"] as const;
function run(status: typeof states[number]): ProducerRunState {
  return { kind: "auto_edit", status, phase: "planning_review", workflowVersion: 2,
    workflowPolicy: "cut-first", deliveryPolicy: "mp4-only", startedAt: "2026-09-06T00:00:00.000Z",
    updatedAt: "2026-09-06T00:01:00.000Z", message: "Synthetic unqualified v2 checkpoint", events: [] };
}
function status(value: ProducerRunState): ProjectStatus {
  return { dir, producerDir: dir, projectRoot: dir, origin: "raw", intent: null, requestedIntent: null,
    intentDecisions: [], stages, segments: [], clipperFiles: [], sourceDir: `${dir}/source`,
    manifestPath: `${dir}/asset_manifest.json`, finalArtifact: { state: "approved", path: `${dir}/final.mp4`, reason: null },
    palmier: { state: "approved_working_head", canOpen: true, projectPath: "/inert/old",
      projectId: "old", timelineId: "old", verified: true, authorityOrigin: "saved", detail: "Old approved work" }, run: value };
}
test("saved treatment copy distinguishes working opening controls from unfinished upstream and body controls", () => {
  assert.equal(treatmentCheckpointLabel(run("treatment_admitted")), "Treatment saved · opening workflow");
  assert.match(TREATMENT_INTEGRATION_NOTICE, /explicit opening controls for a qualified proposal/);
  assert.match(TREATMENT_INTEGRATION_NOTICE, /proposal compilation and review, and full-body continuation are still unfinished/);
  assert.doesNotMatch(TREATMENT_INTEGRATION_NOTICE, /opening-preview workflow is not enabled/);
});
for (const state of states) {
  test(`unreleased v2 ${state} cannot expose legacy approval or resume actions`, () => {
    const value = run(state);
    assert.ok(isGuidedCheckpoint(value));
    assert.ok(isTreatmentCheckpoint(value));
    assert.equal(canResumeAutoEdit(value), false);
    assert.match(treatmentCheckpointLockReason(value)!, /cannot bypass/);
    assert.doesNotMatch(projectPhaseCopy(stages, value).label, /Finished/);
    const html = renderToStaticMarkup(React.createElement(ProjectCard, {
      p: { dir, title: "Synthetic v2", exists: true, mtime: null }, status: status(value), statusError: null,
      onOpen() {}, onRemove() {}, onRefresh() {}, async onRename() {},
    }));
    assert.match(html, /Recheck guided checkpoint/);
    assert.match(html, /Inspect guided checkpoint/);
    assert.doesNotMatch(html, /<dialog|Accept cut|Review cut<|Open approved|>Resume edit<|>Finished</);
  });
}

test("legacy failed projects remain resumable and legacy checkpoints retain their controls", () => {
  const legacy = { ...run("failed"), workflowVersion: undefined };
  assert.equal(canResumeAutoEdit(legacy), true);
  assert.equal(isTreatmentCheckpoint(legacy), false);
  assert.equal(isGuidedCheckpoint({ ...legacy, status: "awaiting_cut_approval" }), true);
});

test("initial editor status check mounts no timeline, player, or premature Color controls", () => {
  const html = renderToStaticMarkup(React.createElement(EditorView, { dir, title: "Synthetic status gate",
    plan: { cutTrack: [], graphicsTrack: [] }, onBack() {} }));
  assert.match(html, /Checking project status before opening the editor/);
  assert.match(html, /Synthetic status gate/);
  assert.match(html, /Recheck project status/);
  assert.doesNotMatch(html, /<video|<iframe|Run private color|Save.*timeline/);
});

test("checkpoint navigation preserves an existing dirty timeline when discard is canceled", () => {
  let navigations = 0, prompts = 0;
  const back = () => { navigations++; };
  const cancel = () => { prompts++; return false; };
  confirmedBack(back, true, cancel)!();
  assert.equal(prompts, 1);
  assert.equal(navigations, 0);
  confirmedBack(back, false, cancel)!();
  assert.equal(prompts, 1);
  assert.equal(navigations, 1);
  confirmedBack(back, true, () => true)!();
  assert.equal(navigations, 2);
  assert.equal(confirmedBack(undefined, true, cancel), undefined);
});
