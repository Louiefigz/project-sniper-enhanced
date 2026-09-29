import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { existsSync, linkSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, unlinkSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { claudeArgs, runAuthoring } from
  "@/app/api/producer/auto-edit/authoring";
import {
  captureInitialAuthoring,
  prepareInitialAuthoringStaging,
  promoteCapturedInitialAuthoring,
} from
  "@/app/api/producer/auto-edit/initial-authoring-staging";
import { pythonInterpreter } from "@/app/api/_lib/spawn-python";
import { projectVisualPlanBinding } from "@/lib/server/visual-plan-binding";
import { canonicalJsonSha256, fileSha256 } from "@/lib/server/auto-edit-hash";
import type { AutoEditCtx } from "@/app/api/producer/auto-edit/stream";
import { writeAdmittedMediaManifest } from "./_visual-plan-media-manifest-fixture";

interface Fixture {
  root: string;
  ctx: AutoEditCtx;
}

function fixture(): Fixture {
  const root = realpathSync(mkdtempSync(
    path.join(os.tmpdir(), "sniper-authoring-isolation-test-"),
  ));
  const producer = path.join(root, "producer");
  const source = path.join(root, "source");
  mkdirSync(producer);
  mkdirSync(source);
  const planPath = path.join(producer, "edit_plan.json");
  const manifestPath = path.join(source, "asset_manifest.json");
  writeFileSync(planPath, JSON.stringify({
    planVersion: 1, sentinel: "original",
    target: { mode: "short", scope: "trim", durationTargetS: 1 },
    cutTrack: [{ sourceId: "source:one", start: 0, end: 1, speed: 1,
      rationale: "Keep one complete source-grounded sentence." }],
    cutDecisions: { schemaVersion: 1, removals: [] },
  }));
  writeFileSync(path.join(source, "transcript.json"), JSON.stringify({
    transcript: [{ start: 0, end: 1, text: "Hello world",
      words: [{ word: "Hello", start: 0, end: 0.45 },
        { word: "world", start: 0.5, end: 0.95 }] }],
  }));
  const mediaPath = path.join(source, "source.mp4");
  writeFileSync(mediaPath, "TEST source metadata authority bytes");
  writeAdmittedMediaManifest(manifestPath, { sources: [{
    id: "source:one", path: mediaPath, transcriptPath: "transcript.json",
  }] });
  return {
    root,
    ctx: {
      dir: producer, scope: "trim", intent: { mode: "short" },
      planPath, manifestPath, transcriptsDir: source,
    },
  };
}

test("successful initial authoring promotes only the isolated plan", async () => {
  const item = fixture();
  let authoringDir = "";
  try {
    const result = await runAuthoring(item.ctx, () => {}, {
      provider: () => "codex",
      codex: async options => {
        authoringDir = options.cwd!;
        assert.notEqual(authoringDir, item.ctx.dir);
        assert.equal(path.dirname(authoringDir), os.tmpdir());
        assert.ok(options.prompt.includes(path.join(authoringDir, "edit_plan.json")));
        assert.equal(options.prompt.includes(`${item.ctx.dir}/edit_plan.json`), false);
        writeFileSync(path.join(authoringDir, "edit_plan.json"),
          '{"planVersion":2,"sentinel":"promoted"}\n');
        writeFileSync(path.join(authoringDir, "unapproved-scratch.json"), "{}\n");
        return { message: "AUTHORED ok segments=1 graphics=0", stderr: "", ms: 1 };
      },
    }, { stage: "cut" });
    assert.equal(result.code, 0);
    assert.equal(JSON.parse(readFileSync(item.ctx.planPath, "utf8")).sentinel, "promoted");
    assert.equal(existsSync(path.join(item.ctx.dir, "unapproved-scratch.json")), false);
    assert.equal(existsSync(authoringDir), false);
  } finally {
    rmSync(item.root, { recursive: true, force: true });
  }
});

function writePresenterPlan(authoringDir: string, allocate = true): void {
  const context = path.join(authoringDir, "VISUAL-PLAN-CONTEXT.json");
  const output = path.join(authoringDir, "VISUAL-PLAN.json");
  const code = [
    "import json,sys",
    "from tests._visual_plan_fixture import candidate,opportunity,visual_plan,reseal_search_authority",
    "ctx=json.load(open(sys.argv[1]))",
    "authority=json.load(open(ctx['transcriptAuthority']['path']))",
    "word=authority['words'][0]",
    "opp=opportunity('opp:one',0,[candidate('candidate:one','presenter')])",
    "opp['transcriptEvidence']={'text':word['text'],'wordIds':[word['id']]}",
    "value=visual_plan(opp)",
    "value['project']=ctx['project']",
    "value['catalogPin']=ctx['catalogPin']",
    "value['transcriptAuthority']=ctx['transcriptAuthority']",
    "value['mediaAuthority']=ctx['mediaAuthority']",
    "value['relatedUsageAuthority']=ctx['relatedUsageAuthority']",
    "value['relatedUsage']=ctx['relatedUsage']",
    "reseal_search_authority(value)",
    "open(sys.argv[2],'w').write(json.dumps(value))",
  ].join("\n");
  execFileSync(pythonInterpreter(), ["-B", "-c", code, context, output], {
    cwd: path.join(process.cwd(), "scripts/producer"),
    env: { NODE_ENV: "production", PYTHONDONTWRITEBYTECODE: "1",
      PYTHONUTF8: "1", PYTHONPATH: "." },
  });
  if (!allocate) return;
  const cli = path.join(process.cwd(), "scripts/producer/planner/visual_plan_cli.py");
  const allocated = execFileSync(pythonInterpreter(), ["-B", cli, "allocate", output], {
    encoding: "utf8", env: { NODE_ENV: "production",
      PYTHONDONTWRITEBYTECODE: "1", PYTHONUTF8: "1" },
  });
  writeFileSync(output, allocated);
}

test("visual authoring relocates controller pins and binding before promotion", async () => {
  const item = fixture();
  item.ctx.scope = "produced";
  item.ctx.visualPlanRequiredVersion = 1;
  item.ctx.intent = { mode: "short", lanes: {} };
  const usagePath = path.join(item.ctx.dir,
    ".sniper-learning/runs/unbound/template-usage.json");
  mkdirSync(path.dirname(usagePath), { recursive: true });
  writeFileSync(usagePath, "{}\n");
  item.ctx.templateUsage = {
    schemaVersion: 1, path: usagePath, digest: "a".repeat(64),
  };
  try {
    let calls = 0;
    let visualAuthoringDir = "";
    const result = await runAuthoring(item.ctx, () => {}, {
      provider: () => "codex",
      codex: async options => {
        const work = options.cwd!;
        calls += 1;
        if (calls === 1) {
          visualAuthoringDir = work;
          assert.match(options.prompt, /route-neutral CREATIVE DIRECTOR/);
          writePresenterPlan(work, false);
          return { message: "AUTHORED ok segments=1 graphics=0", stderr: "", ms: 1 };
        }
        assert.match(options.prompt, /VISUAL\/RETENTION PRODUCER/);
        const plan = JSON.parse(readFileSync(path.join(work, "edit_plan.json"), "utf8"));
        plan.visualPlanApplication = {
          schemaVersion: 1, route: "ordinary",
          visualPlan: { byteHash: "0".repeat(64), visualPlanSha256: "0".repeat(64) },
          decisions: [{ opportunityId: "opp:one", candidateId: "candidate:one",
            modality: "presenter", execution: "presenter-hold",
            timing: { startFrame: 0, endFrameExclusive: 24 },
            elements: [{ lane: "cutTrack", index: 0 }],
            binding: { kind: "presenter", element: { lane: "cutTrack", index: 0 },
              sourceId: "source:one",
              sourceRange: { startFrame: 0, endFrameExclusive: 30 },
              outputRange: { startFrame: 0, endFrameExclusive: 24 },
              implementationSha256: canonicalJsonSha256(plan.cutTrack[0]) } }],
        };
        writeFileSync(path.join(work, "edit_plan.json"), JSON.stringify(plan));
        return { message: "AUTHORED ok segments=1 graphics=0", stderr: "", ms: 1 };
      },
    });
    assert.equal(result.code, 0, result.errTail);
    assert.equal(calls, 2);
    const binding = projectVisualPlanBinding(item.ctx.dir)!;
    const plan = JSON.parse(readFileSync(item.ctx.planPath, "utf8"));
    assert.deepEqual(plan.visualPlanApplication.visualPlan, {
      byteHash: binding.byteHash, visualPlanSha256: binding.visualPlanSha256,
    });
    const visual = JSON.parse(readFileSync(binding.path, "utf8"));
    assert.equal(visual.catalogPin.indexPath,
      path.join(item.ctx.dir, "CATALOG-AUTHORITY.json"));
    assert.equal(visual.transcriptAuthority.path,
      path.join(item.ctx.dir, "TRANSCRIPT-AUTHORITY.json"));
    assert.equal(visual.mediaAuthority.path,
      path.join(item.ctx.dir, "MEDIA-AUTHORITY.json"));
    assert.equal(visual.relatedUsageAuthority.path,
      path.join(item.ctx.dir, "RELATED-USAGE-AUTHORITY.json"));
    assert.deepEqual(visual.relatedUsage, []);
    assert.match(visual.searchAuthority.path,
      new RegExp(`^${item.ctx.dir.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}/VISUAL-SEARCH-RESULTS\\.`));
    const search = JSON.parse(readFileSync(visual.searchAuthority.path, "utf8"));
    assert.match(search.query.path,
      new RegExp(`^${item.ctx.dir.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}/VISUAL-SEARCH\\.`));
    assert.equal(existsSync(search.query.path), true);
    assert.equal(existsSync(visualAuthoringDir), false);
    const cli = path.join(process.cwd(), "scripts/producer/planner/visual_plan_cli.py");
    execFileSync(pythonInterpreter(), ["-B", cli, "validate", binding.path], {
      cwd: path.join(process.cwd(), "scripts/producer"),
      env: { NODE_ENV: "production", PYTHONDONTWRITEBYTECODE: "1",
        PYTHONUTF8: "1", PYTHONPATH: "." },
    });
  } finally {
    rmSync(item.root, { recursive: true, force: true });
  }
});

test("failed authoring discards every staged write", async () => {
  const item = fixture();
  let authoringDir = "";
  try {
    const before = readFileSync(item.ctx.planPath, "utf8");
    const result = await runAuthoring(item.ctx, () => {}, {
      provider: () => "codex",
      codex: async options => {
        authoringDir = options.cwd!;
        writeFileSync(path.join(authoringDir, "edit_plan.json"),
          '{"planVersion":9,"sentinel":"must-not-promote"}\n');
        return { message: "CUT_AUTHORING_BLOCKED test", stderr: "", ms: 1 };
      },
    }, { stage: "cut" });
    assert.equal(result.blocked?.reason, "test");
    assert.equal(readFileSync(item.ctx.planPath, "utf8"), before);
    assert.equal(existsSync(authoringDir), false);
  } finally {
    rmSync(item.root, { recursive: true, force: true });
  }
});

test("promotion rejects concurrent project mutation", async () => {
  const item = fixture();
  try {
    const result = await runAuthoring(item.ctx, () => {}, {
      provider: () => "codex",
      codex: async options => {
        writeFileSync(path.join(options.cwd!, "edit_plan.json"),
          '{"planVersion":2,"sentinel":"candidate"}\n');
        writeFileSync(item.ctx.planPath, '{"planVersion":3,"sentinel":"external"}\n');
        return { message: "AUTHORED ok segments=1 graphics=0", stderr: "", ms: 1 };
      },
    }, { stage: "cut" });
    assert.equal(result.code, 1);
    assert.match(result.errTail, /changed while isolated authoring was running/);
    assert.equal(JSON.parse(readFileSync(item.ctx.planPath, "utf8")).sentinel, "external");
  } finally {
    rmSync(item.root, { recursive: true, force: true });
  }
});

test("Claude permissions and cwd input are rooted in the disposable writer", () => {
  const item = fixture();
  const staging = prepareInitialAuthoringStaging(item.ctx, "cut");
  try {
    const args = claudeArgs(staging.ctx, "cut");
    const allowed = args[args.indexOf("--allowedTools") + 1];
    assert.ok(allowed.includes(`Write(/${staging.ctx.planPath})`));
    assert.equal(allowed.includes(`Write(/${item.ctx.planPath})`), false);
    assert.ok(args.includes(staging.ctx.authoringDir!));
  } finally {
    staging.dispose();
    rmSync(item.root, { recursive: true, force: true });
  }
});

test("controller capture rejects hardlinked provider output", () => {
  const item = fixture();
  const staging = prepareInitialAuthoringStaging(item.ctx, "cut");
  try {
    const outside = path.join(item.root, "hardlink-source.json");
    writeFileSync(outside, '{"planVersion":2}\n');
    unlinkSync(staging.ctx.planPath);
    linkSync(outside, staging.ctx.planPath);
    assert.throws(() => captureInitialAuthoring(staging), /single-link regular file/);
    assert.equal(JSON.parse(readFileSync(item.ctx.planPath, "utf8")).sentinel,
      "original");
  } finally {
    staging.dispose();
    rmSync(item.root, { recursive: true, force: true });
  }
});

test("captured and validated pathname swaps cannot change promoted bytes", () => {
  const item = fixture();
  const staging = prepareInitialAuthoringStaging(item.ctx, "cut");
  try {
    writeFileSync(staging.ctx.planPath,
      '{"planVersion":2,"sentinel":"captured"}\n');
    const captured = captureInitialAuthoring(staging);
    writeFileSync(staging.ctx.planPath,
      '{"planVersion":9,"sentinel":"swapped-after-capture"}\n');
    promoteCapturedInitialAuthoring(captured, paths => {
      writeFileSync(paths.planPath,
        '{"planVersion":10,"sentinel":"swapped-after-validation"}\n');
    });
    assert.equal(JSON.parse(readFileSync(item.ctx.planPath, "utf8")).sentinel,
      "captured");
  } finally {
    staging.dispose();
    rmSync(item.root, { recursive: true, force: true });
  }
});
