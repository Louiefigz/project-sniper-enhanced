import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import {
  chmodSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  realpathSync,
  rmSync,
  statSync,
  writeFileSync,
} from "node:fs";
import os from "node:os";
import path from "node:path";
import { pythonInterpreter } from "../../../app/api/_lib/spawn-python";
import { buildGateFixPrompt } from
  "../../../app/api/producer/auto-edit/revision-prompt";
import {
  assertRevisionPlanUnchanged,
  prepareRevisionStaging,
} from "../../../app/api/producer/auto-edit/revision-staging";
import type { ProducerReview } from
  "../../../app/api/producer/auto-edit/review-contract";
import type { AutoEditCtx } from "../../../app/api/producer/auto-edit/stream";
import { resolveVisualPlanBinding } from "../../server/visual-plan-binding";

const REVIEW: ProducerReview = {
  schemaVersion: 1,
  stage: "plan",
  verdict: "revise",
  summary: "The visual-plan application is missing or malformed.",
  materialIssues: [{
    code: "GATE_VISUAL_PLAN_APPLICATION",
    severity: "major",
    lane: "graphics",
    message: "Map every selected visual-plan decision to its executable plan row.",
    evidence: ["visual_plan_application: missing application"],
    requiredAction: "Repair visualPlanApplication without changing the allocation.",
  }],
  findings: [],
};

function writeVisualPlan(file: string): void {
  const code = [
    "import json,sys",
    "from _visual_plan_fixture import candidate,materialize_plan_pins,opportunity,visual_plan",
    "from planner.visual_plan_allocator import allocate_visual_plan",
    "value=visual_plan(opportunity('opp:one',0,[candidate('candidate:one')]))",
    "value=materialize_plan_pins(value,sys.argv[2])",
    "open(sys.argv[1],'w').write(json.dumps(allocate_visual_plan(value)))",
  ].join("\n");
  execFileSync(pythonInterpreter(), ["-B", "-c", code, file,
    path.join(path.dirname(file), "visual-plan-pins")], {
    cwd: path.join(process.cwd(), "scripts/producer"),
    env: { ...process.env, PYTHONPATH: ".:tests", PYTHONDONTWRITEBYTECODE: "1" },
  });
}

function fixture(application?: unknown): { root: string; ctx: AutoEditCtx } {
  const root = mkdtempSync(path.join(os.tmpdir(), "sniper-revision-visual-plan-"));
  const producer = path.join(root, "producer");
  const source = path.join(root, "source");
  mkdirSync(producer, { recursive: true });
  mkdirSync(source, { recursive: true });
  const planPath = path.join(producer, "edit_plan.json");
  const plan: Record<string, unknown> = { planVersion: 1, cutTrack: [] };
  if (application !== undefined) plan.visualPlanApplication = application;
  writeFileSync(planPath, JSON.stringify(plan));
  const manifestPath = path.join(source, "asset_manifest.json");
  writeFileSync(manifestPath, '{"sources":[]}');
  const visualPath = path.join(producer, "VISUAL-PLAN.json");
  writeVisualPlan(visualPath);
  const visualPlan = resolveVisualPlanBinding(visualPath);
  assert.ok(visualPlan);
  return {
    root,
    ctx: {
      dir: producer,
      scope: "produced",
      intent: { mode: "longform" },
      planPath,
      manifestPath,
      transcriptsDir: source,
      visualPlan,
    },
  };
}

function testReadableRepairAuthority(application?: unknown): void {
  const fix = fixture(application);
  const staging = prepareRevisionStaging(fix.ctx);
  try {
    const source = fix.ctx.visualPlan!;
    const staged = staging.ctx.visualPlan!;
    assert.notEqual(staged.path, source.path);
    assert.equal(path.dirname(staged.path), realpathSync(staging.ctx.dir));
    assert.equal(readFileSync(staged.path, "utf8"), readFileSync(source.path, "utf8"));
    assert.equal(statSync(staged.path).mode & 0o777, 0o400);
    assert.deepEqual(
      { ...staged, path: source.path },
      source,
      "staging must preserve every execution fingerprint while changing only the path",
    );
    const prompt = buildGateFixPrompt(staging.ctx, REVIEW, 1);
    assert.ok(prompt.includes(staged.path));
    assert.match(prompt, /immutable staged visual-plan authority/);
    assert.match(prompt, /never edit or replace the visual plan/i);
    assert.doesNotThrow(() => JSON.parse(readFileSync(staged.path, "utf8")));
    assert.doesNotThrow(() => assertRevisionPlanUnchanged(staging));
  } finally {
    staging.dispose();
    rmSync(fix.root, { recursive: true, force: true });
  }
}

function testStagedPlanCannotDrift(): void {
  const fix = fixture();
  const staging = prepareRevisionStaging(fix.ctx);
  try {
    const stagedPath = staging.ctx.visualPlan!.path;
    chmodSync(stagedPath, 0o600);
    writeFileSync(stagedPath, `${readFileSync(stagedPath, "utf8")} `);
    assert.throws(
      () => assertRevisionPlanUnchanged(staging),
      /changed after planning context resolution|staged VISUAL-PLAN\.json changed/,
    );
  } finally {
    staging.dispose();
    rmSync(fix.root, { recursive: true, force: true });
  }
}

function testBoundSourceCannotDrift(): void {
  const fix = fixture({ decisions: [] });
  const staging = prepareRevisionStaging(fix.ctx);
  try {
    const sourcePath = fix.ctx.visualPlan!.path;
    writeFileSync(sourcePath, `${readFileSync(sourcePath, "utf8")} `);
    assert.throws(
      () => assertRevisionPlanUnchanged(staging),
      /VISUAL-PLAN\.json changed after planning context resolution/,
    );
  } finally {
    staging.dispose();
    rmSync(fix.root, { recursive: true, force: true });
  }
}

testReadableRepairAuthority();
testReadableRepairAuthority({ decisions: "malformed" });
testStagedPlanCannotDrift();
testBoundSourceCannotDrift();
console.log("revision visual-plan staging tests passed");
