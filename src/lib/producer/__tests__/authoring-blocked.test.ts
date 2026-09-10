import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";
import { PassThrough } from "node:stream";
import { test } from "node:test";
import type { ChildProcessWithoutNullStreams } from "node:child_process";
import { AUTHORING_OUTPUT_MAX_BYTES, authoringTextState, observeAuthoringEvent,
  observeAuthoringText } from "@/app/api/producer/auto-edit/authoring-stream-contract";
import { runAuthoring, type AuthoringResult } from "@/app/api/producer/auto-edit/authoring";
import { AUTHORING_TIMEOUT_MS, bindClaudeAuthoringProcess } from "@/app/api/producer/auto-edit/claude-authoring-process";
import { runAuthorStage, type AuthoringRuntime, type AuthoringStageDependencies } from "@/app/api/producer/auto-edit/authoring-stage";
import type { AutoEditCtx } from "@/app/api/producer/auto-edit/stream";
import { freshJob } from "@/lib/server/auto-edit-job-builders";

const MARKER = "CUT_AUTHORING_BLOCKED";
const REASON = "source_timing_review_required";

/** TEST ONLY paths and content; no real project, source, provider or approval. */
function context(dir = "/private/TEST-not-a-project"): AutoEditCtx {
  return { dir, scope: "light", workflowPolicy: "cut-first", intent: { mode: "short" },
    planPath: path.join(dir, "edit_plan.json"), manifestPath: path.join(dir, "asset_manifest.json"), transcriptsDir: dir };
}

/** Root assistant content envelope, not a tool result carrying the same text. */
function assistant(text: string): Record<string, unknown> {
  return { type: "assistant", message: { role: "assistant", content: [{ type: "text", text }] } };
}

test("recognized, unknown and missing editor-stop reasons are bounded and monotonic", () => {
  for (const reason of [REASON, "permission_allowlist_mismatch", "unsupported_guided_retiming", "unknown " + "é".repeat(400), ""]) {
    const state = authoringTextState();
    observeAuthoringText(state, `  ${MARKER} ${reason}\r\nAUTHORED ok segments=9 graphics=3`);
    assert.deepEqual(state.blocked, { marker: MARKER, reason: reason.slice(0, 256) || "missing_block_reason" });
    observeAuthoringText(state, "AUTHORED ok segments=100 graphics=200");
    assert.equal(state.authored, null);
  }
  const state = authoringTextState();
  observeAuthoringText(state, `The prompt mentions ${MARKER} ${REASON}, not a standalone outcome.`);
  assert.equal(state.blocked, null);
  observeAuthoringText(state, "AUTHORED ok segments=7 graphics=3");
  assert.deepEqual(state.authored, { segments: 7, graphics: 3 });
  for (const text of [MARKER, `${MARKER}   \t`, `\t${MARKER}\r\n`]) {
    const bare = authoringTextState();
    observeAuthoringEvent(bare, "legacy", assistant(text));
    assert.deepEqual(bare.blocked, { marker: MARKER, reason: "missing_block_reason" });
  }
});

test("only root completed editor text can stop authoring, never tools or raw token events", () => {
  const text = `${MARKER} ${REASON}`;
  const ignored = [{ type: "user", message: { content: [{ type: "tool_result", content: text }] } },
    { type: "item.completed", item: { type: "command_execution", aggregated_output: text, command: text } },
    { type: "stream_event", event: { type: "content_block_delta", delta: { type: "text_delta", text } } },
    { type: "system", result: text }, { type: "raw", line: text },
    { ...assistant(text), parent_tool_use_id: "nested-tool" },
    { type: "assistant", message: { role: "user", content: [{ type: "text", text }] } },
    { type: "assistant", message: { role: "assistant", content: [{ type: "tool_use", input: { text } }] } }];
  for (const value of ignored) {
    const state = authoringTextState();
    observeAuthoringEvent(state, "legacy", value); observeAuthoringEvent(state, "codex", value);
    assert.equal(state.blocked, null);
  }
  for (const provider of ["legacy", "codex"] as const) {
    const state = authoringTextState();
    observeAuthoringEvent(state, provider, { type: "result", result: text });
    assert.equal(state.blocked?.reason, REASON);
  }
});

test("actual Codex adapter retains final stops with exit0 and preserves existing invocation policy", async () => {
  const result = await runAuthoring(context(), () => {}, { provider: () => "codex", codex: async options => {
    assert.equal(options.maxOutputBytes, AUTHORING_OUTPUT_MAX_BYTES);
    assert.equal(options.timeoutMs, AUTHORING_TIMEOUT_MS);
    assert.equal(options.sandbox, "workspace-write");
    return { message: `${MARKER} ${REASON}`, stderr: "", ms: 1 };
  } }, { stage: "cut" });
  assert.equal(result.code, 0); assert.equal(result.timedOut, false);
  assert.deepEqual(result.blocked, { marker: MARKER, reason: REASON });
  assert.equal(result.authored, null);
});

