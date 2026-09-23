import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  assertNoPromotionReconciliation,
  SURGICAL_RECONCILIATION_CANDIDATE_FILE,
} from "../../../app/api/producer/ai-edit/promotion-recovery";
import {
  beginSurgicalReview,
  finalizeSurgicalEdit,
} from "../../../app/api/producer/ai-edit/finalize";
import type { ProducerReview } from
  "../../../app/api/producer/auto-edit/review-contract";
import { palmierStatePath } from
  "../../../app/api/producer/palmier/_lib";

const review: ProducerReview = {
  schemaVersion: 1, stage: "plan", verdict: "pass",
  summary: "The isolated candidate is ready.", materialIssues: [], findings: [],
};

function fixture() {
  const dir = mkdtempSync(path.join(os.tmpdir(), "sniper-ask-race-"));
  const authorityPath = path.join(dir, "edit_plan.json");
  const candidatePath = path.join(dir, "candidate.json");
  const manifestPath = path.join(dir, "asset_manifest.json");
  const parentText = `${JSON.stringify({
    planVersion: 4, target: { mode: "longform" },
    cutTrack: [{ sourceId: "source-1", start: 0, end: 10 }],
    graphicsTrack: [],
  }, null, 2)}\n`;
  writeFileSync(authorityPath, parentText);
  writeFileSync(manifestPath, JSON.stringify({ sources: [] }));
  return { dir, authorityPath, candidatePath, manifestPath, parentText };
}

function stage(item: ReturnType<typeof fixture>, title: string): void {
  writeFileSync(item.candidatePath, JSON.stringify({
    planVersion: 4, target: { mode: "longform" },
    cutTrack: [{ sourceId: "source-1", start: 0, end: 10 }],
    graphicsTrack: [{
      outStart: 2, outEnd: 5, kind: "line-swap",
      anchor: "own-screen", reason: "Clarify", spec: { lineA: title, lineB: "The TEST result", underlineWord: "result" },
    }],
  }));
  beginSurgicalReview(item.dir, { lanes: ["graphics"] });
}

function input(item: ReturnType<typeof fixture>) {
  return {
    provider: "codex" as const,
    dir: item.dir,
    planPath: item.candidatePath,
    authorityPlanPath: item.authorityPath,
    manifestPath: item.manifestPath,
    transcriptsDir: item.dir,
    request: "Add a title card",
    scope: { lanes: ["graphics" as const] },
    originalPlanText: item.parentText,
    parentPlanHash: createHash("sha256").update(item.parentText).digest("hex"),
  };
}

async function candidateToctouFails(): Promise<void> {
  const item = fixture();
  try {
    stage(item, "Reviewed child");
    await assert.rejects(finalizeSurgicalEdit(input(item), {
      governance: async () => ({ warnings: [] }),
      critic: async () => {
        writeFileSync(item.candidatePath, JSON.stringify({
          planVersion: 99, target: { mode: "longform" },
          cutTrack: [{ sourceId: "foreign", start: 0, end: 2 }],
          graphicsTrack: [],
        }));
        return review;
      },
    }), /candidate changed after deterministic review/);
    assert.equal(readFileSync(item.authorityPath, "utf8"), item.parentText);
  } finally {
    rmSync(item.dir, { recursive: true, force: true });
  }
}

async function cancellationAfterPromotionRestores(): Promise<void> {
  const item = fixture();
  const controller = new AbortController();
  const finalizer = { ...input(item), signal: controller.signal };
  try {
    stage(item, "Cancelled child");
    await assert.rejects(finalizeSurgicalEdit(finalizer, {
      governance: async () => ({ warnings: [] }),
      critic: async () => review,
      afterPromotion: () => controller.abort(),
    }), /cancelled/);
    assert.equal(readFileSync(item.authorityPath, "utf8"), item.parentText);
    assert.equal(existsSync(item.candidatePath), false);
  } finally {
    rmSync(item.dir, { recursive: true, force: true });
  }
}

