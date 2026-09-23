import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  assertSurgicalPlanChange,
  inferSurgicalEditScope,
  parseSurgicalEditScope,
  surgicalScopeFields,
  validateRequestedSurgicalEditScope,
} from "../surgical-edit";
import {
  assertSurgicalReviewCurrent,
  beginSurgicalReview,
  finalizeSurgicalEdit,
} from "../../../app/api/producer/ai-edit/finalize";
import type { ProducerReview } from "../../../app/api/producer/auto-edit/review-contract";
import { surgicalCutOnlyPlan } from "../../../app/api/producer/ai-edit/surgical-governance";

const graphics = inferSurgicalEditScope("Add a full-screen title card at 0:42");
assert.deepEqual(graphics, { lanes: ["graphics"] });
assert.deepEqual(
  inferSurgicalEditScope("Remove the pause and add a smooth transition"),
  { lanes: ["cuts", "motion"] },
);
assert.equal(inferSurgicalEditScope("make it better"), null);
assert.deepEqual(parseSurgicalEditScope({ lanes: ["audio", "music"] }), {
  lanes: ["audio", "music"],
});
assert.deepEqual(
  validateRequestedSurgicalEditScope("Turn down the music", { lanes: ["music"] }),
  { lanes: ["music"] },
);
assert.throws(
  () => validateRequestedSurgicalEditScope("Add a title card", { lanes: ["cuts"] }),
  /do not match controller lanes graphics/,
);
assert.deepEqual(surgicalScopeFields({ lanes: ["motion"] }), [
  "punchIns", "transitions", "treatmentMap",
]);
assert.deepEqual(surgicalScopeFields({ lanes: ["captions"] }), [
  "captions", "captionsTrack", "captionCorrectionLedger", "captionStyles",
  "captionChapters",
]);
assert.throws(() => parseSurgicalEditScope({ lanes: ["graphics", "graphics"] }), /unique/);
assert.throws(
  () => assertSurgicalPlanChange(
    { cutTrack: [{ start: 0, end: 4 }], graphicsTrack: [] },
    { cutTrack: [{ start: 0, end: 3 }], graphicsTrack: [] },
    { lanes: ["graphics"] },
  ),
  /outside the requested scope: cutTrack/,
);

const passReview: ProducerReview = {
  schemaVersion: 1,
  stage: "plan",
  verdict: "pass",
  summary: "The scoped card is restrained, readable, and grounded.",
  materialIssues: [],
  findings: [],
};

function planHash(text: string): string {
  return createHash("sha256").update(text).digest("hex");
}

function fixture(): { dir: string; planPath: string; manifestPath: string; original: string } {
  const dir = mkdtempSync(path.join(os.tmpdir(), "sniper-surgical-edit-"));
  const planPath = path.join(dir, "edit_plan.json");
  const manifestPath = path.join(dir, "asset_manifest.json");
  const original = `${JSON.stringify({
    planVersion: 1,
    target: { mode: "longform" },
    cutTrack: [{ sourceId: "source-1", start: 0, end: 10 }],
    graphicsTrack: [],
  }, null, 2)}\n`;
  writeFileSync(planPath, original);
  writeFileSync(manifestPath, JSON.stringify({ sources: [] }));
  return { dir, planPath, manifestPath, original };
}

async function approvedEdit(): Promise<void> {
  const item = fixture();
  try {
    writeFileSync(item.planPath, JSON.stringify({
      planVersion: 1,
      target: { mode: "longform" },
      cutTrack: [{ sourceId: "source-1", start: 0, end: 10 }],
      graphicsTrack: [{
        outStart: 2, outEnd: 5, kind: "line-swap", anchor: "own-screen",
        reason: "Clarify the thesis", spec: { lineA: "One useful idea", lineB: "One useful idea" },
      }],
    }));
    beginSurgicalReview(item.dir, { lanes: ["graphics"] });
    const result = await finalizeSurgicalEdit({
      provider: "codex",
      dir: item.dir,
      planPath: item.planPath,
      manifestPath: item.manifestPath,
      transcriptsDir: item.dir,
      request: "Add a title card",
      scope: { lanes: ["graphics"] },
      originalPlanText: item.original,
      parentPlanHash: planHash(item.original),
    }, {
      governance: async () => ({ warnings: [] }),
      critic: async () => passReview,
    });
    assert.deepEqual(result.changedFields, ["graphicsTrack"]);
    assertSurgicalReviewCurrent(item.planPath);
    const plan = JSON.parse(readFileSync(item.planPath, "utf8")) as { graphicsTrack: Array<{ id?: string }> };
    assert.match(plan.graphicsTrack[0].id ?? "", /^g-[0-9a-z]{8}$/);
    writeFileSync(item.planPath, `${readFileSync(item.planPath, "utf8")} `);
    assert.throws(
      () => assertSurgicalReviewCurrent(item.planPath),
      /plan changed after its surgical edit review/,
    );
  } finally {
    rmSync(item.dir, { recursive: true, force: true });
  }
}

