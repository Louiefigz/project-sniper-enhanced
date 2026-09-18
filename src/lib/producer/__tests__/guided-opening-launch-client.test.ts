import assert from "node:assert/strict";
import { test } from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { GuidedOpeningLaunchControls } from "@/components/producer/guided-opening-panel";
import { clearConfirmedOpeningLaunch, fetchOpeningLaunchStatus, openingLaunchSubmission, parseOpeningLaunchResult,
  parseOpeningLaunchStatus, readPendingOpeningLaunch, retainOpeningLaunch, submitOpeningLaunch, type OpeningLaunchStatus } from "../guided-opening-launch-client";

Object.assign(globalThis, { React });
const DIR = "/private/tmp/TEST-only/producer", HASH = "a".repeat(64), ID = "11111111-1111-4111-8111-111111111111";
const REQUEST = { expectedToken: "TEST-token", expectedJournalHash: HASH, proposalReadinessHash: HASH, treatmentDraftRevisionHash: HASH };
const ELIGIBLE: OpeningLaunchStatus = { ok: true, state: "eligible", detail: "TEST-only eligible metadata, not authority", request: REQUEST, receivedAt: null };
const RESULT = { ok: true, replayed: false, state: "launch-recorded", journalHash: HASH, requestId: ID, openingApproved: false, bodyGenerated: false, deliveryApproved: false };
const submission = () => openingLaunchSubmission(ELIGIBLE, null, () => ID);
function storage() {
  const values = new Map<string, string>();
  return { values, getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => { values.set(key, value); }, removeItem: (key: string) => { values.delete(key); } };
}

test("launch metadata and acknowledgement are closed, exact and distinct from media/approval", () => {
  assert.deepEqual(parseOpeningLaunchStatus(ELIGIBLE), ELIGIBLE);
  for (const state of ["unavailable", "failed", "launch-recorded"] as const) {
    parseOpeningLaunchStatus({ ...ELIGIBLE, state, request: null, receivedAt: "2026-09-06T00:00:00.000Z" });
  }
  for (const patch of [{ ok: false }, { state: "running" }, { media: {} }, { openingApproved: true }, { receivedAt: "2026-09-06" },
    { request: null }, { request: { ...REQUEST, token: "another" } }, { request: { ...REQUEST, expectedJournalHash: "x" } }]) {
    assert.throws(() => parseOpeningLaunchStatus({ ...ELIGIBLE, ...patch }));
  }
  assert.throws(() => parseOpeningLaunchStatus({ ...ELIGIBLE, state: "launch-recorded", request: null }));
  assert.deepEqual(parseOpeningLaunchResult(RESULT, ID), RESULT);
  for (const patch of [{ requestId: "22222222-2222-4222-8222-222222222222" }, { bodyGenerated: true }, { openingApproved: true },
    { deliveryApproved: true }, { state: "running" }, { replayed: 1 }, { journalHash: "x" }, { media: {} }]) {
    assert.throws(() => parseOpeningLaunchResult({ ...RESULT, ...patch }, ID));
  }
});

test("terminal launch metadata clears the transient warning but retains the duplicate-action fence", () => {
  const props = { busy: false, retry: false, recorded: true, paused: false, error: null, onGenerate: () => {}, onRecheck: () => {} };
  for (const state of ["unavailable", "failed", "eligible"] as const) {
    const html = renderToStaticMarkup(React.createElement(GuidedOpeningLaunchControls,
      { ...props, status: { ...ELIGIBLE, state, request: state === "eligible" ? REQUEST : null } }));
    assert.doesNotMatch(html, /Opening launch recorded\.|>Generate opening</);
  }
  const unknown = renderToStaticMarkup(React.createElement(GuidedOpeningLaunchControls, { ...props, status: null }));
  assert.match(unknown, /Opening launch recorded\./);
});

