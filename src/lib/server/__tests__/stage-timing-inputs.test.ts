import assert from "node:assert/strict";
import test from "node:test";
import type { RunTimingStage } from "@/lib/producer/run-timing";
import { timingInputSummary } from "@/lib/producer/run-timing";
import { accountTimingInputs } from "../stage-timing-inputs";
import { timingMetadata } from "../stage-timing-context";

const stage = (): RunTimingStage => ({ stage: "critic_plan_provider", calls: 2, inclusiveMs: 12_345, failed: 1, interrupted: 0 });

test("largest measured inputs stay separate from missing inputs and overlapping duration", () => {
  const value = stage(), first = { promptBytes: 500_000, evidenceImages: 4, provider: "codex", effort: "medium", deadlineMs: 60_000 };
  accountTimingInputs(value, first, first);
  accountTimingInputs(value, {}, {});
  assert.equal(value.inputs?.maxPromptBytes, 500_000); assert.equal(value.inputs?.promptCalls, 1);
  assert.equal(value.inclusiveMs, 12_345); assert.equal(value.failed, 1);
  assert.match(timingInputSummary(value).join(" "), /1\/2 calls measured/);
  const second = { ...first, promptBytes: 1000, deadlineMs: 120_000, provider: "legacy", effort: "xhigh" };
  accountTimingInputs(value, second, second);
  assert.deepEqual(value.inputs?.providers, ["codex", "legacy"]);
  assert.equal(value.inputs?.maxPromptBytes, 500_000);
  assert.deepEqual(value.inputs?.deadlineRangeMs, [60_000, 120_000]);
});

test("conflicting, private, malformed and non-integer input facts are not displayed", () => {
  for (const malformed of [-1, NaN, Infinity, 1.5, Number.MAX_SAFE_INTEGER + 1, "500000", null]) {
    const value = stage(), metadata = { promptBytes: malformed, provider: "PRIVATE-PROMPT-TEXT" };
    accountTimingInputs(value, metadata, metadata);
    assert.equal(value.inputs, undefined);
  }
  const value = stage();
  accountTimingInputs(value, { promptBytes: 123 }, { promptBytes: 456 });
  accountTimingInputs(value, [], []); accountTimingInputs(value, null, null);
  assert.equal(value.inputs, undefined); assert.equal(value.inclusiveMs, 12_345);
});

test("telemetry retains exact counts without persisting prompt or error text", () => {
  const extra = { promptBytes: 123, deadlineMs: 456, lens: "editorial", prompt: "PRIVATE", error: "PRIVATE" };
  assert.deepEqual(timingMetadata(extra), { lens: "editorial", promptBytes: 123, deadlineMs: 456 });
});
