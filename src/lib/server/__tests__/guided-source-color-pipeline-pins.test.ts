/** Fresh capture/current-code metadata only; no executable source, media, native or package qualification. */
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import path from "node:path";
import test from "node:test";
import { capturePipelineAssets } from "../auto-edit-pipeline-assets";
import { captureAutoEditPipeline } from "../auto-edit-pipeline-authority";
import { openingControllerFiles } from "../guided-opening-launch-store";
import { GUIDED_SOURCE_COLOR_TS_FILES } from "../guided-source-color-staging";
import { GUIDED_SOURCE_COLOR_CLEANUP_TS_FILES } from "../guided-source-color-cleanup-pins";
import { sourceInventoryUnderGuard } from "../grade-observation-store";
import { sourceColorPipelineFixture, SOURCE_COLOR_CAPTURE_HOLES, removeCapturedPipelineFixtureSource } from "./_guided-source-color-pipeline-fixture";
import { sourceColorStaticImportClosure, staticProjectSpecifiers } from "./_guided-source-color-import-closure";

test("literal cleanup pins equal the full bounded current static project TS import graph", t => {
  const started = performance.now(), actual = sourceColorStaticImportClosure();
  assert.deepEqual(GUIDED_SOURCE_COLOR_CLEANUP_TS_FILES, actual);
  assert(actual.every(file => GUIDED_SOURCE_COLOR_TS_FILES.includes(file)));
  assert.equal(new Set(GUIDED_SOURCE_COLOR_TS_FILES).size, GUIDED_SOURCE_COLOR_TS_FILES.length);
  t.diagnostic(`TEST static TS import audit: ${actual.length} files in ${(performance.now() - started).toFixed(3)} ms; no native/package/dynamic-import qualification`);
});

test("static import audit distinguishes runtime project edges from type-only and external imports", () => {
  const source = `import type { T } from './types'; import {type X} from './also-types';
    export type { T } from './exported-types'; export {type T} from './more-types';
    import {value,type Y} from './runtime'; import './side-effect'; export {value} from './re-export';
    export * from '@/lib/server/TEST'; import packageValue from 'TEST-external'; import fs from 'node:fs';
    import('./TEST-dynamic-is-not-statically-qualified');`;
  assert.deepEqual(staticProjectSpecifiers(source), ["./runtime", "./side-effect", "./re-export", "@/lib/server/TEST"]);
});

test("fresh source capture retains the four actual TS import holes without changing exclusions", t => {
  const f = sourceColorPipelineFixture(t), files = capturePipelineAssets(f.repository), names = files.map(row => row.path);
  for (const relative of SOURCE_COLOR_CAPTURE_HOLES) {
    const row = files.find(file => file.path === relative); assert(row, `Fresh capture omitted ${relative}`);
    assert.equal(row.hash, createHash("sha256").update(row.bytes).digest("hex"));
  }
  assert.equal(new Set(names).size, names.length); assert.deepEqual(names, [...names].sort());
  assert(!names.some(name => name.includes("TEST-excluded")));
});

test("actual fresh pipeline snapshot satisfies every current V2 pin while legacy selection remains five", t => {
  const f = sourceColorPipelineFixture(t), started = performance.now();
  const pipeline = captureAutoEditPipeline(f.proposal.job.ctx, "TEST-full-source-color-pins", f.repository), captured = performance.now();
  f.proposal.job.ctx.pipeline = pipeline;
  const actual = openingControllerFiles(f.proposal, 2), checked = performance.now();
  assert.equal(openingControllerFiles(f.proposal).length, 5);
  for (const relative of GUIDED_SOURCE_COLOR_TS_FILES) assert(actual.some(file => file.path === relative));
  assert.equal(actual.length, new Set(actual.map(row => row.path)).size);
  t.diagnostic(`TEST fresh metadata: ${pipeline.files.length} captured files, ${actual.length} V2 pins; capture ${(captured - started).toFixed(3)} ms; current-pin check ${(checked - captured).toFixed(3)} ms`);
});

