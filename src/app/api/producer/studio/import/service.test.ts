import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { applyImport, importDependencies, prepareImport, type ImportDependencies } from "./service";
import { ImportError, type Capture, type ImportPrepared } from "./model";
import { jsonText, readHead, readProposal, readSession, seal, sha } from "./files";
import { emptyFixture } from "./fixture_test";

function harness() {
  const f = emptyFixture(); let host = "original"; let copy = "Ship the *system*"; let releases = 0;
  const instance = "original instance"; const instanceFile = "compositions/one.html";
  const manifestText = JSON.stringify({ files: { "index.html": sha("original"), [instanceFile]: sha(instance) },
    entries: [{ file: instanceFile, kind: "statement-card", planId: f.plan.graphicsTrack![0].id }] });
  const capture = (): Capture => { const planText = fs.readFileSync(path.join(f.dir, "edit_plan.json"), "utf8");
    return { planText, planHash: sha(planText), authority: "fixed", snapshot: sha(host), baseHash: "base",
      manifestText, files: { "index.html": sha(host) }, textFiles: { "index.html": host } }; };
  const deps: ImportDependencies = { ...importDependencies,
    capture: async () => capture(), recheck: (_dir: string, c: Capture) => { assert.equal(c.snapshot, capture().snapshot); assert.equal(c.planHash, capture().planHash); },
    baseline: async () => ({ host: "original", instances: { [instanceFile]: instance } }),
    diff: async () => ({ candidate: { ...f.plan, graphicsTrack: [{ ...f.plan.graphicsTrack![0], spec: { ...f.plan.graphicsTrack![0].spec, text: copy } }] }, blockers: [], warnings: [] }),
    guard: () => ({ lease: { release: () => { releases += 1; } } } as ReturnType<typeof importDependencies.guard>),
  };
  return { ...f, deps, edit: (value: string) => { host = value; copy = value; }, capture,
    releases: () => releases, cleanup: () => fs.rmSync(f.root, { recursive: true, force: true }) };
}

function input(result: ImportPrepared) {
  assert.equal(result.state, "ready"); assert.ok(result.proposalId);
  return { proposalId: result.proposalId, expectedPlanHash: result.expectedPlanHash, expectedPlanVersion: result.expectedPlanVersion };
}

test("repeated imports retain immutable original; undo-to-original is pending; no-op does not save", async () => {
  const h = harness();
  try {
    assert.equal((await prepareImport(h.dir, h.deps) as ImportPrepared).state, "unchanged");
    const original = fs.readFileSync(path.join(h.dir, "edit_plan.json"), "utf8");
    h.edit("Make the *system* clear"); const one = input(await prepareImport(h.dir, h.deps) as ImportPrepared);
    const result = await applyImport(h.dir, one, h.deps); assert.ok(!(result instanceof Response)); assert.equal(result.planVersion, 2);
    assert.equal((await applyImport(h.dir, one, h.deps) as { alreadyApplied: boolean }).alreadyApplied, true);
    h.edit("Quality starts with *intent*"); const two = input(await prepareImport(h.dir, h.deps) as ImportPrepared);
    await applyImport(h.dir, two, h.deps);
    h.edit("Ship the *system*"); const undo = input(await prepareImport(h.dir, h.deps) as ImportPrepared);
    await applyImport(h.dir, undo, h.deps);
    const plan = JSON.parse(fs.readFileSync(path.join(h.dir, "edit_plan.json"), "utf8"));
    assert.equal(plan.planVersion, 4); assert.equal(plan.graphicsTrack[0].spec.text, h.plan.graphicsTrack![0].spec!.text);
    assert.equal(readSession(h.dir)!.originalPlanText, original);
    assert.equal((await prepareImport(h.dir, h.deps) as ImportPrepared).state, "unchanged");
    assert.equal(fs.readdirSync(path.join(h.dir, "plan-history")).length, 3);
  } finally { h.cleanup(); }
});

test("same-version external edit and changed Studio snapshot never overwrite the canonical draft", async () => {
  const h = harness();
  try {
    h.edit("First *change*"); const proposal = input(await prepareImport(h.dir, h.deps) as ImportPrepared);
    h.edit("Second *change*");
    await assert.rejects(applyImport(h.dir, proposal, h.deps), /Studio changed since/u);
    fs.writeFileSync(path.join(h.dir, "edit_plan.json"), jsonText({ ...h.plan, extra: "external edit" }));
    await assert.rejects(applyImport(h.dir, proposal, h.deps), /draft changed outside/u);
    assert.equal(readHead(h.dir), null);
  } finally { h.cleanup(); }
});

test("crash after draft save is committed, prepare recovers the tip, and retry does not resave", async () => {
  const h = harness();
  try {
    h.edit("Recover the *draft*"); const proposal = input(await prepareImport(h.dir, h.deps) as ImportPrepared);
    h.deps.save = async (arg) => { await importDependencies.save(arg); throw new Error("simulated crash after atomic save"); };
    await assert.rejects(applyImport(h.dir, proposal, h.deps), (error: ImportError) => error.committed);
    assert.equal((await prepareImport(h.dir, h.deps) as ImportPrepared).state, "unchanged");
    const result = await applyImport(h.dir, proposal, h.deps);
    assert.ok(!(result instanceof Response)); assert.equal(result.alreadyApplied, true); assert.equal(result.applied, false);
    assert.equal(fs.readdirSync(path.join(h.dir, "plan-history")).length, 1);
  } finally { h.cleanup(); }
});

