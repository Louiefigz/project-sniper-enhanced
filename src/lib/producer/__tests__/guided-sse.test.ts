import assert from "node:assert/strict";
import { test } from "node:test";
import { readEventStream } from "../sse";
import { buildCutAuthoringPrompt } from "@/app/api/producer/auto-edit/cut-authoring-prompt";
import type { AutoEditCtx } from "@/app/api/producer/auto-edit/stream";

function response(event: string): Response {
  return new Response(`: heartbeat\n\ndata: malformed\n\ndata: ${JSON.stringify({ event })}\n\n`);
}

test("guided callers explicitly allow pause, but output-only callers never mistake it for delivery", async () => {
  const events: string[] = [];
  await readEventStream(response("awaiting_cut_approval"), (event) => events.push(String(event.event)),
    undefined, ["outputs", "awaiting_cut_approval"]);
  assert.deepEqual(events, ["awaiting_cut_approval"]);
  await readEventStream(response("outputs"), () => {}, undefined, ["outputs", "awaiting_cut_approval"]);
  await assert.rejects(readEventStream(response("awaiting_cut_approval"), () => {}, undefined, "outputs"), /before confirming outputs/);
  await assert.rejects(readEventStream(response("heartbeat"), () => {}, undefined, ["outputs", "awaiting_cut_approval"]), /result is unknown/);
  await assert.rejects(readEventStream(response("outputs"), () => {}, undefined, []), /at least one/);
});

test("server errors propagate and cancel body rather than falsely finishing a guided request", async () => {
  let canceled = false;
  const body = new ReadableStream({ start(controller) {
    controller.enqueue(new TextEncoder().encode('data: {"event":"error","message":"Cut not qualified"}\n\n'));
  }, cancel() { canceled = true; } });
  await assert.rejects(readEventStream(new Response(body), (event) => {
    if (event.event === "error") throw new Error(String(event.message));
  }, undefined, ["outputs", "awaiting_cut_approval"]), /Cut not qualified/);
  assert.equal(canceled, true); assert.equal(body.locked, false);
});

test("disconnect interrupts a waiting stream read without claiming completion", async () => {
  const controller = new AbortController();
  let canceled = false;
  const body = new ReadableStream({ cancel() { canceled = true; } });
  const pending = readEventStream(new Response(body), () => assert.fail("unexpected event"), controller.signal,
    ["outputs", "awaiting_cut_approval"]);
  controller.abort();
  await pending;
  assert.equal(canceled, true); assert.equal(body.locked, false);
});

test("cut-first authoring discloses its real speed capability without weakening ordinary workflows", () => {
  const ctx: AutoEditCtx = { dir: "/private/tmp/prompt-only/producer", planPath: "/private/tmp/prompt-only/producer/edit_plan.json",
    manifestPath: "/private/tmp/prompt-only/source/asset_manifest.json", transcriptsDir: "/private/tmp/prompt-only/source",
    scope: "produced", deliveryPolicy: "mp4-only", intent: { mode: "longform", lanes: {} } };
  const ordinary = buildCutAuthoringPrompt(ctx, "codex");
  const guided = buildCutAuthoringPrompt({ ...ctx, workflowPolicy: "cut-first" }, "codex");
  assert.doesNotMatch(ordinary, /GUIDED PREVIEW CAPABILITY/);
  assert.match(guided, /supports only speed=1/);
  assert.match(guided, /unsupported_guided_retiming rather than silently discarding/);
  assert.match(guided, /Never invent ids or timestamps/);
  for (const prompt of [ordinary, guided]) {
    assert.match(prompt, /CUT_AUTHORING_BLOCKED source_timing_review_required/);
    assert.match(prompt, /Long word timestamps and low confidence do not prove silence/);
    assert.match(prompt, /never move the cut boundary or delete more words merely to make the gate pass/);
    assert.match(prompt, /Do not create timing-review decisions, mark a human as having listened/);
    assert.match(prompt, /does not waive duplicate, mid-word, meaning, or other integrity checks/);
    assert.doesNotMatch(prompt, /Revise only cutTrack\/cutDecisions\/target until it exits 0/);
    assert.match(prompt, /revise only cutTrack\/cutDecisions and rerun this gate; preserve the controller-provided target and lanes exactly/);
  }
});
