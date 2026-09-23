import assert from "node:assert/strict";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import os from "node:os";
import path from "node:path";
import { NextRequest } from "next/server";
import { PLAN_REFIT_PENDING_FILE } from "../../../app/api/_lib/plan-refit-receipt";
import { currentPlanRefitReceipt } from "../../../app/api/_lib/plan-refit-transaction";
import { POST } from "../../../app/api/producer/save-plan/route";
import { templateUsageApprovalPath } from "@/lib/server/template-usage-approval";

const OLD_CUT = [{ sourceId: "raw", start: 10, end: 50 }];
const NEW_CUT = [
  { sourceId: "raw", start: 10, end: 25 },
  { sourceId: "raw", start: 30, end: 50 },
];

interface Fixture {
  root: string;
  producer: string;
  planPath: string;
  original: Record<string, unknown>;
  dispose: () => void;
}

interface SavedPlan {
  planVersion: number;
  graphicsTrack: Array<{ id: string; outStart: number; outEnd: number }>;
}

function plan(cutTrack: unknown = OLD_CUT): Record<string, unknown> {
  return {
    planVersion: 1,
    target: { mode: "longform" },
    cutTrack,
    graphicsTrack: [
      { id: "g-00000001", kind: "line-swap", outStart: 15.5, outEnd: 19.5 },
      { id: "g-00000002", kind: "line-swap", outStart: 25, outEnd: 30 },
    ],
  };
}

function fixture(): Fixture {
  const root = mkdtempSync(path.join(os.tmpdir(), "sniper-save-plan-"));
  const producer = path.join(root, "producer");
  const planPath = path.join(producer, "edit_plan.json");
  const original = plan();
  mkdirSync(producer);
  writeFileSync(path.join(root, "project.json"), JSON.stringify({ origin: "raw" }));
  writeFileSync(planPath, `${JSON.stringify(original, null, 2)}\n`);
  return {
    root, producer, planPath, original,
    dispose: () => rmSync(root, { recursive: true, force: true }),
  };
}

async function post(item: Fixture, body: Record<string, unknown>): Promise<{
  response: Response;
  json: Record<string, unknown>;
}> {
  const response = await POST(new NextRequest("http://localhost/api/producer/save-plan", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path: item.planPath, ...body }),
  }));
  return { response, json: await response.json() as Record<string, unknown> };
}

async function cutOnlySaveRefitsAndReturnsAuthority(): Promise<void> {
  const item = fixture();
  try {
    const requested = { ...item.original, cutTrack: NEW_CUT };
    const { response, json } = await post(item, { plan: requested });
    assert.equal(response.status, 200, JSON.stringify(json));
    const refit = json.refit as Record<string, unknown>;
    assert.equal(refit.application, "newly-applied");
    assert.equal(refit.alreadyApplied, false);
    assert.equal(json.planVersion, 2);
    const disk = JSON.parse(readFileSync(item.planPath, "utf8")) as SavedPlan;
    assert.deepEqual(json.plan, disk, "client receives the refitted authority, not its stale request");
    assert.deepEqual(disk.graphicsTrack.map((row) => row.id), ["g-00000002"]);
    assert.deepEqual(disk.graphicsTrack.map((row) => [row.outStart, row.outEnd]), [[20, 25]]);
    assert.equal(currentPlanRefitReceipt(item.producer, item.planPath)?.remapped, 1);

    const retry = await post(item, { plan: requested });
    assert.equal(retry.response.status, 409, "a stale network retry cannot apply or undo the refit");
    assert.deepEqual(JSON.parse(readFileSync(item.planPath, "utf8")), disk);
  } finally {
    item.dispose();
  }
}

async function nonCutSaveKeepsExistingBehavior(): Promise<void> {
  const item = fixture();
  try {
    writeFileSync(templateUsageApprovalPath(item.producer), "stale approval\n");
    const changed = structuredClone(item.original);
    (changed.target as Record<string, unknown>).pace = "measured";
    const { response, json } = await post(item, { plan: changed });
    assert.equal(response.status, 200, JSON.stringify(json));
    assert.equal(json.refit, null);
    assert.equal(json.planVersion, 2);
    assert.equal(currentPlanRefitReceipt(item.producer, item.planPath), null);
    const returned = json.plan as { target: Record<string, unknown> };
    assert.equal(returned.target.pace, "measured");
    assert.equal(existsSync(templateUsageApprovalPath(item.producer)), false,
      "every saved draft invalidates the prior delivery approval");
  } finally {
    item.dispose();
  }
}