function cutOnlyApprovalShadowPreservesCutAuthority(): void {
  const item = fixture();
  try {
    const plan = {
      target: { mode: "longform" },
      cutTrack: [{ sourceId: "source-1", start: 1, end: 9 }],
      cutDecisions: { schemaVersion: 1, removals: [] },
      graphicsTrack: [{ kind: "statement-card" }],
      transitions: [{ kind: "zoom-pull" }],
      transitionRationale: [{ at: 2, why: "cover the join" }],
      graphicsDecisions: [{ id: "g1", reason: "name the framework on first mention" }],
      punchIns: [{ outStart: 2 }],
      music: { enabled: true },
    };
    writeFileSync(item.planPath, JSON.stringify(plan));
    const shadow = surgicalCutOnlyPlan(item.planPath);
    assert.deepEqual(shadow.cutTrack, plan.cutTrack);
    assert.deepEqual(shadow.cutDecisions, plan.cutDecisions);
    // A denylist silently leaks the rationale sidecars — the previsual gate rejects
    // them ("populated downstream fields: transitionRationale, graphicsDecisions").
    // An allowlist keeps ONLY the four cut keys, so every visual lane AND its
    // rationale sidecar must be absent.
    for (const field of ["graphicsTrack", "transitions", "transitionRationale",
      "graphicsDecisions", "punchIns", "music"]) {
      assert.equal(field in shadow, false, `${field} cannot contaminate previsual approval`);
    }
  } finally {
    rmSync(item.dir, { recursive: true, force: true });
  }
}

async function rejectedEditRollsBack(): Promise<void> {
  const item = fixture();
  try {
    writeFileSync(item.planPath, JSON.stringify({
      planVersion: 1,
      target: { mode: "longform" },
      cutTrack: [{ sourceId: "source-1", start: 0, end: 4 }],
      graphicsTrack: [],
    }));
    beginSurgicalReview(item.dir, { lanes: ["graphics"] });
    await assert.rejects(() => finalizeSurgicalEdit({
      provider: "legacy",
      dir: item.dir,
      planPath: item.planPath,
      manifestPath: item.manifestPath,
      transcriptsDir: item.dir,
      request: "Add a title card",
      scope: { lanes: ["graphics"] },
      originalPlanText: item.original,
      parentPlanHash: planHash(item.original),
    }, {
      governance: async () => ({ warnings: [] }),
      critic: async () => passReview,
    }), /outside the requested scope/);
    assert.equal(readFileSync(item.planPath, "utf8"), item.original);
    assert.doesNotThrow(() => assertSurgicalReviewCurrent(item.planPath));
  } finally {
    rmSync(item.dir, { recursive: true, force: true });
  }
}

