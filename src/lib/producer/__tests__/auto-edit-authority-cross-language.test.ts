import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import {
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import os from "node:os";
import path from "node:path";
import type { AutoEditCtx } from "../../../app/api/producer/auto-edit/stream";
import { autoEditAuthoritySnapshot } from "../../server/auto-edit-authority-snapshot";
import {
  captureAutoEditDoctrine,
  PRODUCER_CORE_DOCTRINE_PATHS,
  PRODUCER_REFERENCED_DOCTRINE_PATHS,
} from "../../server/auto-edit-doctrine";
import { autoEditRequestKey } from "../../server/auto-edit-hash";
import {
  captureAutoEditPipeline,
  prepareAutoEditRunContext,
} from "../../server/auto-edit-pipeline-authority";
import {
  assertInputFreshness,
  assertPinnedCutPermissions,
  assertPinnedPythonResolver,
  assertPinnedRuntimeAssets,
  assertPinnedTemplateResolver,
  assertSnapshotTamper,
} from "./_auto-edit-authority-cross-language-assertions";

interface Fixture {
  repo: string;
  ctx: AutoEditCtx;
  transcript: string;
  frame: string;
  probe: string;
}

interface Golden {
  requestKey: string;
  snapshot: ReturnType<typeof autoEditAuthoritySnapshot>;
}

const MODEL_PATH = "scripts/producer/audio/models/bd.rnnn";
const PRELOAD_PATH = "scripts/producer/headless/node_isolated_user.cjs";
const REGISTRY_PATH =
  "docs/producer/command-driven-editing/contracts/render-effect-registry-v1.json";
const REGISTRY_SCHEMA_PATH =
  "schemas/producer/render-effect-registry-v1.schema.json";

function write(root: string, relative: string, content: string | Buffer): string {
  const destination = path.join(root, relative);
  mkdirSync(path.dirname(destination), { recursive: true });
  writeFileSync(destination, content);
  return destination;
}

function doctrineFiles(repo: string): void {
  for (const relative of [
    ...PRODUCER_CORE_DOCTRINE_PATHS,
    ...PRODUCER_REFERENCED_DOCTRINE_PATHS,
    "docs/studies/RESTRAINED_STYLE.md",
  ]) write(repo, relative, `DOCTRINE ${relative} — café\n`);
}

function pipelineFiles(repo: string): string {
  const probe = write(repo, "scripts/producer/probe.py", "print('PINNED-PIPELINE')\n");
  write(repo, "scripts/producer/producer_config.py", "# deterministic café config\n");
  for (const relative of [
    "scripts/producer/render_effect_registry.py",
    "scripts/producer/contracts/__init__.py",
    "scripts/producer/contracts/schema_validator.py",
  ]) write(repo, relative, readFileSync(path.join(process.cwd(), relative)));
  const modelPath = path.join(process.cwd(), "scripts/producer/audio/models/bd.rnnn");
  write(repo, "scripts/producer/audio/models/bd.rnnn", readFileSync(modelPath));
  write(repo, "scripts/producer/audio/models/not-allowlisted.rnnn", "do not capture\n");
  write(repo, PRELOAD_PATH, readFileSync(path.join(process.cwd(), PRELOAD_PATH)));
  write(repo, REGISTRY_PATH, readFileSync(path.join(process.cwd(), REGISTRY_PATH)));
  write(repo, REGISTRY_SCHEMA_PATH,
    readFileSync(path.join(process.cwd(), REGISTRY_SCHEMA_PATH)));
  write(repo, "templates/motion/tokens.css", ":root { --accent: #abcdef; }\n");
  write(repo, "templates/motion/hyperframes.json", "{}\n");
  write(repo, "templates/motion/index.html", "<main></main>\n");
  write(repo, "templates/motion/motion-tokens.js", "export const motion = {};\n");
  write(repo, "templates/motion/package.json", "{\"name\":\"motion\"}\n");
  write(repo, "templates/motion/vendor/gsap/gsap.min.js", "globalThis.gsap={};\n");
  write(repo, "templates/motion/compositions/card.html", "<main>card</main>\n");
  write(repo, "assets/fonts/test.ttf", "font");
  write(repo, "assets/models/test.onnx", "model");
  write(repo, "assets/music/test.mp3", "music");
  write(repo, "assets/sfx/test.wav", "sfx");
  write(repo, "src/app/api/producer/auto-edit/example.ts", "export const value = 1;\n");
  write(repo, "src/app/api/producer/native-short/example.ts", "export const short = 1;\n");
  write(repo, "src/app/api/producer/ai-edit/native.ts", "export const native = 1;\n");
  write(repo, "src/app/api/producer/live-build/live.ts", "export const live = 1;\n");
  write(repo, "src/app/api/producer/palmier/qc.ts", "export const qc = 1;\n");
  write(repo, "src/app/api/_lib/audit-gate.ts", "export const audit = true;\n");
  for (const name of ["files", "evidence", "model"]) write(repo, `src/app/api/producer/studio/import/${name}.ts`, "// TEST captured import dependency\n");
  write(repo, "src/lib/debug.ts", "// TEST captured debug dependency\n");
  write(repo, "src/lib/producer/edit-plan.ts", "export const plan = 1;\n");
  write(repo, "src/lib/server/auto-edit-authority.ts", "export const authority = 1;\n");
  write(repo, "src/lib/server/auto-edit-quality-artifacts.ts", "export const quality = 1;\n");
  write(repo, "package.json", "{\"name\":\"golden\"}\n");
  write(repo, "package-lock.json", "{\"lockfileVersion\":3}\n");
  write(repo, "tsconfig.json", "{\"compilerOptions\":{\"strict\":true}}\n");
  write(repo, "next.config.ts", "export default {}; // TEST captured build configuration\n");
  return probe;
}

function fixture(root: string): Fixture {
  const repo = path.join(root, "repo");
  const project = path.join(root, "project");
  const dir = path.join(project, "producer");
  const source = path.join(project, "source");
  const reference = path.join(project, "reference");
  mkdirSync(dir, { recursive: true });
  mkdirSync(source, { recursive: true });
  mkdirSync(reference, { recursive: true });
  doctrineFiles(repo);
  const probe = pipelineFiles(repo);
  const planPath = write(project, "producer/edit_plan.json",
    "{\"planVersion\":1,\"target\":{\"durationTargetS\":1.0},\"cutTrack\":[]}\n");
  const transcript = write(project, "source/clip.transcript.json",
    "{\"transcript\":[{\"text\":\"héllo 🎬\"}]}\n");
  const manifestPath = write(project, "source/asset_manifest.json",
    "{\"sources\":[{\"path\":\"clip.mp4\",\"contentHash\":\"media\",\"transcriptPath\":\"clip.transcript.json\"}]}\n");
  const profilePath = write(project, "reference/style_profile.json", "{\"style\":\"measured\"}\n");
  const deepStudyPath = write(project, "reference/deep_study.json", "{\"study\":\"deep\"}\n");
  const frame = write(project, "reference/frame.jpg", "golden-frame");
  write(project, "reference/reference.json", "{\"strategy\":\"mimic\"}\n");
  write(project, "reference/fingerprint.json", "{\"sha256\":\"source\"}\n");
  write(project, "reference/reference-source.json", "{\"source\":\"local\"}\n");
  const intent = { mode: "short" as const, style: "restrained" as const, brief: "café 🎬", lanes: {} };
  write(project, "project.json", JSON.stringify({ origin: "raw", history: [], intent }));
  return { repo, transcript, frame, probe, ctx: {
    dir, scope: "produced", intent, planPath, manifestPath, transcriptsDir: source,
    referenceStudy: {
      id: "golden-ref", title: "Référence", mode: "short", dir: reference,
      profilePath, deepStudyPath, representativeFrames: [frame],
    },
  } };
}

function pinned(fix: Fixture, runId: string): AutoEditCtx {
  const doctrine = captureAutoEditDoctrine(fix.ctx, runId, fix.repo);
  const pipeline = captureAutoEditPipeline(fix.ctx, runId, fix.repo);
  return { ...fix.ctx, doctrine, pipeline };
}

function pythonResult(ctx: AutoEditCtx, requestCtx: AutoEditCtx): {
  snapshot: ReturnType<typeof autoEditAuthoritySnapshot>;
  requestKey: string;
} {
  const script = [
    "import json, sys",
    "from palmier.quality_hash import authority_snapshot, request_key",
    "value = json.load(sys.stdin)",
    "print(json.dumps({'snapshot': authority_snapshot(value['ctx']), 'requestKey': request_key(value['requestCtx'])}, sort_keys=True))",
  ].join("; ");
  const result = spawnSync(path.join(process.cwd(), ".venv", "bin", "python3"), ["-c", script], {
    input: JSON.stringify({ ctx, requestCtx }), encoding: "utf8",
    env: { ...process.env, PYTHONPATH: path.join(process.cwd(), "scripts", "producer") },
  });
  if (result.status !== 0) throw new Error(result.stderr || result.stdout);
  return JSON.parse(result.stdout) as ReturnType<typeof pythonResult>;
}

function fixedRequestContext(ctx: AutoEditCtx): AutoEditCtx {
  return {
    ...ctx,
    dir: "/golden/project/producer", planPath: "/golden/project/producer/edit_plan.json",
    manifestPath: "/golden/project/source/asset_manifest.json",
    transcriptsDir: "/golden/project/source",
    referenceStudy: undefined,
  };
}

function assertAuthorityParity(fix: Fixture, ctx: AutoEditCtx): Golden {
  assert.ok(ctx.pipeline?.files.some((row) => row.path === MODEL_PATH));
  assert.ok(ctx.pipeline?.files.some((row) => row.path === PRELOAD_PATH));
  assert.ok(ctx.pipeline?.files.some((row) => row.path === REGISTRY_PATH));
  assert.ok(ctx.pipeline?.files.some((row) => row.path === REGISTRY_SCHEMA_PATH));
  assert.ok(ctx.pipeline?.files.some((row) => row.path === "tsconfig.json"));
  assert.ok(ctx.pipeline?.files.some((row) => row.path === "next.config.ts"));
  assert.ok(!ctx.pipeline?.files.some(
    (row) => row.path.endsWith("not-allowlisted.rnnn")));
  assert.deepEqual(readFileSync(path.join(
    ctx.pipeline!.snapshotRoot, ...MODEL_PATH.split("/"))),
  readFileSync(path.join(process.cwd(), ...MODEL_PATH.split("/"))));
  const requestCtx = fixedRequestContext(ctx);
  assert.equal(autoEditRequestKey({ ...requestCtx,
    brainSessionId: "runtime-only", brainSessionEstablished: true }),
  autoEditRequestKey(requestCtx));
  const defaultRequest = { ...requestCtx,
    deliveryPolicy: "palmier-hybrid" as const };
  assert.equal(pythonResult(ctx, defaultRequest).requestKey,
    autoEditRequestKey(requestCtx));
  const ts = {
    snapshot: autoEditAuthoritySnapshot(ctx),
    requestKey: autoEditRequestKey(requestCtx),
  };
  assert.deepEqual(
    pythonResult(ctx, requestCtx), ts,
    "TypeScript and Python must produce the same complete authority");
  const legacy = { ...ctx, doctrine: undefined, pipeline: undefined };
  assert.deepEqual(
    pythonResult(legacy, fixedRequestContext(legacy)).snapshot,
    autoEditAuthoritySnapshot(legacy),
    "legacy managed markers must use the same completely sorted row contract",
  );
  const golden = JSON.parse(readFileSync(path.join(
    __dirname, "fixtures", "auto-edit-authority-golden.json"), "utf8")) as Golden;
  assert.deepEqual(ts, golden);
  return ts;
}

function main(): void {
  const root = mkdtempSync(path.join(os.tmpdir(), "sniper-authority-cross-language-"));
  try {
    const fix = fixture(root);
    const ctx = pinned(fix, "golden-run");
    const ts = assertAuthorityParity(fix, ctx);
    const sourceDigest = ts.snapshot.pipelineDigest;
    writeFileSync(fix.probe, "print('LIVE-CHANGED')\n");
    assert.equal(autoEditAuthoritySnapshot(ctx).pipelineDigest, sourceDigest);
    const execution = spawnSync(path.join(process.cwd(), ".venv", "bin", "python3"), [
      path.join(ctx.pipeline!.snapshotRoot, "scripts", "producer", "probe.py"),
    ], { encoding: "utf8" });
    assert.equal(execution.stdout.trim(), "PINNED-PIPELINE");
    assertPinnedPythonResolver(ctx);
    assertPinnedTemplateResolver(ctx);
    assertPinnedRuntimeAssets(ctx);
    const next = pinned(fix, "next-run");
    assert.notEqual(next.pipeline?.digest, ctx.pipeline?.digest);
    const sourceModel = path.join(fix.repo, ...MODEL_PATH.split("/"));
    const modelBytes = readFileSync(sourceModel);
    writeFileSync(sourceModel, "tampered model");
    assert.throws(
      () => captureAutoEditPipeline(fix.ctx, "bad-model", fix.repo),
      /failed verification/,
    );
    writeFileSync(sourceModel, modelBytes);
    const resumed = prepareAutoEditRunContext({
      ctx: fix.ctx, runId: "resume-token", resume: true,
      savedDoctrine: ctx.doctrine, savedPipeline: ctx.pipeline,
    });
    assert.equal(resumed.pipeline?.digest, ctx.pipeline?.digest);
    assertPinnedCutPermissions(ctx, resumed);
    assertInputFreshness(fix, ctx, ts.snapshot.digest);
    assertSnapshotTamper(ctx);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
  console.log("auto-edit-authority-cross-language.test.ts: all assertions passed");
}

main();
