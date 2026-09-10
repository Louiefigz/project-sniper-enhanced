import assert from "node:assert/strict";
import { test } from "node:test";
import { getStudioStatus, openStudio, type StudioDependencies } from "./service";
import { StudioError, type StudioInspection } from "./model";

const DIR = "/fixture/producer";
const RECORD = { pid: 1234, port: 3991, startedAt: "2026-09-06T12:00:00Z" };

function harness() {
  const calls: string[] = [];
  let generated = true;
  let live = true;
  let count = 0;
  const inspection: StudioInspection = {
    parent: "parent-1", viewExists: true, viewCurrent: true,
    pendingEdits: [], blockers: [],
  };
  const deps: StudioDependencies = {
    paths: () => { calls.push("paths"); },
    inspect: async () => { calls.push("inspect"); count += 1; return { ...inspection }; },
    record: () => generated ? RECORD : null,
    ready: async () => live,
    owned: async () => live,
    wait: async () => { calls.push("wait"); },
    media: async () => "media-hash",
    start: async (_dir, reuse) => { calls.push(`start:${reuse}`); generated = true; live = true; inspection.viewCurrent = true; },
    cleanup: async () => { calls.push("cleanup"); },
    guard: () => { calls.push("lease"); return { lease: { release: () => { calls.push("release"); } } }; },
  };
  return { deps, calls, inspection, count: () => count,
    noSession: () => { generated = false; live = false; } };
}

test("reuses a live current projection and preserves unsynced edits", async () => {
  const h = harness();
  h.inspection.pendingEdits = ["index.html: modified"];
  const result = await openStudio(DIR, h.deps);
  assert.ok(!(result instanceof Response));
  assert.equal(result.reused, true);
  assert.equal(result.url, "http://127.0.0.1:3991/#project/studio");
  assert.deepEqual(result.pendingEdits, ["index.html: modified"]);
  assert.ok(!h.calls.some((call) => call.startsWith("start")));
  assert.equal(h.calls[0], "lease");
  assert.equal(h.calls.at(-1), "release");
});

test("restarts a current unsynced projection without regeneration", async () => {
  const h = harness(); h.noSession();
  h.inspection.pendingEdits = ["index.html: modified"];
  await openStudio(DIR, h.deps);
  assert.ok(h.calls.includes("start:true"));
});

test("new projection is generated once under the lease", async () => {
  const h = harness(); h.noSession();
  h.inspection.viewCurrent = false; h.inspection.viewExists = false;
  await openStudio(DIR, h.deps);
  assert.ok(h.calls.includes("start:false"));
  assert.equal(h.calls.at(-1), "release");
});

test("stale or unbound unsynced edits block opening without touching the view", async () => {
  const h = harness();
  h.inspection.blockers = ["Studio edits belong to an older plan/base"];
  await assert.rejects(openStudio(DIR, h.deps), /older plan/);
  assert.ok(!h.calls.some((call) => call.startsWith("start")));
  assert.equal(h.calls.at(-1), "release");
});

test("a live stale projection is never regenerated under an operator's browser", async () => {
  const h = harness(); h.inspection.viewCurrent = false;
  await assert.rejects(openStudio(DIR, h.deps), /Stop that Studio session/);
  assert.ok(!h.calls.some((call) => call.startsWith("start")));
  assert.equal(h.calls.at(-1), "release");
  const state = await getStudioStatus(DIR, h.deps);
  assert.equal(state.canOpen, false);
  assert.equal(state.url, null);
});

test("an unguarded live session is blocked without stopping it or altering pending edits", async () => {
  const h = harness(); h.deps.ready = async () => false;
  h.inspection.pendingEdits = ["index.html: modified"];
  await assert.rejects(openStudio(DIR, h.deps), /not proven review-only/);
  assert.ok(!h.calls.some((call) => call.startsWith("start") || call === "cleanup"));
  assert.equal(h.calls.at(-1), "release");
  const state = await getStudioStatus(DIR, h.deps);
  assert.equal(state.canOpen, false);
  assert.equal(state.url, null);
  assert.deepEqual(state.pendingEdits, ["index.html: modified"]);
});

test("busy project never starts inspection or generation", async () => {
  const h = harness();
  h.deps.guard = () => ({ response: new Response("busy", { status: 409 }) });
  const response = await openStudio(DIR, h.deps);
  assert.ok(response instanceof Response);
  assert.equal(response.status, 409);
  assert.deepEqual(h.calls, []);
});

test("timeout cleans only a newly started process and releases the lease", async () => {
  const h = harness(); h.noSession();
  h.deps.wait = async () => { throw new StudioError("timeout", 504); };
  await assert.rejects(openStudio(DIR, h.deps), (error: StudioError) => error.status === 504);
  assert.ok(h.calls.includes("cleanup"));
  assert.equal(h.calls.at(-1), "release");
});

test("launch failure and cleanup failure still release the lease", async () => {
  const h = harness(); h.noSession();
  h.deps.start = async () => { throw new StudioError("failed", 502); };
  h.deps.cleanup = async () => { throw new Error("cleanup failed"); };
  const original = console.error; const logged: unknown[] = [];
  console.error = (...args: unknown[]) => { logged.push(args); };
  try { await assert.rejects(openStudio(DIR, h.deps), /failed/); }
  finally { console.error = original; }
  assert.equal(logged.length, 1);
  assert.equal(h.calls.at(-1), "release");
});

test("stale parent after generation cannot return a ready URL", async () => {
  const h = harness(); h.noSession();
  h.deps.inspect = async () => {
    const result = { ...h.inspection };
    h.inspection.parent = "changed";
    return result;
  };
  await assert.rejects(openStudio(DIR, h.deps), /inputs changed/);
  assert.ok(h.calls.includes("cleanup"));
  assert.equal(h.calls.at(-1), "release");
});

test("media identity changes cannot return an approved-looking session", async () => {
  const h = harness(); let hash = 0;
  h.deps.media = async () => String(hash++);
  await assert.rejects(openStudio(DIR, h.deps), /inputs changed/);
  assert.ok(!h.calls.includes("cleanup"), "never stop a reused session");
  assert.equal(h.calls.at(-1), "release");
});

test("status is read only and carries an explicit parity caveat", async () => {
  const h = harness();
  const result = await getStudioStatus(DIR, h.deps);
  assert.equal(result.state, "ready");
  assert.match(result.caveat, /not the approved final/);
  assert.deepEqual(h.calls, ["paths", "inspect"]);
});