async function graphicsGovernanceSurvivesOrdinarySave(): Promise<void> {
  const item = fixture();
  try {
    const changed = structuredClone(item.original);
    Object.assign(changed.target as Record<string, unknown>, {
      graphicsStyle: "catalog-first",
      graphicsStyleRationale: "The kept intro needs a layered explanatory grammar.",
    });
    changed.graphicsDecisions = [{
      beatId: "intro-abc123def456", decision: "graphic",
      kind: "line-swap", reason: "This directly expresses the thesis beat.",
      alternativesConsidered: ["marker-highlight", "count-up"],
      selectionReason: "The full sentence needs a stable, readable takeover.",
    }];
    (changed.graphicsTrack as Array<Record<string, unknown>>)[0].semanticBeatId =
      "intro-abc123def456";
    const { response, json } = await post(item, { plan: changed });
    assert.equal(response.status, 200, JSON.stringify(json));
    const disk = JSON.parse(readFileSync(item.planPath, "utf8")) as Record<string, unknown>;
    const decisions = disk.graphicsDecisions as Array<Record<string, unknown>>;
    assert.equal(decisions[0].graphicId, "g-00000001",
      "save normalization preserves the controller-minted semantic binding");
    assert.equal((disk.target as Record<string, unknown>).graphicsStyle, "catalog-first");
  } finally {
    item.dispose();
  }
}

async function mixedCutSaveFailsClosed(): Promise<void> {
  const item = fixture();
  try {
    const before = readFileSync(item.planPath, "utf8");
    const changed = { ...item.original, cutTrack: NEW_CUT, music: { enabled: true } };
    const { response, json } = await post(item, { plan: changed });
    assert.equal(response.status, 409);
    assert.match(String(json.error), /cutTrack changed with music/);
    assert.equal(readFileSync(item.planPath, "utf8"), before);
    assert.equal(currentPlanRefitReceipt(item.producer, item.planPath), null);
  } finally {
    item.dispose();
  }
}

async function explicitFullPlanSkipsRefit(): Promise<void> {
  const item = fixture();
  try {
    const changed = { ...item.original, cutTrack: NEW_CUT, music: { enabled: true } };
    const { response, json } = await post(item, { plan: changed, timebase: "full-plan" });
    assert.equal(response.status, 200, JSON.stringify(json));
    assert.equal(json.refit, null);
    const returned = json.plan as { graphicsTrack: unknown[] };
    assert.equal(returned.graphicsTrack.length, 2,
      "a declared complete plan already owns all output-time coordinates");
  } finally {
    item.dispose();
  }
}

async function refitFailurePreservesOldPlan(): Promise<void> {
  const item = fixture();
  try {
    const before = readFileSync(item.planPath, "utf8");
    const invalidCut = [{ sourceId: "raw", start: 10 }];
    const { response } = await post(item, {
      plan: { ...item.original, cutTrack: invalidCut },
    });
    assert.equal(response.status, 500);
    assert.equal(readFileSync(item.planPath, "utf8"), before);
    assert.equal(existsSync(path.join(item.producer, PLAN_REFIT_PENDING_FILE)), false);
    assert.equal(currentPlanRefitReceipt(item.producer, item.planPath), null);
  } finally {
    item.dispose();
  }
}

cutOnlySaveRefitsAndReturnsAuthority()
  .then(nonCutSaveKeepsExistingBehavior)
  .then(graphicsGovernanceSurvivesOrdinarySave)
  .then(mixedCutSaveFailsClosed)
  .then(explicitFullPlanSkipsRefit)
  .then(refitFailurePreservesOldPlan)
  .then(() => console.log("save-plan-transaction.test.ts: all assertions passed"))
  .catch((error) => {
    console.error(error);
    process.exitCode = 1;
  });