test("failure before save retains explicit same-proposal retry; lease always releases", async () => {
  const h = harness();
  try {
    h.edit("Keep the *checkpoint*"); const proposal = input(await prepareImport(h.dir, h.deps) as ImportPrepared);
    h.deps.save = async () => { throw new Error("simulated save failure"); };
    await assert.rejects(applyImport(h.dir, proposal, h.deps), /simulated save failure/u);
    assert.equal((await prepareImport(h.dir, h.deps) as ImportPrepared).proposalId, proposal.proposalId);
    h.deps.save = importDependencies.save;
    await applyImport(h.dir, proposal, h.deps);
    assert.equal(h.releases(), 4);
  } finally { h.cleanup(); }
});

test("new edits explicitly supersede only unsaved intents; undo/no-op never strands the next review", async () => {
  const h = harness();
  try {
    h.edit("First *change*"); const old = input(await prepareImport(h.dir, h.deps) as ImportPrepared);
    const original = fs.readFileSync(path.join(h.dir, "edit_plan.json"));
    h.deps.save = async () => { throw new Error("interrupted before write"); };
    await assert.rejects(applyImport(h.dir, old, h.deps), /interrupted/u);
    h.edit("Ship the *system*");
    assert.equal((await prepareImport(h.dir, h.deps) as ImportPrepared).state, "unchanged");
    assert.deepEqual(fs.readFileSync(path.join(h.dir, "edit_plan.json")), original);
    h.edit("Second *change*"); const fresh = input(await prepareImport(h.dir, h.deps) as ImportPrepared);
    assert.notEqual(fresh.proposalId, old.proposalId);
    assert.equal(readProposal(h.dir, fresh.proposalId).previous, null);
    assert.equal(readHead(h.dir)!.proposalId, old.proposalId);
    h.deps.save = importDependencies.save;
    await applyImport(h.dir, fresh, h.deps);
    assert.equal(readHead(h.dir)!.proposalId, fresh.proposalId);
    assert.equal(readProposal(h.dir, old.proposalId).changes[0].after, "First *change*");
    assert.equal(fs.readdirSync(path.join(h.dir, "plan-history")).length, 1);
    assert.equal((await prepareImport(h.dir, h.deps) as ImportPrepared).state, "unchanged");
  } finally { h.cleanup(); }
});

function rewriteSealed(file: string, value: object): void {
  fs.writeFileSync(file, jsonText(seal(Object.fromEntries(Object.entries(value).filter(([key]) => key !== "digest")))));
}

test("re-sealed original object, host or instance corruption fails before an unreviewed plan change", async () => {
  const h = harness();
  try {
    await prepareImport(h.dir, h.deps); const original = readSession(h.dir)!;
    const file = path.join(h.dir, ".sniper-studio-imports/session.json");
    h.edit("Reviewed *copy*");
    const altered = structuredClone(original); altered.originalPlan.cutTrack![0].end = 11;
    for (const bad of [altered, { ...original, host: "unknown code" }, { ...original, instances: {} }]) {
      rewriteSealed(file, bad);
      await assert.rejects(prepareImport(h.dir, h.deps), /original.*(?:agree|manifest)/u);
      assert.equal(readHead(h.dir), null);
      assert.equal(JSON.parse(fs.readFileSync(path.join(h.dir, "edit_plan.json"), "utf8")).cutTrack[0].end, 12);
    }
  } finally { h.cleanup(); }
});

test("first apply rejects inconsistent re-sealed candidate receipts before head or draft writes", async () => {
  const h = harness();
  try {
    h.edit("Reviewed *copy*"); const request = input(await prepareImport(h.dir, h.deps) as ImportPrepared);
    const proposal = readProposal(h.dir, request.proposalId);
    const file = path.join(h.dir, ".sniper-studio-imports", `${proposal.id}.json`);
    for (const bad of [{ ...proposal, afterHash: "0".repeat(64) }, { ...proposal, afterVersion: 99 },
      { ...proposal, candidateText: "{}" }, { ...proposal, changes: [] },
      { ...proposal, capture: { ...proposal.capture, planText: "{}" } }]) {
      rewriteSealed(file, bad);
      await assert.rejects(applyImport(h.dir, request, h.deps), /proposal.*(?:bindings|changes)/u);
      assert.equal(readHead(h.dir), null);
      assert.equal(fs.existsSync(path.join(h.dir, "plan-history")), false);
      assert.equal(JSON.parse(fs.readFileSync(path.join(h.dir, "edit_plan.json"), "utf8")).planVersion, 1);
    }
  } finally { h.cleanup(); }
});

test("busy writer, pending refit, unstable IDs, and unknown candidate fields fail closed", async () => {
  const h = harness();
  try {
    const busy = { ...h.deps, guard: () => ({ response: new Response("busy", { status: 409 }) }) };
    assert.ok(await prepareImport(h.dir, busy) instanceof Response); assert.equal(readSession(h.dir), null);
    fs.writeFileSync(path.join(h.dir, ".sniper-plan-refit.pending.json"), "{}");
    await assert.rejects(prepareImport(h.dir, h.deps), /pending cut-refit/u);
    fs.unlinkSync(path.join(h.dir, ".sniper-plan-refit.pending.json"));
    h.edit("Allowed *copy*");
    h.deps.diff = async () => ({ candidate: { ...h.plan, music: { enabled: true } }, blockers: [], warnings: [] });
    await assert.rejects(prepareImport(h.dir, h.deps), /unsupported plan fields/u);
    assert.equal(readHead(h.dir), null);
  } finally { h.cleanup(); }
  const bad = harness();
  try {
    fs.writeFileSync(path.join(bad.dir, "edit_plan.json"), jsonText({ ...bad.plan, graphicsTrack: [{ ...bad.plan.graphicsTrack![0], id: "legacy" }] }));
    await assert.rejects(prepareImport(bad.dir, bad.deps), /stable graphics/u);
  } finally { bad.cleanup(); }
});
