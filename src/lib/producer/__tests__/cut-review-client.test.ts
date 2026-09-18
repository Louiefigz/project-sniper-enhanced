import assert from "node:assert/strict";
import { test } from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import CutReviewPanel, { CutReviewControl } from "@/components/producer/cut-review-panel";
import { cutWaitLabel, fetchCutReview, parseCutReviewDescription } from "../cut-review-client";
import { projectPrimaryActionLabel, projectPhaseCopy, projectCardSummary, canResumeAutoEdit } from "../project-state";

const dir = "/private/tmp/review/producer";
const hashes = { requestHash: "1".repeat(64), planHash: "2".repeat(64), executionKey: "3".repeat(64),
  receiptHash: "4".repeat(64), mediaSha256: "5".repeat(64) };
const description = { ok: true, state: "awaiting_cut_approval", ...hashes, expectedToken: "paused-job-token",
  waitStartedAt: "2026-09-06T01:02:00.000Z", previewStartedAt: "2026-09-06T01:01:00.000Z",
  waitStoppedAt: null, acceptanceState: "awaiting-decision", acceptanceError: null,
  durationSeconds: 12, width: 960, height: 540, accepted: false,
  scope: "cut-only-source-aspect-ungraded-unmixed-not-delivery", caveat: "Not an approved final.",
  mediaUrl: `/api/producer/cut-review/video?${new URLSearchParams({ dir,
    requestHash: hashes.requestHash, executionKey: hashes.executionKey, receiptHash: hashes.receiptHash })}` };

test("client accepts only exact historical scope, identity and local playback URL", () => {
  assert.deepEqual(parseCutReviewDescription(description, dir), description);
  for (const patch of [{ ok: false }, { accepted: true }, { scope: "approved-final" }, { extra: true },
    { durationSeconds: Infinity }, { width: 0 }, { receiptHash: "x" }, { expectedToken: "" }, { waitStartedAt: "yesterday" },
    { waitStartedAt: description.previewStartedAt.replace("01:01", "01:00") },
    { acceptanceState: "verifying" }, { waitStoppedAt: description.waitStartedAt }, { acceptanceError: "unknown" },
    { mediaUrl: "https://untrusted.example/movie.mp4" }, { mediaUrl: `${description.mediaUrl}&path=/etc/passwd` },
    { mediaUrl: `${description.mediaUrl}&dir=${encodeURIComponent(dir)}` },
    { mediaUrl: `${description.mediaUrl}#fragment` }]) {
    assert.throws(() => parseCutReviewDescription({ ...description, ...patch }, dir));
  }
  assert.throws(() => parseCutReviewDescription(description, "/different/producer"));
});

test("preview fetch is read-only, abortable, bounded and never retries a mutation", async () => {
  let calls = 0;
  const request: typeof fetch = async (url, init) => {
    calls += 1; assert.match(String(url), /^\/api\/producer\/cut-review\?/);
    assert.equal(init?.method, undefined); assert.equal(init?.redirect, "error");
    assert.equal(init?.cache, "no-store");
    return Response.json(description);
  };
  assert.deepEqual(await fetchCutReview(dir, new AbortController().signal, request), description);
  assert.equal(calls, 1);
  const aborted = new AbortController(); aborted.abort();
  await assert.rejects(fetchCutReview(dir, aborted.signal, request), { name: "AbortError" });
  assert.equal(calls, 1, "pre-canceled requests do not fetch");
  await assert.rejects(fetchCutReview(dir, new AbortController().signal, async () => new Response("x".repeat(16_385))), /size limit/);
  await assert.rejects(fetchCutReview(dir, new AbortController().signal,
    async () => Response.json({ error: "Cut changed" }, { status: 409 })), /Cut changed/);
});

test("review UI renders no unverified media or acceptance action before readback", () => {
  Object.assign(globalThis, { React });
  const panel = renderToStaticMarkup(React.createElement(CutReviewPanel, { dir }));
  assert.match(panel, /Review the story cut/);
  assert.match(panel, /Checking the saved cut and exact preview/);
  assert.doesNotMatch(panel, /<video|Accept cut|Generate video|approved final is ready/);
  const control = renderToStaticMarkup(React.createElement(CutReviewControl, { dir }));
  assert.match(control, /Review cut/); assert.match(control, /<dialog/);
  assert.doesNotMatch(control, /<video/);
});

test("waiting copy never offers ordinary resume, generation or final approval", () => {
  const stages = { ingested: true, transcribed: true, plan: true, base: false, final: false };
  const run = { kind: "auto_edit" as const, status: "awaiting_cut_approval" as const, phase: "authoring" as const,
    startedAt: description.previewStartedAt, updatedAt: description.waitStartedAt, message: "Waiting", events: [] };
  assert.equal(projectPrimaryActionLabel(stages, run), "Review cut");
  assert.equal(canResumeAutoEdit(run), false);
  assert.equal(projectPhaseCopy(stages, run).label, "Cut ready for your review");
  assert.match(projectCardSummary(stages, run).next, /Review cut/);
  assert.match(projectCardSummary(stages, run).safe, /cannot bypass/);
  assert.equal(cutWaitLabel(description.waitStartedAt, Date.parse(description.waitStartedAt) + 61_000), "1m 1s waiting for you");
  assert.match(cutWaitLabel(description.waitStartedAt, 0), /unavailable/);
});
