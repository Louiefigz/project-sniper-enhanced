/** Contract fixtures only; TEST preview bytes do not claim an actual media decode. */
import assert from "node:assert/strict";
import { test } from "node:test";
import { existsSync, mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import path from "node:path";
import { prepareSavedPlanReview } from "@/app/api/producer/auto-edit/saved-plan-request";
import { reviews } from "./_plan-readiness-fixture";
import { readinessPacket, reviewUnits } from "../plan-readiness-packet";
import { assertPlanReviews, assertRenderReadiness, writeRenderReadiness, PLAN_REVIEWS } from "../plan-readiness";
import { pythonInterpreter } from "@/app/api/_lib/spawn-python";

const gates = { ok: true, errors: [] };
function write(file: string, value: unknown) { writeFileSync(file, JSON.stringify(value)); }


function fixture(scope = "produced", graphics = "auto") {
  const root = mkdtempSync("/private/tmp/sniper-readiness-test-");
  const dir = path.join(root, "producer"), source = path.join(root, "source");
  mkdirSync(dir); mkdirSync(source);
  const planPath = path.join(dir, "edit_plan.json"), manifest = path.join(source, "asset_manifest.json");
  write(path.join(root, "project.json"), { origin: "raw", history: [], intent: {
    mode: "longform", scope, lanes: { graphics, broll: "off" }, brief: "TEST preserve the argument", music: false,
  } });
  const media = path.join(source, "video.mp4");
  writeFileSync(media, "TEST source bytes; not decoded");
  write(path.join(source, "words.json"), { words: [] });
  write(manifest, { sources: [{ id: "s1", path: media, transcriptPath: "words.json" }], broll: [] });
  write(planPath, { planVersion: 1, target: { mode: "longform", scope }, cutTrack: [{ sourceId: "s1", start: 0, end: 10 }] });
  const ctx = prepareSavedPlanReview(dir).ctx;
  const packet = readinessPacket(ctx);
  const preview = path.join(root, "preview.mp4"), evidence = path.join(root, "evidence.json");
  writeFileSync(preview, "TEST preview bytes; media-admission parser tested separately");
  write(evidence, { test: "explicit synthetic contract evidence" });
  return { root, dir, source, planPath, manifest, ctx, packet, preview, evidence,
    cleanup: () => rmSync(root, { recursive: true, force: true }) };
}


function approve(f: ReturnType<typeof fixture>) {
  write(path.join(f.dir, PLAN_REVIEWS), { schemaVersion: 1, reviews: reviews(f) });
  writeRenderReadiness(f.ctx, { gates });
}

test("all scopes and graphics-off require current independent review", () => {
  for (const scope of ["trim", "light", "produced", "full"]) {
    const f = fixture(scope, "off");
    try {
      assert.equal(f.packet.requiredReviews, ["trim", "light"].includes(scope) ? 1 : 2);
      assert.throws(() => writeRenderReadiness(f.ctx, { gates }));
      approve(f); assertRenderReadiness(f.ctx);
      writeFileSync(path.join(f.source, "video.mp4"), "TEST source replacement at same path");
      assert.throws(() => assertRenderReadiness(f.ctx), /stale/);
    } finally { f.cleanup(); }
  }
});

test("reviews bind independent sessions, assessments, exact preview bytes and passing verdicts", () => {
  const f = fixture();
  try {
    const mutations = [
      (rows: ReturnType<typeof reviews>) => { rows[1].reviewer.sessionId = rows[0].reviewer.sessionId; },
      (rows: ReturnType<typeof reviews>) => { rows[0].reviewer.sessionId = "author"; },
      (rows: ReturnType<typeof reviews>) => { rows[0].coverage.feasibility = ""; },
      (rows: ReturnType<typeof reviews>) => { rows[0].previews = []; },
      (rows: ReturnType<typeof reviews>) => { rows[0].previews[0].sha256 = "0".repeat(64); },
      (rows: ReturnType<typeof reviews>) => { rows[0].review.verdict = "block"; },
      (rows: ReturnType<typeof reviews>) => { rows[0].units.plan = "0".repeat(64); },
    ];
    for (const mutate of mutations) {
      const rows = reviews(f); mutate(rows);
      write(path.join(f.dir, PLAN_REVIEWS), { schemaVersion: 1, reviews: rows });
      assert.throws(() => assertPlanReviews(f.dir, f.packet));
    }
    approve(f);
    writeFileSync(f.preview, "TEST replaced preview");
    assert.throws(() => assertRenderReadiness(f.ctx), /Preview bytes changed/);
  } finally { f.cleanup(); }
});

test("draft readiness cannot admit a final and failed gates mint no readiness", () => {
  const f = fixture("trim", "off");
  try {
    assert.throws(() => writeRenderReadiness(f.ctx, { draft: true, gates: { ok: false, errors: ["TEST failure"] } }), /deterministic/);
    writeRenderReadiness(f.ctx, { draft: true, gates });
    assertRenderReadiness(f.ctx, true);
    assert.throws(() => assertRenderReadiness(f.ctx));
    const plan = JSON.parse(readFileSync(f.planPath, "utf8"));
    plan.cutTrack[0].end = 9; write(f.planPath, plan);
    assert.throws(() => assertRenderReadiness(f.ctx, true), /stale/);
  } finally { f.cleanup(); }
});

test("three graphic changes preserve only unchanged dependency neighborhoods", () => {
  const plan = { cutTrack: [{ start: 0, end: 300 }], graphicsTrack: Array.from({ length: 30 }, (_, index) => ({
    kind: "line-swap", outStart: index * 10, outEnd: index * 10 + 2, spec: { text: "before" },
  })) };
  const before = reviewUnits(plan, { sources: "same" });
  for (const index of [3, 12, 25]) plan.graphicsTrack[index].spec.text = "after";
  const after = reviewUnits(plan, { sources: "same" });
  const changed = after.filter((unit, index) => unit.hash !== before[index].hash).map(unit => unit.id);
  assert.deepEqual(changed, ["plan", ...[2, 3, 4, 11, 12, 13, 24, 25, 26].map(index => `graphicsTrack/${index}`)]);
  assert.notEqual(after[0].hash, before[0].hash);
  plan.cutTrack[0].end = 290;
  assert.ok(reviewUnits(plan, { sources: "same" }).every((unit, index) => unit.hash !== after[index].hash));
  assert.ok(reviewUnits(plan, { sources: "changed" }).every((unit, index) => unit.hash !== after[index].hash));
  plan.graphicsTrack[3].spec = { text: "after", layout: "changed" } as typeof plan.graphicsTrack[3]["spec"];
  assert.ok(reviewUnits(plan, { sources: "same" }).every((unit, index) => unit.hash !== after[index].hash));
});

test("local catalog configuration and placement preserve distant units; timing still broadens", () => {
  const plan = { graphicsTrack: Array.from({ length: 10 }, (_, index) => ({
    kind: "count-up", outStart: index * 10, outEnd: index * 10 + 3,
    spec: { end: 10, accent: "blue" }, placement: { x: 0, y: 0 },
  })) };
  const before = reviewUnits(plan, { source: "same" });
  plan.graphicsTrack[5].spec.end = 20;
  plan.graphicsTrack[5].placement.x = 100;
  const local = reviewUnits(plan, { source: "same" });
  assert.deepEqual(local.filter((unit, index) => unit.hash !== before[index].hash).map(unit => unit.id),
    ["plan", "graphicsTrack/4", "graphicsTrack/5", "graphicsTrack/6"]);
  plan.graphicsTrack[5].outEnd += 1;
  assert.ok(reviewUnits(plan, { source: "same" }).every((unit, index) => unit.hash !== local[index].hash));
});

test("actual render and assemble CLIs refuse before output or media work on missing or stale readiness", () => {
  const f = fixture("trim", "off"), output = path.join(f.dir, "TEST-output");
  const common = { encoding: "utf8" as const, env: { ...process.env, SNIPER_NODE_PATH: process.execPath } };
  const render = ["scripts/producer/render.py", f.planPath, f.manifest, output, "--approval-dir", f.dir,
    "--no-audit", "--allow-legacy-unadmitted", "--skip-graphics", "--resume"];
  const assemble = ["scripts/producer/assemble.py", path.join(f.dir, "absent-base.mp4"), f.planPath,
    path.join(f.dir, "final.mp4"), "--manifest", f.manifest, "--auto-base", "--allow-legacy-unadmitted"];
  const graph = ["scripts/producer/current_render_graph_cli.py", "--phase", "assemble", "--producer-dir", f.dir,
    "--plan", f.planPath, "--manifest", f.manifest, "--base", path.join(f.dir, "absent-base.mp4"),
    "--output", path.join(f.dir, "final.mp4"), "--", ...assemble];
  function refused() {
    for (const command of [render, assemble, graph]) {
      const result = spawnSync(pythonInterpreter(), command, common);
      assert.notEqual(result.status, 0, result.stderr);
      assert.match(result.stdout + result.stderr, /readiness/i);
    }
    assert.equal(existsSync(output), false);
    assert.equal(existsSync(path.join(f.dir, "final.mp4")), false);
  }
  try {
    refused();
    writeRenderReadiness(f.ctx, { draft: true, gates }); refused();
    approve(f);
    // Current review clears this boundary. Synthetic source/plan then fails normal media/schema admission.
    const current = spawnSync(pythonInterpreter(), render, common);
    assert.notEqual(current.status, 0);
    assert.doesNotMatch(current.stdout + current.stderr, /readiness refused/i);
    rmSync(output, { recursive: true, force: true });
    writeFileSync(path.join(f.source, "video.mp4"), "TEST changed source"); refused();
  } finally { f.cleanup(); }
});

test("actual mint command cannot use trim or draft to waive failed gates", () => {
  const f = fixture("trim", "off");
  const command = ["--import", "tsx", "scripts/infra/mint-delivery-approval.ts", f.dir];
  try {
    const missing = spawnSync(process.execPath, command, { encoding: "utf8" });
    assert.notEqual(missing.status, 0); assert.match(missing.stderr, /plan-reviews/);
    const failed = spawnSync(process.execPath, [...command, "--draft"], { encoding: "utf8" });
    assert.notEqual(failed.status, 0); assert.match(failed.stderr, /cut|gate|source/);
    assert.equal(existsSync(path.join(f.dir, ".sniper-render-ready.json")), false);
    assert.equal(existsSync(path.join(f.dir, ".sniper-draft-ready.json")), false);
  } finally { f.cleanup(); }
});

test("actual mint runs passing deterministic gates for separate draft and final admission", () => {
  const f = fixture("trim", "off");
  try {
    const projectFile = path.join(f.root, "project.json");
    const project = JSON.parse(readFileSync(projectFile, "utf8"));
    project.intent.excerpt = true; write(projectFile, project);
    const target = { mode: "longform", scope: "trim", excerpt: true, lanes: project.intent.lanes };
    write(f.planPath, { planVersion: 1, target, captions: { burn: false }, music: { enabled: false },
      cutTrack: [{ sourceId: "s1", start: 0, end: 4, speed: 1, rationale: "TEST keep the complete recorded sentence." }],
      cutDecisions: { schemaVersion: 1, removals: [] } });
    const manifest = JSON.parse(readFileSync(f.manifest, "utf8"));
    Object.assign(manifest.sources[0], { duration: 4, resolution: [1920, 1080], fps: 30 });
    write(f.manifest, manifest);
    const words = "This test keeps a complete sentence from the recorded source.".split(" ").map((word, index) =>
      ({ word, start: 0.2 + index * 0.3, end: 0.4 + index * 0.3 }));
    write(path.join(f.source, "words.json"), { transcript: [{ start: 0, end: 4, words,
      text: words.map(row => row.word).join(" ") }] });
    const ctx = prepareSavedPlanReview(f.dir).ctx, packet = readinessPacket(ctx);
    write(path.join(f.dir, PLAN_REVIEWS), { schemaVersion: 1, reviews: reviews(f, packet) });
    const command = ["--import", "tsx", "scripts/infra/mint-delivery-approval.ts", f.dir];
    const draft = spawnSync(process.execPath, [...command, "--draft"], { encoding: "utf8" });
    assert.equal(draft.status, 0, draft.stderr); assertRenderReadiness(ctx, true);
    assert.equal(existsSync(path.join(f.dir, ".sniper-render-ready.json")), false);
    const final = spawnSync(process.execPath, command, { encoding: "utf8" });
    assert.equal(final.status, 0, final.stderr); assertRenderReadiness(ctx);
  } finally { f.cleanup(); }
});

test("three local revisions admit unchanged review evidence only after fresh affected reviews", () => {
  const f = fixture("produced", "auto");
  try {
    const plan = JSON.parse(readFileSync(f.planPath, "utf8"));
    plan.graphicsTrack = Array.from({ length: 30 }, (_, index) => ({
      kind: "line-swap", outStart: index * 10, outEnd: index * 10 + 2, spec: { text: "before" },
    }));
    write(f.planPath, plan);
    const before = readinessPacket(f.ctx), retained = reviews(f, before);
    write(path.join(f.dir, PLAN_REVIEWS), { schemaVersion: 1, reviews: retained });
    for (const index of [3, 12, 25]) plan.graphicsTrack[index].spec.text = "after";
    write(f.planPath, plan);
    const after = readinessPacket(f.ctx);
    assert.throws(() => assertPlanReviews(f.dir, after), /current independent reviews/);
    const changed = new Set(after.units.filter((unit, index) => unit.hash !== before.units[index].hash).map(unit => unit.id));
    assert.equal(changed.size, 10); // Contextual plan assessment + three neighborhoods; 21 graphic checks retained.
    const refreshed = reviews(f, after).map(row => ({ ...row,
      units: Object.fromEntries(Object.entries(row.units).filter(([id]) => changed.has(id))),
      previews: row.previews.filter(preview => changed.has(preview.unitId)),
    }));
    write(path.join(f.dir, PLAN_REVIEWS), { schemaVersion: 1, reviews: [...retained, ...refreshed] });
    writeRenderReadiness(f.ctx, { gates }); assertRenderReadiness(f.ctx);
    const asset = path.join(f.root, "TEST-font.woff"); writeFileSync(asset, "TEST asset");
    plan.graphicsTrack[3].spec.fontPath = asset; write(f.planPath, plan);
    const fontBefore = readinessPacket(f.ctx);
    writeFileSync(asset, "TEST changed asset");
    assert.ok(readinessPacket(f.ctx).units.every((unit, index) => unit.hash !== fontBefore.units[index].hash));
  } finally { f.cleanup(); }
});

test("real command rejects missing reviews, accepts current evidence, and rejects changed intent", () => {
  const f = fixture("light", "off");
  const command = ["--import", "tsx", "scripts/infra/plan-readiness.ts", "check", f.dir, f.planPath, f.manifest];
  try {
    const missing = spawnSync(process.execPath, command, { encoding: "utf8" });
    assert.notEqual(missing.status, 0);
    approve(f);
    const passed = spawnSync(process.execPath, command, { encoding: "utf8" });
    assert.equal(passed.status, 0, passed.stderr);
    const snapshot = path.join(f.root, "snapshot.json");
    writeFileSync(snapshot, readFileSync(f.planPath));
    const snapshotCommand = [...command.slice(0, -2), snapshot, f.manifest];
    assert.equal(spawnSync(process.execPath, snapshotCommand, { encoding: "utf8" }).status, 0);
    write(snapshot, { target: { mode: "longform" }, cutTrack: [] });
    assert.notEqual(spawnSync(process.execPath, snapshotCommand, { encoding: "utf8" }).status, 0);
    const project = JSON.parse(readFileSync(path.join(f.root, "project.json"), "utf8"));
    project.intent.brief = "TEST a different instruction";
    write(path.join(f.root, "project.json"), project);
    assert.notEqual(spawnSync(process.execPath, command, { encoding: "utf8" }).status, 0);
  } finally { f.cleanup(); }
});