test("actual Codex adapter latches streamed stops across abort or a later success message", async () => {
  for (const fails of [false, true]) {
    const result = await runAuthoring(context(), () => {}, { provider: () => "codex", codex: async options => {
      options.onEvent?.({ type: "item.completed", item: { type: "agent_message", text: `${MARKER} ${REASON}` } });
      assert.equal(options.signal?.aborted, true);
      if (fails) throw new Error("TEST ONLY timed out after prior explicit stop");
      return { message: "AUTHORED ok segments=1 graphics=0", stderr: "", ms: 1 };
    } }, { stage: "cut" });
    assert.deepEqual(result.blocked, { marker: MARKER, reason: REASON });
    assert.equal(result.authored, null);
  }
});

test("Codex raw transport failure cannot use prior success or timeout recovery", async () => {
  for (const fails of [false, true]) {
    const result = await runAuthoring(context(), () => {}, { provider: () => "codex", codex: async options => {
      options.onEvent?.({ type: "result", result: "AUTHORED ok segments=1 graphics=0" });
      options.onEvent?.({ type: "raw", line: '{"type":"assistant","text":"CUT_AUTHORING_BLOCKED' });
      assert.equal(options.signal?.aborted, true);
      if (fails) throw new Error("TEST ONLY timed out after malformed transport");
      return { message: "AUTHORED ok segments=1 graphics=0", stderr: "", ms: 1 };
    } }, { stage: "cut" });
    assert.match(result.protocolFailure ?? "", /structured-output protocol failed/);
    assert.equal(result.code, 1);
    assert.equal(result.blocked, null); assert.equal(result.authored, null);
  }
});

/** A PID-less in-memory child prevents any process-group or provider execution. */
function fakeProcess(): ChildProcessWithoutNullStreams {
  return Object.assign(new EventEmitter(), { stdin: new PassThrough(), stdout: new PassThrough(),
    stderr: new PassThrough(), pid: undefined }) as unknown as ChildProcessWithoutNullStreams;
}

/** Exercise the production post-spawn binder, then explicitly close the fake child. */
async function claudeRows(chunks: Buffer[]): Promise<AuthoringResult> {
  const proc = fakeProcess();
  const result = new Promise<AuthoringResult>(resolve => bindClaudeAuthoringProcess(proc,
    { ctx: context(), send: () => {}, stage: "cut", started: performance.now(), timeoutMs: 500 }, resolve));
  for (const chunk of chunks) proc.stdout.emit("data", chunk);
  proc.emit("close", 0);
  return result;
}

test("actual Claude binder preserves split UTF8 reason and unterminated complete message", async () => {
  const reason = "unknown_é_review", raw = Buffer.from(JSON.stringify(assistant(`${MARKER} ${reason}`)));
  const split = raw.indexOf(Buffer.from("é")) + 1;
  const result = await claudeRows([raw.subarray(0, split), raw.subarray(split)]);
  assert.equal(result.code, 0); assert.equal(result.timedOut, false);
  assert.deepEqual(result.blocked, { marker: MARKER, reason });
});

test("actual Claude binder never replaces an assistant stop with later successful result", async () => {
  const rows = [assistant(`${MARKER} ${REASON}`), { type: "result", result: "AUTHORED ok segments=2 graphics=3" }];
  const result = await claudeRows([Buffer.from(rows.map(value => JSON.stringify(value)).join("\n"))]);
  assert.equal(result.blocked?.reason, REASON); assert.equal(result.authored, null);
  const tool = { type: "user", message: { content: [{ type: "tool_result", content: `${MARKER} ${REASON}` }] } };
  const ordinary = await claudeRows([Buffer.from(JSON.stringify(tool) + "\n" + JSON.stringify(rows[1]))]);
  assert.equal(ordinary.blocked, null); assert.deepEqual(ordinary.authored, { segments: 2, graphics: 3 });
  const incomplete = await claudeRows([Buffer.from(JSON.stringify(assistant("AUTHORED ok segments=2 graphics=3")))]);
  assert.equal(incomplete.authored, null); // Historical counts come only from the final result.
});

test("Claude byte bound rejects a no-newline row before JSON allocation or timeout salvage", async () => {
  const result = await claudeRows([Buffer.alloc(AUTHORING_OUTPUT_MAX_BYTES + 1, 120)]);
  assert.equal(result.code, 1); assert.equal(result.timedOut, false);
  assert.match(result.errTail, /output budget/); assert.equal(result.authored, null);
  assert.match(result.protocolFailure ?? "", /output budget/);
});