test("lost response retains exactly one UUID; stale/malformed/browser storage is never fresh authority", () => {
  const store = storage(), first = submission(); retainOpeningLaunch(DIR, first, store);
  assert.deepEqual(readPendingOpeningLaunch(DIR, store), first);
  assert.deepEqual(openingLaunchSubmission(ELIGIBLE, readPendingOpeningLaunch(DIR, store), () => { throw Error("must not mint"); }), first);
  assert.equal(readPendingOpeningLaunch("/OTHER/producer", store), null);
  assert.throws(() => openingLaunchSubmission({ ...ELIGIBLE, request: { ...REQUEST, expectedToken: "changed" } }, first, () => ID), /prior request/);
  assert.throws(() => openingLaunchSubmission({ ...ELIGIBLE, state: "failed", request: null }, first, () => ID), /eligibility/);
  clearConfirmedOpeningLaunch(DIR, "other-id", store); assert.deepEqual(readPendingOpeningLaunch(DIR, store), first);
  clearConfirmedOpeningLaunch(DIR, ID, store); assert.equal(readPendingOpeningLaunch(DIR, store), null);
  assert.throws(() => retainOpeningLaunch(DIR, first, { ...store, setItem: () => {} }), /safely retained/);
  retainOpeningLaunch(DIR, first, store); const key = [...store.values.keys()][0];
  for (const text of ["x".repeat(16_385), "{}", JSON.stringify({ dir: "/OTHER", submission: first }), JSON.stringify({ dir: DIR, submission: { ...first, approved: true } })]) {
    store.values.set(key, text); assert.throws(() => readPendingOpeningLaunch(DIR, store));
  }
});

test("network calls are bounded/abortable; POST is exact once and unknown or wrong acknowledgements never retry", async () => {
  let reads = 0, posts = 0;
  const request: typeof fetch = async (url, init) => {
    assert.equal(init?.cache, "no-store"); assert.equal(init?.redirect, "error");
    if (!init?.method) { reads++; assert.equal(String(url), `/api/producer/guided-opening/launch?${new URLSearchParams({ dir: DIR })}`); return Response.json(ELIGIBLE); }
    posts++; assert.equal(init.method, "POST"); assert.equal(String(url), "/api/producer/guided-opening/launch");
    assert.deepEqual(JSON.parse(String(init.body)), { dir: DIR, submission: submission() }); return Response.json(RESULT, { status: 202 });
  };
  const signal = new AbortController().signal;
  await fetchOpeningLaunchStatus(DIR, signal, request); await submitOpeningLaunch({ dir: DIR, submission: submission(), signal }, request);
  assert.equal(reads, 1); assert.equal(posts, 1);
  const aborted = new AbortController(); aborted.abort();
  await assert.rejects(submitOpeningLaunch({ dir: DIR, submission: submission(), signal: aborted.signal }, request)); assert.equal(posts, 1);
  let lost = 0;
  await assert.rejects(submitOpeningLaunch({ dir: DIR, submission: submission(), signal }, async () => { lost++; throw Error("TEST lost connection"); }), /lost connection/);
  assert.equal(lost, 1);
  await assert.rejects(submitOpeningLaunch({ dir: DIR, submission: submission(), signal }, async () => Response.json(RESULT)), /recorded request/);
  await assert.rejects(fetchOpeningLaunchStatus(DIR, signal, async () => new Response("x".repeat(16_385))), /size limit/);
});

test("launch UI offers only explicit eligible actions and never advertises running/approved/full-video status", () => {
  const props = { busy: false, retry: false, recorded: false, paused: false, error: null, onGenerate: () => {}, onRecheck: () => {} };
  const eligible = renderToStaticMarkup(React.createElement(GuidedOpeningLaunchControls, { ...props, status: ELIGIBLE }));
  assert.match(eligible, />Generate opening</); assert.match(eligible, /unfinished stages/); assert.match(eligible, /never restarts/);
  const retry = renderToStaticMarkup(React.createElement(GuidedOpeningLaunchControls, { ...props, status: ELIGIBLE, retry: true, busy: true }));
  assert.match(retry, /Recording opening request/); assert.match(retry, /disabled/);
  for (const state of ["unavailable", "failed", "launch-recorded"] as const) {
    const html = renderToStaticMarkup(React.createElement(GuidedOpeningLaunchControls, { ...props, status: { ...ELIGIBLE, state, request: null }, paused: true }));
    assert.doesNotMatch(html, />Generate opening<|>Approve|<video|<iframe/);
    assert.match(html, /Recheck launch status/); assert.match(html, /Automatic metadata checks paused/);
    if (state === "launch-recorded") assert.match(html, /does not prove that a worker is running/);
  }
});