test("each missing explicit capture hole fails instead of silently minting a reduced fresh snapshot", async t => {
  for (const relative of SOURCE_COLOR_CAPTURE_HOLES) await t.test(relative, t => {
    const f = sourceColorPipelineFixture(t); removeCapturedPipelineFixtureSource(f, relative);
    assert.throws(() => capturePipelineAssets(f.repository), /Required Producer pipeline source is missing/);
  });
});

test("missing new cleanup or shared owner pin cannot borrow current code from outside the original snapshot", t => {
  const f = sourceColorPipelineFixture(t);
  const pipeline = captureAutoEditPipeline(f.proposal.job.ctx, "TEST-pins-cannot-borrow", f.repository);
  f.proposal.job.ctx.pipeline = pipeline;
  for (const name of ["src/lib/server/guided-source-color-cleanup-recovery.ts", "src/lib/server/guided-source-color-cleanup-final-read.ts",
    "src/lib/server/guided-source-color-cleanup-adoption.ts", "src/lib/server/guided-source-color-cleanup-preparation.ts",
    "src/lib/server/guided-source-color-cleanup-history.ts", "src/lib/server/guided-source-color-cleanup-history-hold.ts",
    "src/lib/server/project-mutation-lease.ts", "src/app/api/producer/studio/import/evidence.ts",
    "src/lib/server/guided-opening-finishing.ts"]) {
    const index = pipeline.files.findIndex(row => row.path === name); assert(index >= 0);
    const [original] = pipeline.files.splice(index, 1);
    assert.throws(() => openingControllerFiles(f.proposal, 2), /predates required/);
    pipeline.files.splice(index, 0, original);
  }
  assert.equal(openingControllerFiles(f.proposal).length, 5);
});

/** Run only bounded Python metadata discovery/checks, never an encoder, probe, daemon or model. */
function pythonMetadata(script: string, input = ""): string {
  return execFileSync(path.join(process.cwd(), ".venv/bin/python"), ["-c", script], {
    cwd: process.cwd(), input, timeout: 10_000, maxBuffer: 256 * 1024, encoding: "utf8",
    env: { ...process.env, PYTHONPATH: path.join(process.cwd(), "scripts/producer") },
  });
}

/** Reuse the production static Python walker, with a finite source-size inventory before it runs. */
function openingPythonSources(entrypoint: "guided_opening_media.py" | "guided_opening_read.py" | "guided_body_media.py"
  | "guided_body_read.py" | "guided_body_cleanup.py" = "guided_opening_media.py"): string[] {
  const result = pythonMetadata(`from pathlib import Path
import json
from render_effect_discovery import local_python_import_closure
root = Path.cwd(); producer = root / "scripts/producer"
files = [p for p in producer.rglob("*.py") if "tests" not in p.parts and "__pycache__" not in p.parts]
assert len(files) <= 4000
assert all(p.is_file() and not p.is_symlink() and p.resolve() == p and p.stat().st_size <= 8*1024**2 for p in files)
assert sum(p.stat().st_size for p in files) <= 64*1024**2
paths = local_python_import_closure([producer / ${JSON.stringify(entrypoint)}])
assert len(paths) <= 512 and all(p.is_relative_to(producer) for p in paths)
print(json.dumps([p.relative_to(root).as_posix() for p in paths]))`);
  const paths: unknown = JSON.parse(result);
  assert(Array.isArray(paths) && paths.every(value => typeof value === "string" && value.startsWith("scripts/producer/") && value.endsWith(".py")));
  return paths;
}

