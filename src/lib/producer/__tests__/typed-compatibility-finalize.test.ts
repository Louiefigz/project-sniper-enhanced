import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import {
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  beginSurgicalReview,
  finalizeSurgicalEdit,
  SURGICAL_REVIEW_FILE,
} from "../../../app/api/producer/ai-edit/finalize";
import type { ProducerReview } from
  "../../../app/api/producer/auto-edit/review-contract";
import { templateUsageApprovalPath } from
  "../../../lib/server/template-usage-approval";

const review: ProducerReview = {
  schemaVersion: 1, stage: "plan", verdict: "pass",
  summary: "Only the requested line-swap copy changed.",
  materialIssues: [], findings: [],
};

function sha256(value: string): string {
  return createHash("sha256").update(value).digest("hex");
}

function plan(text: string, outStart = 1): Record<string, unknown> {
  return {
    planVersion: 7,
    target: { mode: "longform" },
    cutTrack: [{ sourceId: "raw", start: 0, end: 10 }],
    graphicsTrack: [{
      id: "g-00000001", kind: "line-swap",
      outStart, outEnd: 3, spec: { lineA: text, lineB: "TEST second line" },
    }],
  };
}

function fixture(name: string): {
  dir: string;
  authority: string;
  candidate: string;
  manifest: string;
  parentText: string;
} {
  const dir = mkdtempSync(path.join(os.tmpdir(), `sniper-typed-${name}-`));
  const authority = path.join(dir, "edit_plan.json");
  const candidate = path.join(dir, "candidate.json");
  const manifest = path.join(dir, "asset_manifest.json");
  const parentText = `${JSON.stringify(plan("Before"), null, 2)}\n`;
  writeFileSync(authority, parentText);
  writeFileSync(manifest, JSON.stringify({ sources: [] }));
  return { dir, authority, candidate, manifest, parentText };
}

function input(item: ReturnType<typeof fixture>) {
  return {
    provider: "codex" as const,
    dir: item.dir,
    planPath: item.candidate,
    authorityPlanPath: item.authority,
    manifestPath: item.manifest,
    transcriptsDir: item.dir,
    request: "Change the statement card text to After",
    scope: { lanes: ["graphics" as const] },
    originalPlanText: item.parentText,
    parentPlanHash: sha256(item.parentText),
  };
}

async function catalogCopyUsesCurrentReviewPath(): Promise<void> {
  const item = fixture("pass");
  try {
    writeFileSync(item.candidate, JSON.stringify(plan("After")));
    beginSurgicalReview(item.dir, { lanes: ["graphics"] });
    const result = await finalizeSurgicalEdit(input(item), {
      governance: async () => ({ warnings: [] }),
      critic: async () => review,
    });
    assert.equal(result.typedCompatibility, undefined);
    const committed = JSON.parse(readFileSync(item.authority, "utf8"));
    assert.equal(committed.planVersion, 8);
    assert.equal(committed.graphicsTrack[0].spec.lineA, "After");
    const marker = JSON.parse(readFileSync(
      path.join(item.dir, SURGICAL_REVIEW_FILE), "utf8",
    ));
    assert.equal(marker.typedCompatibility, undefined);
  } finally {
    rmSync(item.dir, { recursive: true, force: true });
  }
}

async function retiredCandidateCannotFallBack(): Promise<void> {
  const item = fixture("retired");
  try {
    const candidate = plan("After") as { graphicsTrack: Array<{ kind: string }> };
    candidate.graphicsTrack[0].kind = "statement-card";
    writeFileSync(item.candidate, JSON.stringify(candidate));
    beginSurgicalReview(item.dir, { lanes: ["graphics"] });
    await assert.rejects(finalizeSurgicalEdit(input(item), {
      governance: async () => { throw new Error("must refuse before governance"); },
      critic: async () => { throw new Error("must refuse before critic"); },
    }), /retired/);
    assert.equal(readFileSync(item.authority, "utf8"), item.parentText);
  } finally {
    rmSync(item.dir, { recursive: true, force: true });
  }
}

async function sidecarFailureRestoresPriorReceipt(): Promise<void> {
  const item = fixture("sidecar-rollback");
  const receiptPath = templateUsageApprovalPath(item.dir);
  const previous = Buffer.from("exact prior template approval\n");
  try {
    writeFileSync(item.candidate, JSON.stringify(plan("After")));
    writeFileSync(receiptPath, previous);
    beginSurgicalReview(item.dir, { lanes: ["graphics"] });
    await assert.rejects(finalizeSurgicalEdit(input(item), {
      governance: async () => ({
        warnings: [],
        templateUsage: {
          schemaVersion: 1,
          path: path.join(item.dir, "template-usage.json"),
          digest: "a".repeat(64),
        },
        verdict: {
          gates: {
            templateUsage: { ok: true },
            operatorIntent: { ok: true },
          },
        } as never,
      }),
      critic: async () => review,
      templateApproval: () => {
        writeFileSync(receiptPath, "candidate template approval\n");
      },
      afterSidecars: () => {
        throw new Error("injected failure after sidecar promotion");
      },
    }), /injected failure after sidecar promotion/);
    assert.deepEqual(readFileSync(receiptPath), previous);
    assert.equal(readFileSync(item.authority, "utf8"), item.parentText);
  } finally {
    rmSync(item.dir, { recursive: true, force: true });
  }
}

async function cutPublicationFailureRestoresPriorReceipt(): Promise<void> {
  const item = fixture("cut-sidecar-rollback");
  const receiptPath = path.join(item.dir, ".sniper-cut-approval.json");
  const previous = Buffer.from("exact prior cut approval\n");
  try {
    writeFileSync(item.candidate, JSON.stringify(plan("After")));
    writeFileSync(receiptPath, previous);
    beginSurgicalReview(item.dir, { lanes: ["graphics"] });
    await assert.rejects(finalizeSurgicalEdit(input(item), {
      governance: async () => ({
        warnings: [],
        cutApproval: {
          path: receiptPath,
          text: "candidate cut approval\n",
        },
      }),
      critic: async () => review,
      cutApprovalWriter: (destination, data) => {
        writeFileSync(destination, data);
        throw new Error("injected failure after cut receipt publication");
      },
    }), /injected failure after cut receipt publication/);
    assert.deepEqual(readFileSync(receiptPath), previous);
    assert.equal(readFileSync(item.authority, "utf8"), item.parentText);
  } finally {
    rmSync(item.dir, { recursive: true, force: true });
  }
}

catalogCopyUsesCurrentReviewPath()
  .then(retiredCandidateCannotFallBack)
  .then(sidecarFailureRestoresPriorReceipt)
  .then(cutPublicationFailureRestoresPriorReceipt)
  .then(() => console.log("typed-compatibility-finalize.test.ts: passed"))
  .catch((error) => {
    console.error(error);
    process.exitCode = 1;
  });
