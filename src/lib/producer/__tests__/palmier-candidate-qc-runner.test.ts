import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  runCandidateQc,
  runLiveBuildCandidateQc,
  type QcDependencies,
} from "../../../app/api/producer/palmier/candidate-qc/runner";
import type { PalmierNativeQcAuthority } from "../../../app/api/producer/ai-edit/palmier-native-authority";
import type { PalmierLiveBuildQcAuthority } from "../../../app/api/producer/live-build/authority";

function sha(value: string | Buffer): string {
  return createHash("sha256").update(value).digest("hex");
}

function fixture(dir: string, suffix = "initial"): {
  authority: PalmierNativeQcAuthority;
  receipt: Record<string, unknown>;
} {
  const request = "Tighten the explicit filler word";
  const requestHash = sha(request);
  const parent = {
    schemaVersion: 1, authority: "palmier", projectId: "project-1",
    timelineId: "parent-1", fingerprint: "a".repeat(64),
    timeline: { id: "parent-1", totalFrames: 100, tracks: [] },
  };
  const nativePlan = {
    schemaVersion: 1, lanes: ["cuts"],
    operations: [{ tool: "remove_words", args: { words: ["um"] }, reason: "Requested" }],
    requestHash,
    parent: { projectId: "project-1", timelineId: "parent-1", fingerprint: "a".repeat(64) },
  };
  mkdirSync(dir, { recursive: true });
  const inputPath = path.join(dir, `native-input-${suffix}.json`);
  writeFileSync(inputPath, `${JSON.stringify({
    schemaVersion: 1, kind: "palmier-native-candidate-input",
    request: { text: request, hash: requestHash }, controller: { lanes: ["cuts"] },
    parent, nativePlan,
  }, null, 2)}\n`);
  const captureId = `native-test-${suffix}`;
  const authority: PalmierNativeQcAuthority = {
    schemaVersion: 1, requestHash, captureId,
    nativeInput: {
      path: inputPath, hash: sha(readFileSync(inputPath)), requestTextHash: requestHash,
      lanes: ["cuts"], parent: nativePlan.parent, nativePlanHash: "b".repeat(64),
    },
    ctx: {
      dir, scope: "produced", planPath: inputPath,
      manifestPath: path.join(dir, "asset_manifest.json"), transcriptsDir: dir,
      doctrine: { runId: captureId, doctrineHash: "c".repeat(64),
        snapshotPath: path.join(dir, "doctrine.json"), files: {} },
      pipeline: { schemaVersion: 1, runId: captureId, digest: "d".repeat(64),
        snapshotRoot: dir, lockPath: path.join(dir, "pipeline.json"), files: [] },
    },
  };
  const exportPath = path.join(dir, "palmier.candidate.mp4");
  const auditPath = path.join(dir, "palmier.native-audit.json");
  const framePath = path.join(dir, "frame.png");
  writeFileSync(exportPath, "export");
  writeFileSync(framePath, "frame");
  writeFileSync(auditPath, JSON.stringify({ checks: [{ name: "canvas", status: "pass" }] }));
  const receipt = {
    schemaVersion: 1, status: "deterministic-passed",
    candidate: { fingerprint: sha(suffix) },
    export: { path: exportPath, hash: sha("export") },
    authority: { inputDigest: "f".repeat(64) },
    deterministic: {
      digest: "1".repeat(64), auditPath,
      frames: [{ path: framePath, hash: sha("frame") }],
    },
  };
  return { authority, receipt };
}

const ISSUE = {
  code: "QC_COMPOSITION",
  severity: "major" as const,
  lane: "graphics",
  message: "A panel is visibly clipped.",
  evidence: ["frame.png"],
  requiredAction: "Keep the panel inside the delivery canvas.",
};

function liveFixture(dir: string): {
  authority: PalmierLiveBuildQcAuthority;
  receipt: Record<string, unknown>;
} {
  const base = fixture(dir, "live");
  const planPath = path.join(dir, "live-edit-plan.json");
  const journalPath = path.join(dir, ".palmier-live-build.jsonl");
  writeFileSync(planPath, JSON.stringify({ planVersion: 1,
    target: { mode: "longform" }, cutTrack: [] }));
  writeFileSync(journalPath, `${JSON.stringify({
    event: "palmier_op_result", status: "applied",
  })}\n`);
  const captureId = "live-test-capture";
  const request = `Execute approved Producer plan ${sha(readFileSync(planPath))} exactly in the governed Palmier candidate.`;
  const requestHash = sha(request);
  const parent = base.authority.nativeInput.parent;
  const inputPath = path.join(dir, "live-build-input.json");
  writeFileSync(inputPath, JSON.stringify({
    schemaVersion: 1, kind: "palmier-live-build-input", captureId,
    request: { text: request, hash: requestHash },
    controller: { lanes: ["cuts"] }, parent,
    plan: { path: planPath, hash: sha(readFileSync(planPath)) },
    journal: { path: journalPath, hash: sha(readFileSync(journalPath)),
      operationCount: 1 },
    planningReviews: [], sessionId: "session-live",
  }));
  return { receipt: base.receipt, authority: {
    schemaVersion: 1, kind: "palmier-live-build-qc-authority",
    requestHash, captureId,
    liveInput: { path: inputPath, hash: sha(readFileSync(inputPath)),
      planHash: sha(readFileSync(planPath)),
      journalHash: sha(readFileSync(journalPath)), lanes: ["cuts"], parent,
      operationCount: 1, sessionId: "session-live" },
    ctx: { ...base.authority.ctx, planPath },
  } };
}