test("fresh capture and staged code inventory retain the actual source-only base Python closure", t => {
  const started = performance.now(), sources = openingPythonSources(), discovered = performance.now();
  const context = "scripts/producer/guided_source_color_base_context.py";
  assert(sources.includes(context));
  const schemas = ["channel-normalization-receipt-v1", "treatment-proposal-v7", "treatment-proposal-v8"]
    .map(name => `schemas/producer/${name}.schema.json`);
  const inventoryLeaves = ["grade-observation-process.ts", "grade-observation-service.ts"]
    .map(name => `src/lib/server/${name}`); // Legacy inventory-only leaves, not runtime cleanup import edges.
  const gradeLeaves = ["headless/grade_observation_worker.js", "headless/render_image_approval.json", "color/grade_project_worker.py"]
    .map(name => `scripts/producer/${name}`); // Explicit existing non-import worker/data requirements.
  const f = sourceColorPipelineFixture(t, [...sources, ...schemas, ...inventoryLeaves, ...gradeLeaves]);
  const pipeline = captureAutoEditPipeline(f.proposal.job.ctx, "TEST-source-only-base-capture", f.repository);
  const captured = new Map(pipeline.files.map(row => [row.path, row.hash]));
  let checks = 0;
  const inventory = sourceInventoryUnderGuard(pipeline.snapshotRoot, () => { checks++; });
  const staged = new Map(inventory.files.map(row => [path.relative(pipeline.snapshotRoot, row.path), row.sha256]));
  for (const relative of [...sources, ...gradeLeaves]) {
    assert(captured.has(relative), `Fresh capture omitted actual Python import ${relative}`);
    assert.equal(staged.get(relative), captured.get(relative), `Staging omitted or changed ${relative}`);
  }
  const expected = Object.fromEntries([...sources, ...schemas, ...gradeLeaves].map(relative => [relative, captured.get(relative)]));
  const outcome = JSON.parse(pythonMetadata(`import json,sys
from pathlib import Path
from color.grade_project import implementation
from guided_opening_pipeline import _execution_closure
expected = json.load(sys.stdin)
grade = implementation()
assert all(expected[Path(row["path"]).relative_to(Path.cwd()).as_posix()] == row["sha256"] for row in grade)
rows = _execution_closure(expected, 8)
del expected["scripts/producer/guided_source_color_base_context.py"]
try:
    _execution_closure(expected, 8)
except RuntimeError as error:
    print(json.dumps({"count": len(rows), "gradeCount": len(grade), "missing": str(error)}))
else:
    raise RuntimeError("TEST missing original source pin was accepted")`, JSON.stringify(expected)));
  assert.equal(outcome.count, sources.length + schemas.length);
  assert.match(outcome.missing, /absent or changed.*guided_source_color_base_context/);
  t.diagnostic(`TEST Python closure ${sources.length}; grade implementation ${outcome.gradeCount}; snapshot ${pipeline.files.length}; staged ${inventory.files.length}; guard calls ${checks}; discovery ${(discovered - started).toFixed(3)} ms; complete metadata test ${(performance.now() - started).toFixed(3)} ms; no native/package/admission qualification`);
});

test("fresh capture retains the complete actual schema2 readback Python closure and finite holders", t => {
  const started = performance.now(), sources = openingPythonSources("guided_opening_read.py"), discovered = performance.now();
  const required = ["guided_opening_read.py", "guided_opening_claim.py", "guided_source_color_read.py",
    "guided_source_color_read_scope.py", "guided_source_color_read_entry.py", "guided_source_color_read_transport.py",
    "guided_source_color_observation_read.py", "guided_source_color_observation_files.py",
    "guided_source_color_observation_contract.py", "guided_source_color_observation_rows.py",
    "guided_source_color_observation_replay.py", "guided_source_color_observation_execution.py",
    "guided_source_color_observation_pins.py", "guided_source_color_consumption_read.py",
    "guided_source_color_consumption_files.py", "guided_source_color_consumption_contract.py",
    "color/grade_bt709_identity.py", "color/grade_observation_read.py", "guided_body_execution.py",
    "cross_runtime_canonical_json.py"].map(name => `scripts/producer/${name}`);
  for (const relative of required) assert(sources.includes(relative), `Read entrypoint does not import required boundary ${relative}`);
  const inventoryLeaves = ["grade-observation-process.ts", "grade-observation-service.ts"]
    .map(name => `src/lib/server/${name}`); // Existing inventory-only TS leaves, not executed by this TEST.
  const f = sourceColorPipelineFixture(t, [...sources, ...inventoryLeaves]);
  const pipeline = captureAutoEditPipeline(f.proposal.job.ctx, "TEST-schema2-read-closure", f.repository);
  const original = JSON.stringify(pipeline), captured = new Map(pipeline.files.map(row => [row.path, row.hash]));
  let checks = 0;
  const inventory = sourceInventoryUnderGuard(pipeline.snapshotRoot, () => { checks++; });
  const staged = new Map(inventory.files.map(row => [path.relative(pipeline.snapshotRoot, row.path), row.sha256]));
  const bytes = new Map(capturePipelineAssets(f.repository).map(row => [row.path, row]));
  for (const relative of sources) {
    const row = bytes.get(relative); assert(row, `Fresh package omitted read import ${relative}`);
    assert.equal(captured.get(relative), createHash("sha256").update(row.bytes).digest("hex"), `Snapshot changed ${relative}`);
    assert.equal(staged.get(relative), captured.get(relative), `Staging omitted or changed read import ${relative}`);
  }
  assert.equal(JSON.stringify(pipeline), original, "Read-closure verification must not rewrite an existing snapshot");
  assert.equal(new Set(sources).size, sources.length);
  assert(checks > sources.length);
  t.diagnostic(`TEST read seed guided_opening_read.py: ${sources.length} Python imports; ${required.length} explicit read/holder boundaries; ${pipeline.files.length} freshly captured files; ${inventory.files.length} staged files; discovery ${(discovered - started).toFixed(3)} ms; total ${(performance.now() - started).toFixed(3)} ms; no native, dynamic-import, old-snapshot repair or package execution qualification`);
});

