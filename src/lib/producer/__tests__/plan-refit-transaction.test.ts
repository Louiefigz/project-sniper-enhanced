import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
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
import {
  currentPlanRefitReceipt,
  refitPlanTransaction,
  resolvePlanRefitDecision,
  writePlanRefitReceipt,
} from "../../../app/api/_lib/plan-refit-transaction";
import {
  PLAN_REFIT_PENDING_FILE,
  PLAN_REFIT_RECEIPT_FILE,
  commitPlanRefitReceipt,
  stagePlanRefitReceipt,
} from "../../../app/api/_lib/plan-refit-receipt";
import { refitSavedPlanBeforeReview } from "../../../app/api/producer/auto-edit/saved-plan-request";
import type { AutoEditCtx } from "../../../app/api/producer/auto-edit/stream";
import { pythonInterpreter, SCRIPTS_DIR } from "../../../app/api/_lib/spawn-python";

const OLD_CUT = [{ sourceId: "raw", start: 10, end: 50 }];
const NEW_CUT = [
  { sourceId: "raw", start: 10, end: 25 },
  { sourceId: "raw", start: 30, end: 50 },
];
function plan(cutTrack: unknown, graphicsTrack: unknown[] = []): Record<string, unknown> {
  return { planVersion: 1, target: { mode: "longform" }, cutTrack, graphicsTrack };
}
function fixture(): { dir: string; planPath: string; oldPath: string } {
  const dir = mkdtempSync(path.join(os.tmpdir(), "sniper-plan-refit-transaction-"));
  const planPath = path.join(dir, "edit_plan.json");
  const oldPath = path.join(dir, "base_plan.json");
  writeFileSync(oldPath, JSON.stringify(plan(OLD_CUT)));
  writeFileSync(planPath, JSON.stringify(plan(NEW_CUT, [
    { id: "g-drop", kind: "statement-card", outStart: 15.5, outEnd: 19.5 },
    { id: "g-shift", kind: "statement-card", outStart: 25, outEnd: 30 },
  ])));
  return { dir, planPath, oldPath };
}
async function transactionIsAtomicAndLoud(): Promise<void> {
  const item = fixture();
  try {
    const receipt = await refitPlanTransaction({
      planPath: item.planPath,
      oldPlanPath: item.oldPath,
      source: "saved-plan",
    });
    assert.ok(receipt);
    assert.equal(receipt.schemaVersion, 2);
    assert.equal(receipt.dropped, 1);
    assert.equal(receipt.remapped, 1);
    const updated = JSON.parse(readFileSync(item.planPath, "utf8")) as {
      graphicsTrack: Array<{ id: string; outStart: number; outEnd: number }>;
    };
    assert.deepEqual(updated.graphicsTrack.map((entry) => entry.id), ["g-shift"]);
    assert.equal(updated.graphicsTrack[0].outStart, 20);
    assert.equal(updated.graphicsTrack[0].outEnd, 25);
    writePlanRefitReceipt(item.dir, receipt, item.planPath);
    assert.equal(currentPlanRefitReceipt(item.dir, item.planPath)?.dropped, 1);
    assert.equal(currentPlanRefitReceipt(item.dir, item.planPath)?.remapped, 1);
    writeFileSync(item.planPath, `${readFileSync(item.planPath, "utf8")} `);
    assert.equal(currentPlanRefitReceipt(item.dir, item.planPath), null);
  } finally {
    rmSync(item.dir, { recursive: true, force: true });
  }
}

async function failedRefitPreservesOperatorPlan(): Promise<void> {
  const item = fixture();
  try {
    const before = readFileSync(item.planPath, "utf8");
    writeFileSync(item.oldPath, "not-json");
    await assert.rejects(() => refitPlanTransaction({
      planPath: item.planPath,
      oldPlanPath: item.oldPath,
      source: "saved-plan",
    }));
    assert.equal(readFileSync(item.planPath, "utf8"), before);
    assert.equal(existsSync(`${item.planPath}.refit.json`), false);
  } finally {
    rmSync(item.dir, { recursive: true, force: true });
  }
}