async function liveFailureDoesNotReplace(dir: string): Promise<void> {
  const current = liveFixture(dir);
  let attempts = 0;
  let repairs = 0;
  const dependencies: QcDependencies = {
    authority: () => ({ cli: "pinned-native-qc.py", payload: current.authority }),
    cli: async (_dir, action) => {
      if (action === "prepare") attempts += 1;
      if (action === "audit") writeFileSync(
        path.join(dir, "palmier.native-qc.json"), JSON.stringify(current.receipt),
      );
      return { ok: true, status: action };
    },
    review: async (_dir, lens, evidence) => ({
      schemaVersion: 1, stage: "rendered", lens, ...evidence.binding,
      verdict: lens === "composition" ? "revise" : "pass",
      materialIssues: lens === "composition" ? [ISSUE] : [],
    }),
    repair: async () => { repairs += 1; },
  };
  await assert.rejects(
    runLiveBuildCandidateQc(dir, () => {}, dependencies),
    /First issue: A panel is visibly clipped/,
  );
  assert.equal(attempts, 1, "retained-session builds get one exact-candidate QC attempt");
  assert.equal(repairs, 0, "live QC must never create a wholesale replacement");
}

async function repairScenario(dir: string, failReplacement: boolean): Promise<void> {
  let current = fixture(dir, "first");
  let attempt = 0;
  let repairs = 0;
  let exhaustedRejections = 0;
  const dependencies: QcDependencies = {
    authority: () => ({ cli: "pinned-native-qc.py", payload: current.authority }),
    cli: async (_dir, action) => {
      if (action === "prepare") attempt += 1;
      if (action === "audit") {
        writeFileSync(path.join(dir, "palmier.native-qc.json"), JSON.stringify(current.receipt));
      }
      return { ok: true, status: action };
    },
    review: async (_dir, lens, evidence) => {
      const fail = lens === "composition" && (attempt === 1 || failReplacement);
      return {
        schemaVersion: 1, stage: "rendered", lens, ...evidence.binding,
        verdict: fail ? "revise" : "pass",
        materialIssues: fail ? [ISSUE] : [],
      };
    },
    repair: async () => {
      repairs += 1;
      current = fixture(dir, "replacement");
    },
    rejectFailed: async () => {
      exhaustedRejections += 1;
      return { archivePath: path.join(dir, "archive"), evidence: {} as never };
    },
  };
  const events: Array<Record<string, unknown>> = [];
  if (failReplacement) {
    await assert.rejects(
      runCandidateQc(dir, (event) => events.push(event), dependencies),
      /stopped after one governed replacement/,
    );
    assert.equal(repairs, 1, "only one replacement may be created");
    assert.equal(exhaustedRejections, 1, "the failed replacement must be archived");
    assert.equal(attempt, 2, "no third candidate QC attempt may start");
    assert.ok(events.some((event) => event.step === "repair_exhausted"));
    return;
  }
  const result = await runCandidateQc(dir, (event) => events.push(event), dependencies);
  assert.equal(result.status, "finalize");
  assert.equal(repairs, 1);
  assert.equal(exhaustedRejections, 0);
  assert.equal(attempt, 2);
  assert.ok(events.some((event) => event.step === "repair"));
  assert.ok(events.some((event) => event.step === "replacement"));
}

async function main(): Promise<void> {
  const dir = mkdtempSync(path.join(os.tmpdir(), "sniper-candidate-qc-runner-"));
  try {
    const { authority, receipt } = fixture(dir);
    const calls: string[] = [];
    const dependencies: QcDependencies = {
      authority: () => ({ cli: "pinned-native-qc.py", payload: authority }),
      cli: async (_dir, action, inputPath) => {
        calls.push(action);
        if (action === "audit") {
          writeFileSync(path.join(dir, "palmier.native-qc.json"), JSON.stringify(receipt));
        }
        if (action === "finalize") {
          const value = JSON.parse(readFileSync(inputPath!, "utf8")) as {
            schemaVersion: number; reviews: Array<Record<string, unknown>>;
          };
          assert.equal(value.schemaVersion, 1);
          assert.equal(value.reviews.length, 2);
          const exact = ["candidateFingerprint", "deterministicDigest", "exportHash",
            "inputAuthorityDigest", "lens", "materialIssues", "schemaVersion", "stage", "verdict"];
          for (const review of value.reviews) assert.deepEqual(Object.keys(review).sort(), exact);
          return { ok: true, status: "qc-approved" };
        }
        return { ok: true, status: action };
      },
      review: async (_dir, lens, evidence) => ({
        schemaVersion: 1, stage: "rendered", lens,
        ...evidence.binding, verdict: "pass", materialIssues: [],
      }),
    };
    const events: Array<Record<string, unknown>> = [];
    const result = await runCandidateQc(dir, (event) => events.push(event), dependencies);
    assert.equal(result.status, "qc-approved");
    assert.deepEqual(calls, ["prepare", "audit", "finalize"]);
    assert.deepEqual(events.map((event) => event.step),
      ["prepare", "audit", "rendered_reviews", "approval"]);
    await repairScenario(path.join(dir, "repair-pass"), false);
    await repairScenario(path.join(dir, "repair-exhausted"), true);
    await liveFailureDoesNotReplace(path.join(dir, "live-failure"));
    console.log("palmier-candidate-qc-runner.test.ts: all assertions passed");
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

void main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
