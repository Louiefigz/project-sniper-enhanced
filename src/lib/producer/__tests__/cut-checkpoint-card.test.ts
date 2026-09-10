import assert from "node:assert/strict";
import { test } from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ProjectCard from "@/components/producer/project-card";
import type { ProjectStatus } from "@/components/producer/use-project-status";

const dir = "/private/tmp/synthetic-cut-checkpoint-card/producer";
const checkpoints = ["awaiting_cut_approval", "cut_accepted"] as const;
const palmierStates = ["approved_working_head", "approved_mirror", "manual_working_head",
  "pending_candidate", "approved_candidate", "no_workspace"] as const;
const finalStates = ["missing", "unapproved", "approved"] as const;

function fixture(
  checkpoint: typeof checkpoints[number],
  palmier: typeof palmierStates[number],
  final: typeof finalStates[number],
  candidateActive = false,
): ProjectStatus {
  return {
    dir, producerDir: dir, projectRoot: dir, origin: "raw",
    intent: { mode: "longform", scope: "produced", lanes: {} }, requestedIntent: null,
    intentDecisions: [{ code: "BROLL_UNAVAILABLE_RESOLVED", lane: "broll", requested: "auto",
      resolved: "off", status: "resolved", eligibleAssets: 0, message: "Historical cutaway resolution." }],
    stages: { ingested: true, transcribed: true, plan: true, base: final !== "missing", final: final === "approved" },
    segments: [], clipperFiles: [], sourceDir: `${dir}/source`, manifestPath: `${dir}/asset_manifest.json`,
    finalArtifact: { state: final, path: final === "missing" ? null : `${dir}/final.mp4`, reason: null },
    palmier: { state: palmier, canOpen: palmier !== "no_workspace", projectPath: "/inert/historical-palmier",
      projectId: "historical", timelineId: "historical", verified: true, authorityOrigin: "saved",
      approvalCurrent: true, detail: "Historical Palmier state.", candidateQc: {
        state: "approved", active: candidateActive, action: null, canRunQc: true, canPromote: true,
        canDiscard: true, step: null, message: "Historical candidate.",
      } },
    run: { kind: "auto_edit", status: checkpoint, phase: "planning_review",
      startedAt: "2026-09-06T00:00:00.000Z", updatedAt: "2026-09-06T00:01:00.000Z",
      message: "Synthetic cut checkpoint.", events: [], deliveryPolicy: "mp4-only", workflowPolicy: "cut-first" },
  };
}

function renderCard(status: ProjectStatus): string {
  Object.assign(globalThis, { React });
  return renderToStaticMarkup(React.createElement(ProjectCard, {
    p: { dir, title: "Synthetic checkpoint fixture", exists: true, mtime: null },
    status, statusError: null, onOpen: () => {}, onRemove: () => {},
    onRename: async () => {}, onRefresh: () => {},
  }));
}

function buttonLabels(html: string): string[] {
  return [...html.matchAll(/<button\b[^>]*>(.*?)<\/button>/g)]
    .map((match) => match[1].replace(/<[^>]*>/g, "").trim());
}

const cases = checkpoints.flatMap((checkpoint) => palmierStates.flatMap((palmier) =>
  finalStates.map((final) => ({ checkpoint, palmier, final }))))
  .flatMap((value) => [false, true].map((candidateActive) => ({ ...value, candidateActive })));

for (const { checkpoint, palmier, final, candidateActive } of cases) {
  test(`actual ProjectCard: ${checkpoint}, ${palmier}, ${final} final, candidate active=${candidateActive}`, () => {
    const html = renderCard(fixture(checkpoint, palmier, final, candidateActive));
    const accepted = checkpoint === "cut_accepted";
    assert.deepEqual(buttonLabels(html), ["Synthetic checkpoint fixture", "Rename",
      accepted ? "Continue accepted cut" : "Review cut", "Close cut review",
      accepted ? "Open accepted-cut continuation" : "Open cut review", "View details"]);
    assert.match(html, /<dialog[^>]*aria-label="Review cut checkpoint"/);
    assert.doesNotMatch(html, /<video|type="checkbox"|Accept cut and continue/);
    assert.doesNotMatch(html, /Historical cutaway resolution|Palmier edit approved|>Finished</);
    assert.match(html, /cannot bypass/);
  });
}

test("historical approved Palmier controls remain available outside the cut checkpoint", () => {
  const status = fixture("awaiting_cut_approval", "approved_working_head", "approved");
  status.run = null;
  delete status.palmier.candidateQc;
  const html = renderCard(status);
  assert.ok(buttonLabels(html).includes("Open approved Palmier timeline"));
  assert.ok(buttonLabels(html).includes("Open approved Sniper video"));
  assert.doesNotMatch(html, /Review cut checkpoint|Continue accepted cut/);
});