async function savedReviewPreservesFullPlanTimebase(): Promise<void> {
  const item = fixture();
  try {
    const source = path.join(item.dir, "source");
    mkdirSync(source);
    const manifestPath = path.join(source, "asset_manifest.json");
    writeFileSync(manifestPath, JSON.stringify({ sources: [], broll: [] }));
    const ctx: AutoEditCtx = {
      dir: item.dir,
      scope: "produced",
      planPath: item.planPath,
      manifestPath,
      transcriptsDir: source,
    };
    const before = readFileSync(item.planPath, "utf8");
    const result = await refitSavedPlanBeforeReview(ctx);
    assert.equal(result.receipt, null);
    assert.equal(result.snapshots, undefined);
    assert.equal(readFileSync(item.planPath, "utf8"), before,
      "a complete saved plan is already authored in its own cut timebase");
    assert.equal(currentPlanRefitReceipt(item.dir, item.planPath), null);
    assert.equal(existsSync(path.join(item.dir, "plan-history")), false,
      "review does not snapshot or rewrite a complete plan");
    const unchanged = await refitSavedPlanBeforeReview(ctx);
    assert.equal(unchanged.receipt, null);
  } finally {
    rmSync(item.dir, { recursive: true, force: true });
  }
}

async function chainedSurgicalRefitIsExactlyOnce(): Promise<void> {
  const item = fixture();
  try {
    const surgical = await refitPlanTransaction({
      planPath: item.planPath,
      oldPlanPath: item.oldPath,
      source: "surgical-cut",
      receiptDir: item.dir,
      deferReceiptCommit: true,
    });
    assert.ok(surgical);
    commitPlanRefitReceipt(item.dir, surgical, item.planPath);
    const once = JSON.parse(readFileSync(item.planPath, "utf8")) as {
      graphicsTrack: Array<{
        id: string; kind: string; outStart: number; outEnd: number;
      }>;
    };
    assert.deepEqual(once.graphicsTrack[0], {
      id: "g-shift", kind: "statement-card", outStart: 20, outEnd: 25,
    });
    const source = path.join(item.dir, "source");
    mkdirSync(source);
    const manifestPath = path.join(source, "asset_manifest.json");
    writeFileSync(manifestPath, JSON.stringify({ sources: [] }));
    const ctx: AutoEditCtx = {
      dir: item.dir, scope: "produced", planPath: item.planPath,
      manifestPath, transcriptsDir: source,
    };
    const reviewed = await refitSavedPlanBeforeReview(ctx);
    assert.equal(reviewed.alreadyApplied, true);
    const after = JSON.parse(readFileSync(item.planPath, "utf8")) as typeof once;
    assert.deepEqual(after.graphicsTrack, once.graphicsTrack,
      "saved review must not map [20,25] a second time to [15,20]");

    after.graphicsTrack[0].kind = "quote-card";
    writeFileSync(item.planPath, JSON.stringify(after));
    assert.equal(resolvePlanRefitDecision(
      item.dir, item.planPath, { kind: "full-plan" },
    ).kind, "unchanged", "a complete non-cut edit stays in its own target timebase");
  } finally {
    rmSync(item.dir, { recursive: true, force: true });
  }
}

async function secondCutStartsFromLastAppliedTarget(): Promise<void> {
  const item = fixture();
  try {
    const first = await refitPlanTransaction({
      planPath: item.planPath, oldPlanPath: item.oldPath,
      source: "surgical-cut", receiptDir: item.dir,
    });
    assert.ok(first);
    const onceText = readFileSync(item.planPath, "utf8");
    const current = JSON.parse(readFileSync(item.planPath, "utf8")) as Record<string, unknown>;
    current.cutTrack = [
      { sourceId: "raw", start: 10, end: 15 },
      { sourceId: "raw", start: 18, end: 25 },
      { sourceId: "raw", start: 30, end: 50 },
    ];
    writeFileSync(item.planPath, JSON.stringify(current));
    const result = await refitPlanTransaction({
      planPath: item.planPath,
      oldPlanText: onceText,
      source: "surgical-cut",
      receiptDir: item.dir,
    });
    assert.equal(result?.sourceCutHash, first.targetCutHash);
    const twice = JSON.parse(readFileSync(item.planPath, "utf8")) as {
      graphicsTrack: Array<{ outStart: number; outEnd: number }>;
    };
    assert.deepEqual(twice.graphicsTrack.map((row) => [row.outStart, row.outEnd]),
      [[17, 22]], "the second cut maps once from C1, not again from base C0");
  } finally {
    rmSync(item.dir, { recursive: true, force: true });
  }
}

