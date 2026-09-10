import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import StudioImportPanel from "@/components/producer/editor/studio-import-panel";
import { applyStudioImport, parseStudioImportProposal, parseStudioImportResult, prepareStudioImport,
  type StudioImportProposal, type StudioImportResult } from "../studio-import-client";

const proposal: StudioImportProposal = {
  ok: true, state: "ready", proposalId: "56c922de-383d-4d92-bb84-a49a1b0417a8",
  expectedPlanHash: "a".repeat(64), expectedPlanVersion: 4,
  changes: [{ graphicId: "graphic-1", kind: "statement-card", field: "spec.text", before: "Before", after: "After" }],
  blockers: [], warnings: [], caveat: "Draft only; render/QC remain required.",
};
const result: StudioImportResult = {
  ok: true, applied: true, alreadyApplied: false, planVersion: 5, planHash: "b".repeat(64),
  requiresRender: true, studioEditsPreserved: true, warnings: [],
};

test("proposal validation never enables import on missing, blocked or forged authority", () => {
  assert.deepEqual(parseStudioImportProposal(proposal), proposal);
  for (const fields of [{ proposalId: "../other" }, { proposalId: null }, { changes: [] },
    { expectedPlanHash: "garbage" }, { expectedPlanVersion: -1 }, { expectedPlanVersion: 1.5 },
    { expectedPlanVersion: Number.MAX_SAFE_INTEGER + 1 }, { blockers: ["unsupported edit"] },
    { state: "approved" }, { state: "blocked" }, { warnings: [null] },
    { changes: [{ ...proposal.changes[0], graphicId: "" }] },
    { changes: [{ ...proposal.changes[0], after: undefined }] }]) {
    assert.throws(() => parseStudioImportProposal({ ...proposal, ...fields }));
  }
  assert.equal(parseStudioImportProposal({ ...proposal, state: "unchanged", proposalId: null, changes: [] }).state, "unchanged");
  for (const fields of [{ requiresRender: false }, { studioEditsPreserved: false },
    { alreadyApplied: true }, { applied: false }, { planHash: "" }, { planVersion: Infinity }]) {
    assert.throws(() => parseStudioImportResult({ ...result, ...fields }));
  }
  assert.equal(parseStudioImportResult({ ...result, applied: false, alreadyApplied: true }).alreadyApplied, true);
});

test("prepare is explicit and sends no apply, force, render or authority override", async () => {
  const original = globalThis.fetch;
  const calls: { url: string; body: unknown }[] = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), body: JSON.parse(String(init?.body)) });
    assert.equal(init?.method, "POST");
    assert.equal(init?.cache, "no-store");
    return Response.json(proposal);
  };
  try {
    assert.deepEqual(await prepareStudioImport("/isolated/producer"), proposal);
    assert.deepEqual(calls, [{ url: "/api/producer/studio/import", body: { dir: "/isolated/producer", action: "prepare" } }]);
    const controller = new AbortController(); controller.abort();
    await assert.rejects(prepareStudioImport("/isolated/producer", controller.signal), { name: "AbortError" });
    assert.equal(calls.length, 1);
  } finally { globalThis.fetch = original; }
});

test("apply invalidates first, sends only exact proposal bindings, then reloads canonical draft", async () => {
  const original = globalThis.fetch;
  const order: string[] = [];
  globalThis.fetch = async (url, init) => {
    order.push("request");
    assert.equal(String(url), "/api/producer/studio/import");
    assert.deepEqual(JSON.parse(String(init?.body)), {
      dir: "/isolated/producer", action: "apply", proposalId: proposal.proposalId,
      expectedPlanHash: proposal.expectedPlanHash, expectedPlanVersion: 4,
    });
    return Response.json(result);
  };
  try {
    const observed = await applyStudioImport({ dir: "/isolated/producer", proposal,
      invalidatePreview: () => { order.push("invalidate"); },
      reloadDraft: async () => { order.push("reload"); return true; } });
    assert.deepEqual(order, ["invalidate", "request", "reload"]);
    assert.deepEqual(observed, { result, error: null, reloaded: true });
    assert.equal(proposal.expectedPlanVersion, 4, "proposal remains immutable for exact retry");
  } finally { globalThis.fetch = original; }
});

test("lost/error/malformed responses never leave an apparently current preview or retry fresh", async () => {
  const original = globalThis.fetch;
  try {
    for (const failure of ["network", "committed", "malformed", "conflict"]) {
      const order: string[] = [];
      let requests = 0;
      globalThis.fetch = async () => {
        order.push("request"); requests += 1;
        if (failure === "network") throw new Error("connection lost after send");
        if (failure === "malformed") return Response.json({ ...result, requiresRender: false });
        return Response.json({ ok: false, committed: failure === "committed", error: "exact draft needs reconciliation" },
          { status: failure === "conflict" ? 409 : 500 });
      };
      const observed = await applyStudioImport({ dir: "/isolated/producer", proposal,
        invalidatePreview: () => { order.push("invalidate"); },
        reloadDraft: async () => { order.push("reload"); return false; } });
      assert.deepEqual(order, ["invalidate", "request", "reload"]);
      assert.equal(requests, 1, "no automatic retry, fresh import or render fallback");
      assert.equal(observed.result, null); assert.ok(observed.error); assert.equal(observed.reloaded, false);
    }
  } finally { globalThis.fetch = original; }
});

test("invalid or pre-aborted apply does not send or invalidate; same proposal can be replayed", async () => {
  const original = globalThis.fetch;
  const bodies: string[] = [];
  globalThis.fetch = async (_url, init) => {
    bodies.push(String(init?.body));
    return Response.json({ ...result, applied: bodies.length === 1, alreadyApplied: bodies.length > 1 });
  };
  try {
    const input = { dir: "/isolated/producer", proposal, invalidatePreview: () => {}, reloadDraft: async () => true };
    const controller = new AbortController(); controller.abort();
    await assert.rejects(applyStudioImport({ ...input, signal: controller.signal,
      invalidatePreview: () => assert.fail("no mutation was requested") }), { name: "AbortError" });
    await assert.rejects(applyStudioImport({ ...input,
      proposal: { ...proposal, state: "unchanged", proposalId: null, changes: [] } }), /Preview supported/);
    assert.equal(bodies.length, 0);
    await applyStudioImport(input);
    assert.equal((await applyStudioImport(input)).result?.alreadyApplied, true);
    assert.equal(bodies[0], bodies[1], "retry uses same id and expected parent, not a refreshed authority");
  } finally { globalThis.fetch = original; }
});

test("UI shows proposed changes and draft-only action, with escaped text and blocked states", () => {
  const base = { action: null, proposal, error: null, message: null, elapsedMs: 400, warnings: [],
    blocked: null, prepare: async () => {}, apply: async () => {}, cancelPrepare: () => {}, applying: false };
  const html = renderToStaticMarkup(React.createElement(StudioImportPanel, { imported: base, unavailable: false }));
  assert.match(html, /Apply to Sniper draft/); assert.match(html, /Before/); assert.match(html, /After/);
  assert.doesNotMatch(html, />Export<|>Render updated video</);
  const blocked = renderToStaticMarkup(React.createElement(StudioImportPanel, { unavailable: false,
    imported: { ...base, proposal: { ...proposal, state: "blocked", proposalId: null, blockers: ["<script>bad</script>"] } } }));
  assert.doesNotMatch(blocked, /Apply to Sniper draft|<script>/);
  assert.match(blocked, /&lt;script&gt;/);
});