async function unreadableAuthorityBlocks(): Promise<void> {
  const item = fixture();
  try {
    stage(item, "Unreadable recovery child");
    await assert.rejects(finalizeSurgicalEdit(input(item), {
      governance: async () => ({ warnings: [] }),
      critic: async () => review,
      afterPromotion: (authorityPath) => {
        rmSync(authorityPath);
        mkdirSync(authorityPath);
        throw new Error("authority replaced by an unreadable node");
      },
    }), /manual reconciliation required/);
    assert.equal(existsSync(path.join(
      item.dir, SURGICAL_RECONCILIATION_CANDIDATE_FILE,
    )), true);
    assert.throws(() => assertNoPromotionReconciliation(item.dir),
      /unreadable|unresolved/);
  } finally {
    rmSync(item.dir, { recursive: true, force: true });
  }
}

async function symlinkAuthorityCannotMasqueradeAsParent(): Promise<void> {
  const item = fixture();
  const outside = path.join(item.dir, "outside-parent.json");
  writeFileSync(outside, item.parentText);
  try {
    stage(item, "Symlink recovery child");
    await assert.rejects(finalizeSurgicalEdit(input(item), {
      governance: async () => ({ warnings: [] }),
      critic: async () => review,
      afterPromotion: (authorityPath) => {
        rmSync(authorityPath);
        symlinkSync(outside, authorityPath);
        throw new Error("authority replaced by a symlink");
      },
    }), /manual reconciliation required/);
    assert.equal(readFileSync(item.authorityPath, "utf8"), item.parentText);
    assert.throws(() => assertNoPromotionReconciliation(item.dir), /unresolved/);
  } finally {
    rmSync(item.dir, { recursive: true, force: true });
  }
}

async function foreignReturnCannotBeApproved(): Promise<void> {
  const item = fixture();
  const foreign = `${JSON.stringify({
    planVersion: 80, target: { mode: "longform" },
    cutTrack: [{ sourceId: "foreign", start: 0, end: 1 }],
    graphicsTrack: [], external: true,
  })}\n`;
  try {
    stage(item, "Foreign return child");
    await assert.rejects(finalizeSurgicalEdit(input(item), {
      governance: async () => ({ warnings: [] }),
      critic: async () => review,
      afterPromotion: (authorityPath) => {
        writeFileSync(authorityPath, foreign);
      },
    }), /manual reconciliation required/);
    assert.equal(readFileSync(item.authorityPath, "utf8"), foreign);
    assert.throws(() => assertNoPromotionReconciliation(item.dir), /unresolved/);
  } finally {
    rmSync(item.dir, { recursive: true, force: true });
  }
}

async function palmierAuthorityCannotAppearBeforePromotion(): Promise<void> {
  const item = fixture();
  try {
    stage(item, "Stale Sniper child");
    await assert.rejects(finalizeSurgicalEdit(input(item), {
      governance: async () => ({ warnings: [] }),
      critic: async () => {
        writeFileSync(palmierStatePath(item.dir), JSON.stringify({
          schemaVersion: 4,
          workspaceMode: "managed-draft",
          ownership: "sniper",
          projectId: "managed-project",
          projectPath: item.dir,
          latestTimelineId: "managed-timeline",
        }));
        return review;
      },
    }), /managed Palmier workspace|Palmier.*canonical/);
    assert.equal(readFileSync(item.authorityPath, "utf8"), item.parentText);
    assert.equal(existsSync(item.candidatePath), false);
  } finally {
    rmSync(item.dir, { recursive: true, force: true });
  }
}

candidateToctouFails()
  .then(cancellationAfterPromotionRestores)
  .then(unreadableAuthorityBlocks)
  .then(symlinkAuthorityCannotMasqueradeAsParent)
  .then(foreignReturnCannotBeApproved)
  .then(palmierAuthorityCannotAppearBeforePromotion)
  .then(() => console.log("ask-edit-authority-races.test.ts: passed"))
  .catch((error) => { console.error(error); process.exitCode = 1; });
