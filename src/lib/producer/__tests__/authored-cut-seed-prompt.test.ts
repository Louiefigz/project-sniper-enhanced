/** Prompt-only checks; no editor, provider, command, or source media runs. */
import assert from "node:assert/strict";
import { test } from "node:test";
import { buildCutAuthoringPrompt, claudeCutAuthoringBashPatterns } from "@/app/api/producer/auto-edit/cut-authoring-prompt";
import { claudeArgs } from "@/app/api/producer/auto-edit/authoring";
import type { AutoEditCtx } from "@/app/api/producer/auto-edit/stream";

const context: AutoEditCtx = { dir: "/private/tmp/TEST-author-seed", planPath: "/private/tmp/TEST-author-seed/edit_plan.json",
  manifestPath: "/private/tmp/TEST-author-seed/asset_manifest.json", transcriptsDir: "/private/tmp/TEST-author-seed",
  scope: "produced", workflowPolicy: "cut-first", deliveryPolicy: "mp4-only",
  intent: { mode: "longform", lanes: {}, brief: "Keep the real lesson; defer my graphics. Do not invent silence." } };
const authored: AutoEditCtx = { ...context, authoredCut: { schemaVersion: 1, policy: "source-brief-cut",
  requestHash: "a".repeat(64), initialPlanSha256: "b".repeat(64), transcriptDigest: "c".repeat(64),
  preparationStartedAt: "2026-09-07T00:00:00.000Z" } };

test("explicit authored seed preserves version and complete target while allowing only cut prediction changes", () => {
  for (const provider of ["legacy", "codex"] as const) {
    const prompt = buildCutAuthoringPrompt(authored, provider);
    assert.match(prompt, /Before running a command or editing, read the existing .*edit_plan.json/);
    assert.match(prompt, /Preserve or increment its existing planVersion; never reset it to the example's 1/);
    assert.match(prompt, /including canvas width\/height, numeric fps, mode\/scope\/lanes, platforms, treatment, music and other intent settings/);
    assert.match(prompt, /Only recompute target.durationTargetS from the actual kept cut durations/);
    assert.match(prompt, /do not rebuild target from the abbreviated writable shape or target step/);
    assert.ok(prompt.indexOf("AUTHORED CUT SEED:") < prompt.indexOf("1. Run"));
    assert.match(prompt, /SOURCE TIMING REVIEW WALL:/); assert.match(prompt, /CUT_AUTHORING_BLOCKED/);
  }
});

test("seed instruction changes neither untrusted brief bytes, pinned commands, nor provider permissions", () => {
  const before = structuredClone(authored);
  for (const provider of ["legacy", "codex"] as const) {
    const prompt = buildCutAuthoringPrompt(authored, provider), original = buildCutAuthoringPrompt(context, provider);
    assert.doesNotMatch(original, /AUTHORED CUT SEED:/);
    const stripped = prompt.split("\n").filter((line) => !line.startsWith("AUTHORED CUT SEED:")
      && !line.startsWith("Preserve or increment its existing planVersion;")).join("\n");
    assert.equal(stripped, original);
    assert.ok(prompt.includes(JSON.stringify(context.intent!.brief)));
  }
  assert.deepEqual(claudeCutAuthoringBashPatterns(authored), claudeCutAuthoringBashPatterns(context));
  const actualArgs = claudeArgs(authored, "cut"), priorArgs = claudeArgs(context, "cut");
  actualArgs[actualArgs.indexOf("-p") + 1] = "<PROMPT>"; priorArgs[priorArgs.indexOf("-p") + 1] = "<PROMPT>";
  assert.deepEqual(actualArgs, priorArgs); assert.deepEqual(authored, before);
});