test("fresh capture retains actual body worker/read/cleanup imports and refuses a reduced original lock", t => {
  const started = performance.now(), sources = [...new Set(["guided_body_media.py", "guided_body_read.py", "guided_body_cleanup.py"]
    .flatMap(name => openingPythonSources(name as "guided_body_media.py" | "guided_body_read.py" | "guided_body_cleanup.py")))].sort();
  for (const name of ["guided_body_source_color_entry.py", "guided_body_source_color_work.py", "guided_body_source_color_result.py",
    "guided_body_read_entry.py", "guided_source_color_read_scope.py", "guided_source_color_consumption_read.py"]) {
    assert(sources.includes(`scripts/producer/${name}`), `Body import closure omitted ${name}`);
  }
  const f = sourceColorPipelineFixture(t, sources);
  const pipeline = captureAutoEditPipeline(f.proposal.job.ctx, "TEST-source2-body-closure", f.repository);
  const original = JSON.stringify(pipeline), expected = new Map(pipeline.files.map(row => [row.path, row.hash]));
  for (const source of sources) assert(expected.has(source), `Fresh body capture omitted ${source}`);
  const outcome = JSON.parse(pythonMetadata(`import json,sys,tempfile
from pathlib import Path
from types import SimpleNamespace
from cut_preview_io import bound_json,file_hash,write_new
from guided_body_pipeline import _body_closure
pipeline = json.load(sys.stdin)
pipeline["lockSha256"] = file_hash(Path(pipeline["lockPath"]))
actual = _body_closure(SimpleNamespace(value={"pipeline":pipeline}))
lock = bound_json(Path(pipeline["lockPath"]),pipeline["lockSha256"])
missing = "scripts/producer/guided_body_read_entry.py"
assert any(row["path"] == missing for row in lock["files"])
lock["files"] = [row for row in lock["files"] if row["path"] != missing]
with tempfile.TemporaryDirectory(prefix="TEST-body-reduced-lock-",dir="/private/tmp") as temporary:
    target = Path(temporary).resolve()/"TEST-lock.json"
    write_new(target,lock)
    reduced = {**pipeline,"lockPath":str(target),"lockSha256":file_hash(target)}
    try:
        _body_closure(SimpleNamespace(value={"pipeline":reduced}))
    except RuntimeError as error:
        print(json.dumps({"count":len(actual),"missing":str(error)}))
    else:
        raise RuntimeError("TEST reduced original body lock was accepted")`, JSON.stringify(pipeline)));
  assert.equal(outcome.count, sources.length);
  assert.match(outcome.missing, /absent or changed.*guided_body_read_entry/);
  assert.equal(JSON.stringify(pipeline), original, "Never rebaseline an original snapshot");
  t.diagnostic(`TEST body Python imports ${sources.length}; fresh snapshot ${pipeline.files.length}; total ${(performance.now() - started).toFixed(3)} ms; metadata only, no native/AV qualification`);
});