async function pendingReceiptRecoversCrashOrdering(): Promise<void> {
  const item = fixture();
  try {
    const receipt = await refitPlanTransaction({
      planPath: item.planPath, oldPlanPath: item.oldPath, source: "saved-plan",
    });
    assert.ok(receipt);
    stagePlanRefitReceipt(item.dir, receipt);
    assert.ok(existsSync(path.join(item.dir, PLAN_REFIT_PENDING_FILE)));
    const decision = resolvePlanRefitDecision(item.dir, item.planPath, {
      kind: "cut-only", oldPlanText: readFileSync(item.oldPath, "utf8"),
    });
    assert.equal(decision.kind, "already-applied");
    assert.ok(existsSync(path.join(item.dir, PLAN_REFIT_RECEIPT_FILE)));
    assert.equal(existsSync(path.join(item.dir, PLAN_REFIT_PENDING_FILE)), false);
  } finally {
    rmSync(item.dir, { recursive: true, force: true });
  }
}

async function receiptBeforePromotionIsHarmless(): Promise<void> {
  const item = fixture();
  try {
    const original = readFileSync(item.oldPath, "utf8");
    const receipt = await refitPlanTransaction({
      planPath: item.planPath, oldPlanText: original, source: "surgical-cut",
    });
    assert.ok(receipt);
    stagePlanRefitReceipt(item.dir, receipt);
    writeFileSync(item.planPath, original);
    const decision = resolvePlanRefitDecision(item.dir, item.planPath, {
      kind: "cut-only", oldPlanText: original,
    });
    assert.equal(decision.kind, "unchanged");
    assert.equal(existsSync(path.join(item.dir, PLAN_REFIT_PENDING_FILE)), false,
      "a receipt staged before candidate promotion has no authority on its own");
  } finally {
    rmSync(item.dir, { recursive: true, force: true });
  }
}

async function malformedReceiptFailsClosed(): Promise<void> {
  const item = fixture();
  try {
    writeFileSync(path.join(item.dir, PLAN_REFIT_RECEIPT_FILE), "{broken");
    assert.throws(
      () => resolvePlanRefitDecision(item.dir, item.planPath, { kind: "full-plan" }),
      /not valid JSON/,
    );
    writeFileSync(path.join(item.dir, PLAN_REFIT_RECEIPT_FILE), JSON.stringify({
      schemaVersion: 2, transactionState: "committed", source: "saved-plan",
      inputPlanHash: "a", planHash: "b", sourceCutTrack: OLD_CUT,
      targetCutTrack: NEW_CUT, sourceCutHash: "wrong", targetCutHash: "wrong",
      remapped: 0, dropped: 0, changes: [], createdAt: new Date().toISOString(),
    }));
    assert.throws(
      () => resolvePlanRefitDecision(item.dir, item.planPath, { kind: "full-plan" }),
      /conflicting cut-timebase hashes/,
    );
  } finally {
    rmSync(item.dir, { recursive: true, force: true });
  }
}

async function pythonAcceptsTypeScriptReceipt(): Promise<void> {
  const item = fixture();
  try {
    await refitPlanTransaction({
      planPath: item.planPath, oldPlanPath: item.oldPath,
      source: "saved-plan", receiptDir: item.dir,
    });
    const code = [
      "import json,sys", `sys.path.insert(0, ${JSON.stringify(path.join(SCRIPTS_DIR, "producer"))})`,
      "from edit.refit_authority import resolve_refit_source",
      "plan=json.load(open(sys.argv[2])); base=json.load(open(sys.argv[3]))",
      "print(resolve_refit_source(sys.argv[1],sys.argv[2],plan,base)[0])",
    ].join(";");
    const result = spawnSync(pythonInterpreter(), ["-c", code, item.dir, item.planPath, item.oldPath], {
      encoding: "utf8",
    });
    assert.equal(result.status, 0, result.stderr);
    assert.equal(result.stdout.trim(), "already-applied");
  } finally {
    rmSync(item.dir, { recursive: true, force: true });
  }
}

transactionIsAtomicAndLoud()
  .then(failedRefitPreservesOperatorPlan)
  .then(savedReviewPreservesFullPlanTimebase)
  .then(chainedSurgicalRefitIsExactlyOnce)
  .then(secondCutStartsFromLastAppliedTarget)
  .then(pendingReceiptRecoversCrashOrdering)
  .then(receiptBeforePromotionIsHarmless)
  .then(malformedReceiptFailsClosed)
  .then(pythonAcceptsTypeScriptReceipt)
  .then(() => console.log("plan-refit-transaction.test.ts: all assertions passed"))
  .catch((error) => {
    console.error(error);
    process.exitCode = 1;
  });