test("Claude truncated final JSON and non-envelope JSON invalidate prior valid success", async () => {
  const good = JSON.stringify({ type: "result", result: "AUTHORED ok segments=1 graphics=0" });
  for (const tail of ['{"type":"assistant","text":"CUT_AUTHORING_BLOCKED', '{"tool":', "null", "[]", '"raw"', "{}"]) {
    const result = await claudeRows([Buffer.from(good + "\n" + tail)]);
    assert.equal(result.code, 1); assert.equal(result.blocked, null); assert.equal(result.authored, null);
    assert.match(result.protocolFailure ?? "", /structured-output protocol failed/);
  }
});

test("Claude invalid UTF8 cannot be replaced into successful editor transport", async () => {
  const prefix = Buffer.from('{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"');
  const suffix = Buffer.from('"}]}}\n' + JSON.stringify({ type: "result", result: "AUTHORED ok segments=1 graphics=0" }));
  for (const invalid of [Buffer.from([0xff]), Buffer.from([0xc0, 0xaf]), Buffer.from([0xed, 0xa0, 0x80])]) {
    const result = await claudeRows([prefix, invalid, suffix]);
    assert.equal(result.code, 1); assert.equal(result.authored, null); assert.equal(result.blocked, null);
    assert.match(result.protocolFailure ?? "", /structured-output protocol failed/);
  }
  const truncated = await claudeRows([prefix, Buffer.from([0xc2])]);
  assert.match(truncated.protocolFailure ?? "", /structured-output protocol failed/);
  const valid = await claudeRows([prefix, Buffer.from("� é 😀"), suffix]);
  assert.equal(valid.protocolFailure, null); assert.deepEqual(valid.authored, { segments: 1, graphics: 0 });
});

test("malformed known root editor envelopes cannot be overwritten by later valid results", async () => {
  const malformed = [{ type: "assistant", message: { role: "assistant", content: MARKER } },
    { type: "assistant", message: { role: "assistant", content: [{ type: "text", text: [MARKER] }] } },
    { type: "assistant", message: { content: [] } }, { type: "assistant", message: null },
    { type: "assistant", message: { role: "assistant", content: [null] } }];
  const good = { type: "result", result: "AUTHORED ok segments=1 graphics=0" };
  for (const row of malformed) {
    const result = await claudeRows([Buffer.from([good, row, good].map(value => JSON.stringify(value)).join("\n"))]);
    assert.equal(result.code, 1); assert.equal(result.authored, null); assert.equal(result.blocked, null);
    assert.match(result.protocolFailure ?? "", /structured-output protocol failed/);
  }
  const state = authoringTextState();
  observeAuthoringEvent(state, "codex", { type: "item.completed", item: { type: "agent_message", text: [MARKER] } });
  observeAuthoringEvent(state, "codex", good);
  assert.match(state.protocolFailure ?? "", /structured-output protocol failed/);
  const legitimate = [{ type: "system", subtype: "init", session_id: "TEST" },
    { type: "assistant", message: { role: "assistant", content: [{ type: "thinking", thinking: MARKER }, { type: "tool_use", input: { text: MARKER } }] } },
    { ...malformed[0], parent_tool_use_id: "TEST-subagent" },
    { type: "item.completed", item: { type: "command_execution", aggregated_output: MARKER } }];
  for (const value of legitimate) {
    const accepted = authoringTextState();
    observeAuthoringEvent(accepted, "legacy", value); observeAuthoringEvent(accepted, "codex", value);
    observeAuthoringEvent(accepted, "legacy", good);
    assert.equal(accepted.protocolFailure, null); assert.equal(accepted.blocked, null);
    assert.deepEqual(accepted.authored, { segments: 1, graphics: 0 });
  }
});

test("exact Codex output-budget exception is protocol failure before saved-plan normalization", async () => {
  const result = await runAuthoring(context(), () => {}, { provider: () => "codex", codex: async () => {
    throw new Error(`Codex exceeded its ${AUTHORING_OUTPUT_MAX_BYTES}-byte output budget`);
  } }, { stage: "cut" });
  assert.equal(result.code, 1); assert.equal(result.timedOut, false); assert.equal(result.blocked, null);
  assert.match(result.protocolFailure ?? "", /structured-output protocol failed/);
  await assertStageRefuses(result, /structured-output protocol failed/);
});

