import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  runSurgicalGovernance,
  type SurgicalGovernanceDependencies,
} from "../../../app/api/producer/ai-edit/surgical-governance";
import type { GateBundleInput, GateBundleVerdict, PlanningGateId } from
  "../../../app/api/producer/auto-edit/planning-gate-contract";
import type { AutoEditCtx } from
  "../../../app/api/producer/auto-edit/stream";
import type { BoundTemplateUsage } from "../../server/template-usage-history";

const SHA = "a".repeat(64);

function passingVerdict(): GateBundleVerdict {
  const gate = (id: PlanningGateId) => ({
    gate: id, ok: true, errors: [], warnings: [], exit: 0,
  });
  return {
    ok: true, errors: [], warnings: [], processesStopped: true,
    gates: {
      operatorIntent: gate("operator_intent"),
      transcriptCut: gate("transcript_cut"),
      visualPlanApplication: gate("visual_plan_application"),
      planLint: gate("plan_lint"),
      hookContract: gate("hook_contract"),
      templateUsage: gate("template_usage"),
      claimsContract: gate("claims_contract"),
      compSize: gate("comp_size"),
      geometryFeasibility: gate("geometry_feasibility"),
      referenceLint: null,
    },
  };
}

function fakeUsage(dir: string): BoundTemplateUsage {
  const core = {
    schemaVersion: 1 as const,
    kind: "producer-template-usage-history" as const,
    mode: "longform" as const,
    windowProjects: 8,
    projectCount: 0,
    projects: [],
    counts: {},
    overusedKinds: [],
    policy: { minProjects: 3, minProjectShare: 0.5 },
  };
  return {
    authority: { schemaVersion: 1, path: path.join(dir, "usage.json"), digest: SHA },
    history: { ...core, digest: SHA },
  };
}

function fixture(): { root: string; input: Parameters<typeof runSurgicalGovernance>[0]; ctx: AutoEditCtx } {
  const root = mkdtempSync(path.join(os.tmpdir(), "sniper-surgical-visual-"));
  const producer = path.join(root, "producer");
  const source = path.join(root, "source");
  mkdirSync(producer);
  mkdirSync(source);
  const planPath = path.join(producer, "edit_plan.json");
  const manifestPath = path.join(source, "asset_manifest.json");
  writeFileSync(planPath, "{}\n");
  writeFileSync(manifestPath, '{"sources":[]}\n');
  const ctx: AutoEditCtx = {
    dir: producer, scope: "produced", visualPlanRequiredVersion: 1,
    intent: { mode: "longform", lanes: {} }, planPath, manifestPath, transcriptsDir: source,
  };
  return {
    root, ctx,
    input: {
      dir: producer, planPath, manifestPath, transcriptsDir: source,
      scope: { lanes: ["graphics"] },
    },
  };
}

function dependencies(
  ctx: AutoEditCtx,
  runGates: NonNullable<SurgicalGovernanceDependencies["runGates"]>,
): SurgicalGovernanceDependencies {
  return {
    prepareReview: () => ({ ctx, resume: false, bootstrapPlanHash: SHA }),
    captureUsage: () => fakeUsage(ctx.dir),
    runGates,
  };
}

async function requiredMissingFailsBeforeBuyer(): Promise<void> {
  const item = fixture();
  let buyerReached = false;
  try {
    await assert.rejects(
      () => runSurgicalGovernance(item.input, dependencies(item.ctx, async () => {
        buyerReached = true;
        return passingVerdict();
      })),
      /required VISUAL-PLAN\.json is missing/,
    );
    assert.equal(buyerReached, false);
  } finally {
    rmSync(item.root, { recursive: true, force: true });
  }
}

async function buyerReceivesExactVisualAuthority(): Promise<void> {
  const item = fixture();
  let received: GateBundleInput | undefined;
  const visualPlan = { path: path.join(item.ctx.dir, "VISUAL-PLAN.json"),
    byteHash: SHA, visualPlanSha256: "b".repeat(64) };
  const project = {
    mode: "long" as const, aspect: "16:9" as const, durationFrames: 300,
    fps: { numerator: 30 as const, denominator: 1 as const },
    intentSha256: "c".repeat(64), acceptedProgramSha256: "d".repeat(64),
    transcriptSha256: "e".repeat(64),
  };
  try {
    const deps = dependencies(item.ctx, async (input) => {
      received = input;
      return passingVerdict();
    });
    deps.visualAuthority = () => ({
      visualPlanRequired: true, visualPlan,
      visualPlanProject: project, visualPlanCatalogPinSha256: "f".repeat(64),
    });
    await runSurgicalGovernance(item.input, deps);
    assert.equal(received?.visualPlanRequired, true);
    assert.deepEqual(received?.visualPlan, visualPlan);
    assert.deepEqual(received?.visualPlanProject, project);
    assert.equal(received?.visualPlanCatalogPinSha256, "f".repeat(64));
  } finally {
    rmSync(item.root, { recursive: true, force: true });
  }
}

async function main(): Promise<void> {
  await requiredMissingFailsBeforeBuyer();
  await buyerReceivesExactVisualAuthority();
  console.log("surgical-governance-visual-plan.test.ts: all assertions passed");
}

main().catch((error: unknown) => {
  console.error(error);
  process.exitCode = 1;
});
