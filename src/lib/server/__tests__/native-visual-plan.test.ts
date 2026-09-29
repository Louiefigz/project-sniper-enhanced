/** Native project routing accepts only the allocated whole-project visual plan. */
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { pythonInterpreter } from "../../../app/api/_lib/spawn-python";
import { fileSha256 } from "../auto-edit-hash";
import { nativeVisualPlanSource } from "../visual-plan-binding";
import { resolveVisualPlanBinding, type CatalogReceiptAuthorityPin,
  type VisualPlanBinding } from "../visual-plan-binding";
import { assertNativeVisualPlanApplication,
  type NativeVisualPlanApplication } from "../native-visual-plan-application";
import { assertNativeExecutionBinding } from "../native-visual-execution-binding";
import { readNativeShortProject, writeNativeShortProject } from "../native-short-project";
import { nativeShortFixture, refreshNativePrebuildReviewFixture } from "./_native-short-project-fixture";

function writePlan(file: string, mode: "short" | "long", routeClass = "native",
  modality = "text"): CatalogReceiptAuthorityPin | undefined {
  const code = [
    "import json,os,sys",
    "from _visual_plan_fixture import candidate,materialize_plan_pins,opportunity,visual_plan",
    "from planner.visual_plan_allocator import allocate_visual_plan",
    "from planner.catalog_receipt_issuer import issue_catalog_receipts",
    `value=visual_plan(opportunity('opp:one',0,[candidate('candidate:one',modality='${modality}',routeClass='${routeClass}')]))`,
    `value['project']['mode']='${mode}'`,
    `value['project']['aspect']='${mode === "short" ? "9:16" : "16:9"}'`,
    "value=materialize_plan_pins(value,os.path.join(os.path.dirname(sys.argv[1]),'visual-plan-pins'))",
    `if '${modality}' == 'catalog':`,
    " result=issue_catalog_receipts(value,os.path.dirname(sys.argv[1]))",
    " value=result.plan",
    " print(json.dumps(result.authority))",
    "else:",
    " value=allocate_visual_plan(value)",
    "open(sys.argv[1],'w').write(json.dumps(value))",
  ].join("\n");
  const output = execFileSync(pythonInterpreter(), ["-B", "-c", code, file], {
    cwd: path.join(process.cwd(), "scripts/producer"),
    env: { ...process.env, PYTHONPATH: ".:tests", PYTHONDONTWRITEBYTECODE: "1" },
    encoding: "utf8",
  });
  return output.trim() ? JSON.parse(output) as CatalogReceiptAuthorityPin : undefined;
}

function application(file: string, visibleId: string,
  binding?: VisualPlanBinding): NativeVisualPlanApplication {
  const plan = JSON.parse(readFileSync(file, "utf8")) as {
    allocation: { decisions: Array<{ opportunityId: string; candidateId: string }> };
    opportunities: Array<{ id: string; timing: { startFrame: number; endFrameExclusive: number };
      candidates: Array<{ id: string; modality: string }> }>;
  };
  const decision = plan.allocation.decisions[0], opportunity = plan.opportunities[0];
  const candidate = opportunity.candidates.find(row => row.id === decision.candidateId)!;
  const resolved = binding ?? resolveVisualPlanBinding(file);
  assert.ok(resolved);
  const markup = textMarkup(visibleId);
  const executionBinding = candidate.modality === "catalog"
    ? { kind: "catalog" as const, mounts: [] }
    : { kind: "text" as const, elementId: visibleId, outputRange: opportunity.timing,
      visibleText: "Visible proof", contentSha256: createHash("sha256")
        .update(markup).digest("hex") };
  return { schemaVersion: 1, route: "native-short", visualPlanSha256: resolved.visualPlanSha256,
    decisions: [{ opportunityId: decision.opportunityId, candidateId: decision.candidateId,
      anatomy: "split-card", development: "label-then-proof",
      ...opportunity.timing, sceneIndexes: [0],
      visibleIds: [visibleId], catalogBindings: [], binding: executionBinding }] };
}

function textMarkup(visibleId: string): string {
  return `<div id="${visibleId}" data-start="0" data-duration="0.8">Visible proof</div>`;
}

test("native visual-plan binding enforces the complete project route and immutable bytes", () => {
  const directory = realpathSync(mkdtempSync(path.join(os.tmpdir(), "native-visual-plan-")));
  try {
    const file = path.join(directory, "VISUAL-PLAN.json");
    writePlan(file, "short");
    const binding = resolveVisualPlanBinding(file);
    assert.ok(binding);
    assert.equal(nativeVisualPlanSource(binding, "short"), readFileSync(file, "utf8"));
    assert.throws(() => nativeVisualPlanSource(binding, "long"), /complete long project/);
    writeFileSync(file, `${readFileSync(file, "utf8")} `);
    assert.throws(() => nativeVisualPlanSource(binding, "short"), /changed after planning/);
  } finally { rmSync(directory, { recursive: true, force: true }); }
});