test("malformed terminal results and explicit provider errors cannot become later success", async () => {
  const good = { type: "result", result: "AUTHORED ok segments=1 graphics=0" };
  for (const row of [{ type: "result", result: [MARKER] }, { type: "result" },
    { ...good, is_error: "false" }, { ...good, is_error: true },
    { type: "result", is_error: true, subtype: "error_max_turns", errors: ["TEST provider error"] }]) {
    const result = await claudeRows([Buffer.from([good, row, good].map(value => JSON.stringify(value)).join("\n"))]);
    assert.equal(result.code, 1); assert.equal(result.authored, null); assert.equal(result.blocked, null);
    const providerError = row.is_error === true;
    assert.match(providerError ? result.providerFailure ?? "" : result.protocolFailure ?? "", /provider reported an error|protocol failed/);
    if (providerError) assert.equal(result.protocolFailure, null);
    await assertStageRefuses(result, /provider reported an error|protocol failed/);
  }
});

test("Codex adapter latches root error results while nested terminal metadata remains opaque", async () => {
  for (const nested of [false, true]) {
    const result = await runAuthoring(context(), () => {}, { provider: () => "codex", codex: async options => {
      options.onEvent?.({ type: "result", is_error: true, result: "AUTHORED ok segments=1 graphics=0",
        ...(nested ? { parent_tool_use_id: "TEST-subagent" } : {}) });
      assert.equal(options.signal?.aborted, !nested);
      return { message: "AUTHORED ok segments=1 graphics=0", stderr: "", ms: 1 };
    } }, { stage: "cut" });
    assert.equal(result.code, nested ? 0 : 1);
    if (!nested) await assertStageRefuses({ ...result, timedOut: true }, /provider reported an error/);
    if (nested) assert.deepEqual(result.authored, { segments: 1, graphics: 0 });
  }
});

/** All downstream callbacks are tripwires; this is not a mocked successful review. */
function stageDependencies(author: AuthoringStageDependencies["author"], calls: string[]): AuthoringStageDependencies {
  const forbidden = () => { throw new Error("TEST downstream work must not execute"); };
  return { exists: file => file.endsWith("edit_plan.json"), hashFile: forbidden, author, authority: forbidden,
    validateCut: forbidden, validateSavedCut: forbidden, reviewCut: forbidden, verifyReviewCut: forbidden,
    approveCut: forbidden, approveSavedCut: forbidden, verifyCut: forbidden, lockCut: forbidden,
    bindSession: () => { calls.push("bind-session"); return forbidden(); }, checkpoint: forbidden };
}

/** A fresh runtime over one private valid saved JSON; no disk job or consent receipt. */
function runtime(ctx: AutoEditCtx, events: Record<string, unknown>[]): AuthoringRuntime {
  const run = { job: freshJob({ ctx, token: "TEST-blocked", snapshots: 0 }, new Date().toISOString()) } as AuthoringRuntime;
  const advance: AuthoringRuntime["io"]["advance"] = update => (run.job = { ...run.job, ...update });
  run.io = { send: event => events.push(event), advance, invalidate: advance };
  return run;
}

/** Verify the real stage leaves saved bytes untouched and never invokes downstream work. */
async function assertStageRefuses(result: AuthoringResult, error: RegExp): Promise<void> {
  const dir = mkdtempSync("/private/tmp/sniper-authoring-blocked-"), ctx = context(dir), calls: string[] = [], events: Record<string, unknown>[] = [];
  const raw = '{"planVersion":1,"target":{"mode":"short"},"cutTrack":[],"graphicsTrack":[{"kind":"TEST-no-id"}]}';
  writeFileSync(ctx.planPath, raw);
  try {
    const run = runtime(ctx, events), deps = stageDependencies(async () => { calls.push("author"); return result; }, calls);
    await assert.rejects(runAuthorStage(run, deps), error);
    assert.deepEqual(calls, ["author"]); assert.equal(readFileSync(ctx.planPath, "utf8"), raw);
    assert.equal(run.job.checkpoint, "authoring");
    assert.equal(events.filter(row => row.event === "authoring_blocked").length, result.blocked ? 1 : 0);
    assert.equal(events.some(row => ["authoring_done", "authoring_deadline_recovered"].includes(String(row.event))), false);
  } finally { rmSync(dir, { recursive: true, force: true }); }
}

test("exit0 or timed-out explicit stop cannot normalize saved JSON, salvage, review or approve", async () => {
  for (const [timedOut, reason] of [[false, REASON], [true, REASON], [false, "missing_block_reason"]] as const) {
    await assertStageRefuses({ code: 0, timedOut, ms: 1, errTail: "", provider: "codex", authored: null,
      sessionEstablished: true, blocked: { marker: MARKER, reason } }, new RegExp(`${MARKER} ${reason}`));
  }
});

test("protocol failure blocks saved-plan normalization and timeout salvage independently of editor markers", async () => {
  for (const timedOut of [false, true]) {
    await assertStageRefuses({ code: 0, timedOut, ms: 1, errTail: "", provider: "legacy", authored: { segments: 1, graphics: 0 },
      sessionEstablished: true, protocolFailure: "Authoring structured-output protocol failed" }, /structured-output protocol failed/);
  }
});