async function cutRefitsBeforeLint(): Promise<void> {
  const item = fixture();
  const candidatePath = path.join(item.dir, ".sniper-ai-edit-cut-candidate.json");
  const approvalPath = path.join(item.dir, ".sniper-cut-approval.json");
  try {
    const original = `${JSON.stringify({
      planVersion: 1,
      target: { mode: "longform" },
      cutTrack: [{ sourceId: "source-1", start: 10, end: 50 }],
      graphicsTrack: [{ id: "g-1234abcd", kind: "line-swap", outStart: 15.5, outEnd: 19.5 }],
    }, null, 2)}\n`;
    writeFileSync(item.planPath, original);
    writeFileSync(approvalPath, "old-cut-authority\n");
    writeFileSync(candidatePath, JSON.stringify({
      planVersion: 1,
      target: { mode: "longform" },
      cutTrack: [
        { sourceId: "source-1", start: 10, end: 25 },
        { sourceId: "source-1", start: 30, end: 50 },
      ],
      graphicsTrack: [{ id: "g-1234abcd", kind: "line-swap", outStart: 15.5, outEnd: 19.5 }],
    }));
    beginSurgicalReview(item.dir, { lanes: ["cuts"] });
    const result = await finalizeSurgicalEdit({
      provider: "codex",
      dir: item.dir,
      planPath: candidatePath,
      authorityPlanPath: item.planPath,
      manifestPath: item.manifestPath,
      transcriptsDir: item.dir,
      request: "Remove the middle pause",
      scope: { lanes: ["cuts"] },
      originalPlanText: original,
      parentPlanHash: planHash(original),
    }, {
      governance: async ({ planPath }) => {
        const current = JSON.parse(readFileSync(planPath, "utf8")) as { graphicsTrack: unknown[] };
        assert.deepEqual(current.graphicsTrack, [], "dependent windows are refitted before lint");
        assert.equal(readFileSync(item.planPath, "utf8"), original,
          "canonical authority stays untouched while the refitted candidate is reviewed");
        return {
          warnings: [],
          cutApproval: { path: approvalPath, text: "new-cut-authority\n" },
        };
      },
      critic: async () => {
        assert.equal(readFileSync(approvalPath, "utf8"), "old-cut-authority\n",
          "candidate cut authority stays unpromoted until the critic passes");
        return passReview;
      },
    });
    assert.deepEqual(result.changedFields, ["cutTrack"]);
    assert.equal(result.refit?.dropped, 1);
    assertSurgicalReviewCurrent(item.planPath);
    const promoted = JSON.parse(readFileSync(item.planPath, "utf8")) as { graphicsTrack: unknown[] };
    assert.deepEqual(promoted.graphicsTrack, []);
    assert.equal(readFileSync(approvalPath, "utf8"), "new-cut-authority\n");
    assert.equal(existsSync(candidatePath), false);
  } finally {
    rmSync(item.dir, { recursive: true, force: true });
  }
}

async function candidatePromotesOnlyAfterReview(): Promise<void> {
  const item = fixture();
  const candidatePath = path.join(item.dir, ".sniper-ai-edit-candidate-test.json");
  try {
    writeFileSync(candidatePath, JSON.stringify({
      planVersion: 1,
      target: { mode: "longform" },
      cutTrack: [{ sourceId: "source-1", start: 0, end: 10 }],
      graphicsTrack: [{
        outStart: 2, outEnd: 5, kind: "line-swap", anchor: "own-screen",
        reason: "Clarify the thesis", spec: { title: "Reviewed first" },
      }],
    }));
    beginSurgicalReview(item.dir, { lanes: ["graphics"] });
    await finalizeSurgicalEdit({
      provider: "codex",
      dir: item.dir,
      planPath: candidatePath,
      authorityPlanPath: item.planPath,
      manifestPath: item.manifestPath,
      transcriptsDir: item.dir,
      request: "Add a title card",
      scope: { lanes: ["graphics"] },
      originalPlanText: item.original,
      parentPlanHash: planHash(item.original),
    }, {
      governance: async () => ({ warnings: [] }),
      critic: async () => {
        assert.equal(readFileSync(item.planPath, "utf8"), item.original,
          "canonical authority stays untouched until the critic passes");
        return passReview;
      },
    });
    assert.match(readFileSync(item.planPath, "utf8"), /Reviewed first/);
    assert.equal(existsSync(candidatePath), false);
    assertSurgicalReviewCurrent(item.planPath);
  } finally {
    rmSync(item.dir, { recursive: true, force: true });
  }
}

cutOnlyApprovalShadowPreservesCutAuthority();
approvedEdit()
  .then(rejectedEditRollsBack)
  .then(cutRefitsBeforeLint)
  .then(candidatePromotesOnlyAfterReview)
  .then(() => console.log("surgical-edit.test.ts: all assertions passed"))
  .catch((error) => {
    console.error(error);
    process.exitCode = 1;
  });
