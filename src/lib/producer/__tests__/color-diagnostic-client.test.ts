import assert from "node:assert/strict";
import test from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import { createElement } from "react";
import { unknownColorContext } from "../color-diagnostic";
import { colorResultMatchesContexts, parseColorDescriptor, parseColorJob } from "../color-diagnostic-client";
import type { ColorGroup, ColorJob } from "../color-diagnostic";
import ColorSourceControls from "../../../components/producer/editor/color-source-controls";
import ColorResult from "../../../components/producer/editor/color-result";
const source = { id: "raw-1", label: "camera.mp4", duration: 90, sha256: "a".repeat(64) };
const descriptor = { ok: true, kind: "descriptor", planHash: "b".repeat(64), manifestHash: "c".repeat(64), cutHash: "d".repeat(64), sources: [source], blockers: [], projectHistory: [] };
const job = { ok: true, kind: "job", jobId: "00000000-0000-4000-8000-000000000001", state: "complete", startedAt: "2026-09-06T00:00:00.000Z",
  elapsedMs: 1000, queueMs: 0, cleanupVerified: true, inputsRevalidated: true, parentsCurrent: true, error: null,
  planHash: "b".repeat(64), manifestHash: "c".repeat(64), diagnosticId: null, groups: [], caveats: [], timings: [],
  reviewState: "unreviewed", deliveryApproved: false, qualityQualified: false, writesGrade: false };
test("default source controls do not infer neutral lighting or untransformed history", () => {
  const value = unknownColorContext(source);
  assert.equal(value.sourceProfile, "unknown"); assert.equal(value.historyState, "unknown"); assert.equal(value.lightingGroups[0].intent, "unknown");
  const html = renderToStaticMarkup(createElement(ColorSourceControls, { source, value, disabled: false, onChange: () => {} }));
  assert.equal((html.match(/value="unknown" selected=""/g) ?? []).length, 3);
  assert(html.includes("whole-source") || html.includes("Whole-source")); assert(!html.includes("application/json"));
});
test("client rejects approval claims and unbounded/invalid screening response", () => {
  assert.equal(parseColorDescriptor(descriptor).sources.length, 1);
  assert.equal(parseColorJob(job).writesGrade, false);
  for (const patch of [{ deliveryApproved: true }, { writesGrade: true }, { qualityQualified: true }, { elapsedMs: NaN }, { queueMs: 1 }]) {
    assert.throws(() => parseColorJob({ ...job, ...patch }));
  }
});
test("result panel makes private status and absent grade authority explicit", () => {
  const html = renderToStaticMarkup(createElement(ColorResult, { job: parseColorJob({ ...job, parentsCurrent: false }) }));
  assert(html.includes("Private / unreviewed")); assert(html.includes("No grade, render, or approval"));
  assert(html.includes("Saved inputs changed")); assert(!html.includes("Apply grade"));
});
test("edited profile, history, lighting or notes cannot relabel a retained result", () => {
  const context = unknownColorContext(source);
  const group: ColorGroup = { sourceId: source.id, groupId: "whole-source", intent: "unknown", context,
    metadata: {}, retainedIntervals: [], unsampledIntervalIndices: [], observations: [], sampledFrames: 0,
    minimumMeanLuma: null, maximumMeanLuma: null, worstNominalBlackFraction: null, worstNominalWhiteFraction: null,
    warnings: [], screeningOffsets: [] };
  const result: ColorJob = { ...parseColorJob(job), groups: [group] };
  assert.equal(colorResultMatchesContexts(result, [context]), true);
  const reordered = Object.fromEntries(Object.entries(context).reverse());
  assert.equal(colorResultMatchesContexts(result, [reordered as typeof context]), true);
  for (const patch of [{ sourceProfile: "bt709-sdr" as const }, { historyState: "known" as const },
    { lightingGroups: [{ ...context.lightingGroups[0], intent: "dark" as const }] },
    { lightingGroups: [{ ...context.lightingGroups[0], description: "new notes" }] }]) {
    assert.equal(colorResultMatchesContexts(result, [{ ...context, ...patch }]), false);
  }
  assert.equal(colorResultMatchesContexts({ ...result, groups: [group, group] }, [context, context]), false);
  const html = renderToStaticMarkup(createElement(ColorResult, { job: result, contextsCurrent: false }));
  assert(html.includes("controls differ from this result"));
  assert(html.includes("Declarations for this result: unknown"));
});