test("ordinary allocation cannot be smuggled into a native project", () => {
  const directory = realpathSync(mkdtempSync(path.join(os.tmpdir(), "ordinary-visual-plan-")));
  try {
    const file = path.join(directory, "VISUAL-PLAN.json");
    writePlan(file, "short", "compatibility");
    const binding = resolveVisualPlanBinding(file);
    assert.ok(binding);
    assert.throws(() => nativeVisualPlanSource(binding, "short"), /native-short/);
  } finally { rmSync(directory, { recursive: true, force: true }); }
});

test("Native Short freezes and cold-reads the allocated visual plan", () => {
  const directory = realpathSync(mkdtempSync(path.join(os.tmpdir(), "short-visual-plan-")));
  try {
    const input = nativeShortFixture(directory);
    const binding = input.visualPlan;
    assert.ok(binding);
    const plan = JSON.parse(readFileSync(binding.path, "utf8"));
    const candidate = plan.opportunities[0].candidates[0];
    const mediaPin = plan.mediaAuthority;
    const media = JSON.parse(readFileSync(mediaPin.path, "utf8"));
    const source = input.assets.find(row => row.role === "source")!;
    const admitted = media.inventory[0];
    assert.deepEqual(candidate.source, {
      recordId: "asset:source", path: admitted.path, sha256: source.sha256,
      sourceSha256: source.sha256,
      range: { startFrame: 0, endFrameExclusive: 50 },
    });
    assert.equal(admitted.modality, "source-footage");
    assert.equal(admitted.recordId, "asset:source");
    assert.equal(admitted.sourceSha256, source.sha256);
    assert.equal(admitted.sourceSetLane, "source");
    assert.equal(admitted.authorizationEvidence, null);
    refreshNativePrebuildReviewFixture(input);
    const built = writeNativeShortProject(input, path.join(directory, "project"));
    assert.equal(existsSync(path.join(built.directory, "VISUAL-PLAN.json")), true);
    assert.deepEqual(readNativeShortProject(built.directory).visualPlan, binding);
  } finally { rmSync(directory, { recursive: true, force: true }); }
});

test("Native Short execution application covers the exact selected candidate and visible scene", () => {
  const directory = realpathSync(mkdtempSync(path.join(os.tmpdir(), "short-visual-application-")));
  try {
    const file = path.join(directory, "VISUAL-PLAN.json");
    writePlan(file, "short");
    const binding = resolveVisualPlanBinding(file);
    assert.ok(binding);
    const input = nativeShortFixture(directory), visibleId = input.strategy.scenes[0].visibleIds[0];
    const value = application(file, visibleId);
    const html = textMarkup(visibleId);
    assert.doesNotThrow(() => assertNativeVisualPlanApplication({ binding,
      application: value, scenes: input.strategy.scenes, html }));
    const missing = structuredClone(value); missing.decisions = [];
    assert.throws(() => assertNativeVisualPlanApplication({ binding,
      application: missing, scenes: input.strategy.scenes, html }), /cover every/);
    const substituted = structuredClone(value);
    substituted.decisions[0].candidateId = "candidate:other";
    assert.throws(() => assertNativeVisualPlanApplication({ binding,
      application: substituted, scenes: input.strategy.scenes, html }), /differs/);
    const absent = structuredClone(value); absent.decisions[0].visibleIds = ["missing"];
    assert.throws(() => assertNativeVisualPlanApplication({ binding,
      application: absent, scenes: input.strategy.scenes, html }), /absent or unrelated/);
    assert.throws(() => assertNativeVisualPlanApplication({ binding,
      application: value, scenes: input.strategy.scenes,
      html: html.replace("Visible proof", "Substituted proof") }), /binding differs/);
    const forged = structuredClone(value);
    if (forged.decisions[0].binding.kind === "text") {
      forged.decisions[0].binding.contentSha256 = "0".repeat(64);
    }
    assert.throws(() => assertNativeVisualPlanApplication({ binding,
      application: forged, scenes: input.strategy.scenes, html }), /binding differs/);
    assert.throws(() => assertNativeVisualPlanApplication({ binding,
      application: value, scenes: input.strategy.scenes, html,
      styleApplication: { choices: [{ sceneIndex: 0, visibleIds: [visibleId],
        anatomy: "split-card", development: "different reveal" }] } }),
    /disagree on composition development/);
  } finally { rmSync(directory, { recursive: true, force: true }); }
});

