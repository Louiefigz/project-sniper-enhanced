import assert from "node:assert/strict";
import { test } from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { fetchAcceptedCutStatus, parseAcceptedCutStatus } from "../cut-accepted-status-client";
import CutAcceptanceControls from "@/components/producer/cut-acceptance-controls";
import CutAcceptedPanel from "@/components/producer/cut-accepted-panel";
import type { CutReviewDescription } from "../cut-review-client";

const status = { ok: true, cutAccepted: true, scope: "human-cut-only-not-delivery", state: "cut_accepted",
  acceptanceHash: "5".repeat(64), requestHash: "1".repeat(64), previewAttempt: 1, continuationAttempt: 2,
  canRetryContinuation: true, waitStoppedAt: "2026-09-06T01:02:03.000Z", timingState: "verified-activation",
  decisionSubmittedAt: "2026-09-06T01:02:03.000Z", caveat: "Cut-only acceptance, not final approval." };

test("accepted status preserves truthful worker state and exact historical scope", () => {
  assert.deepEqual(parseAcceptedCutStatus(status), status);
  for (const state of ["running", "failed", "interrupted", "complete"]) {
    assert.equal(parseAcceptedCutStatus({ ...status, state, canRetryContinuation: false }).state, state);
  }
  assert.equal(parseAcceptedCutStatus({ ...status, timingState: "unavailable-legacy-activation", waitStoppedAt: null }).waitStoppedAt, null);
  assert.equal(parseAcceptedCutStatus({ ...status, waitStoppedAt: "2026-09-06T01:05:03.000Z" }).decisionSubmittedAt, status.decisionSubmittedAt);
  for (const change of [{ state: "awaiting_cut_approval" }, { state: "running" }, { cutAccepted: false },
    { scope: "final-approved" }, { workerPid: 123 }, { expectedToken: "secret" }, { acceptanceHash: "x" },
    { continuationAttempt: 1 }, { previewAttempt: 0 }, { waitStoppedAt: "yesterday" }, { caveat: "" },
    { waitStoppedAt: null }, { timingState: "unavailable-legacy-activation" }, { decisionSubmittedAt: "yesterday" },
    { waitStoppedAt: "2026-09-06T01:01:03.000Z" }]) {
    assert.throws(() => parseAcceptedCutStatus({ ...status, ...change }));
  }
});

test("accepted status fetch is read-only and abortable, never an implicit continuation retry", async () => {
  let reads = 0;
  const request: typeof fetch = async (url, init) => {
    reads += 1; assert.equal(url, "/api/producer/cut-review/accept?dir=%2Fp");
    assert.equal(init?.method, undefined); assert.equal(init?.cache, "no-store"); assert.equal(init?.redirect, "error");
    return Response.json(status);
  };
  assert.deepEqual(await fetchAcceptedCutStatus("/p", new AbortController().signal, request), status);
  await assert.rejects(fetchAcceptedCutStatus("/p", AbortSignal.abort(), request), { name: "AbortError" });
  assert.equal(reads, 1);
  await assert.rejects(fetchAcceptedCutStatus("/p", new AbortController().signal,
    async () => Response.json({ error: "Source identity differs" }, { status: 409 })), /Source identity differs/);
});

test("UI never auto-attests listening/watching or offers an unverified pending retry", () => {
  Object.assign(globalThis, { React });
  const review = { acceptanceState: "awaiting-decision" } as CutReviewDescription;
  for (const playable of [false, true]) {
    const markup = renderToStaticMarkup(React.createElement(CutAcceptanceControls, { dir: "/p", review, playable }));
    assert.equal((markup.match(/type="checkbox"/g) ?? []).length, 4);
    assert.doesNotMatch(markup, /checked=/);
    assert.match(markup, /<button[^>]*disabled=""/);
    assert.match(markup, /Accept cut &amp; continue saved brief/);
    assert.match(markup, /does not approve a finished video/);
  }
  const pending = renderToStaticMarkup(React.createElement(CutAcceptedPanel, { dir: "/p" }));
  assert.match(pending, /Verifying the saved human decision/);
  assert.doesNotMatch(pending, /Retry continuation|<video|final video is ready/);
  const verifying = renderToStaticMarkup(React.createElement(CutAcceptanceControls,
    { dir: "/p", review: { ...review, acceptanceState: "verifying" }, playable: true }));
  assert.match(verifying, /Retry saved cut decision/);
  assert.doesNotMatch(verifying, /Accept cut &amp;|type="checkbox"|checked=/);
  assert.match(verifying, /cannot make a new choice or bypass a live verifier/);
});