test("catalog execution binds the visible ID to the exact mounted implementation", () => {
  const directory = realpathSync(mkdtempSync(path.join(os.tmpdir(), "short-catalog-application-")));
  try {
    const file = path.join(directory, "VISUAL-PLAN.json");
    const authority = writePlan(file, "short", "native", "catalog");
    const binding = resolveVisualPlanBinding(file, undefined, authority); assert.ok(binding);
    const plan = JSON.parse(readFileSync(file, "utf8"));
    const selected = plan.opportunities[0].candidates[0];
    assert.ok(authority);
    const reference = selected.source.path as string | undefined;
    assert.ok(reference);
    const implementation = path.join(directory, "adapted-catalog.html");
    writeFileSync(implementation, `${readFileSync(reference, "utf8")}\n<!-- project-owned adaptation -->\n`);
    const visibleId = "catalog-mount", mounted = "compositions/catalog.html";
    const value = application(file, visibleId, binding);
    value.decisions[0].catalogBindings = [{ file: mounted, mountId: visibleId,
      catalogId: selected.source.recordId, sourceSha256: selected.source.sourceSha256,
      implementationSha256: fileSha256(implementation)! }];
    value.decisions[0].binding = { kind: "catalog",
      mounts: structuredClone(value.decisions[0].catalogBindings) };
    const catalogFiles = [{ file: mounted, path: implementation,
      sha256: fileSha256(implementation)!, catalogId: selected.source.recordId,
      sourceSha256: selected.source.sourceSha256 }];
    const scene = [{ startFrame: 0, endFrame: 30, visibleIds: [visibleId] }];
    const html = `<div id="${visibleId}" data-start="0" data-duration="0.8" data-composition-src="${mounted}"></div>`;
    assert.doesNotThrow(() => assertNativeVisualPlanApplication({ binding,
      application: value, scenes: scene, html, catalogFiles }));
    const direct = structuredClone(value);
    direct.decisions[0].catalogBindings[0].implementationSha256 = selected.source.sourceSha256;
    if (direct.decisions[0].binding.kind === "catalog") {
      direct.decisions[0].binding.mounts = structuredClone(direct.decisions[0].catalogBindings);
    }
    const directFiles = [{ ...catalogFiles[0], path: reference,
      sha256: selected.source.sourceSha256 }];
    assert.throws(() => assertNativeVisualPlanApplication({ binding,
      application: direct, scenes: scene, html, catalogFiles: directFiles }),
    /requires a project-owned adaptation/);
    assert.throws(() => assertNativeVisualPlanApplication({ binding,
      application: value, scenes: scene,
      html: `<div id="${visibleId}" data-start="0" data-duration="0.8"></div><div id="other" data-composition-src="${mounted}"></div>`,
      catalogFiles }), /differs from its staged implementation/);
  } finally { rmSync(directory, { recursive: true, force: true }); }
});

test("native modality bindings reject media, transition, presenter, custom and omit drift", () => {
  const timing = { startFrame: 0, endFrameExclusive: 24 }, fps = 30;
  const asset = { file: "assets/source.mp4", sha256: "a".repeat(64) };
  const video = '<video id="media" src="assets/source.mp4" data-start="0" '
    + 'data-duration="0.8" data-media-start="2"></video>';
  const media = { kind: "media" as const, elementId: "media", sourceRecordId: "asset:one",
    assetFile: asset.file, sourceSha256: asset.sha256,
    sourceRange: { startFrame: 60, endFrameExclusive: 84 }, outputRange: timing,
    elementSha256: createHash("sha256").update(video).digest("hex") };
  const base = { visibleIds: ["media"], html: video, assets: [asset], timing, fps,
    catalogBindings: [] };
  assert.doesNotThrow(() => assertNativeExecutionBinding({ ...base, binding: media,
    candidate: { modality: "source-footage", source: { recordId: "asset:one",
      sourceSha256: asset.sha256, range: media.sourceRange } } }));
  assert.throws(() => assertNativeExecutionBinding({ ...base,
    binding: { ...media, sourceRange: timing }, candidate: { modality: "source-footage",
      source: { recordId: "asset:one", sourceSha256: asset.sha256,
        range: media.sourceRange } } }), /binding differs/);
  const presenter = { kind: "presenter" as const, elementId: "media",
    assetFile: asset.file, sourceSha256: asset.sha256, sourceRange: media.sourceRange,
    outputRange: timing, elementSha256: media.elementSha256 };
  assert.doesNotThrow(() => assertNativeExecutionBinding({ ...base, binding: presenter,
    candidate: { modality: "presenter" } }));
  const transition = '<div id="seam" data-start="0" data-duration="0.8" '
    + 'data-transition-kind="whip"></div>';
  assert.doesNotThrow(() => assertNativeExecutionBinding({ binding: { kind: "transition",
    elementId: "seam", outputRange: timing, mechanism: "whip",
    configurationSha256: createHash("sha256").update(transition).digest("hex") },
    candidate: { modality: "transition" }, visibleIds: ["seam"], html: transition,
    assets: [], timing, fps, catalogBindings: [] }));
  const custom = '<div id="custom" data-start="0" data-duration="0.8"></div>';
  assert.doesNotThrow(() => assertNativeExecutionBinding({ binding: { kind: "custom-native",
    visibleIds: ["custom"], implementationSha256: createHash("sha256")
      .update(custom).digest("hex"), outputRange: timing }, candidate: { modality: "custom-native" },
    visibleIds: ["custom"], html: custom, assets: [], timing, fps, catalogBindings: [] }));
  assert.doesNotThrow(() => assertNativeExecutionBinding({ binding: { kind: "omit" },
    candidate: { modality: "omit" }, visibleIds: [], html: "", assets: [], timing, fps,
    catalogBindings: [] }));
});
