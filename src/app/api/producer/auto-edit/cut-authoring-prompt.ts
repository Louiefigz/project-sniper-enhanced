import path from "node:path";
import { type BrainProvider } from "../../_lib/ai-provider";
import { doctrinePromptPath, doctrinePromptRoot } from "@/lib/server/auto-edit-doctrine";
import { pipelineAuthorityPath } from "@/lib/server/auto-edit-pipeline-authority";
import type { AutoEditCtx } from "./stream";
import {
  producerCommand,
  REPO_ROOT,
  targetStep,
  verbatimBashCommand,
} from "./authoring-prompt";

interface CutCommands {
  speech: string;
  approval: string;
}

function commands(ctx: AutoEditCtx): CutCommands {
  return {
    speech: producerCommand(ctx, "edit/speech_cleanup.py", [
      ctx.manifestPath, "--out", path.join(ctx.dir, "speech_cleanup.json"),
    ]),
    approval: producerCommand(ctx, "transcript_cut_contract.py", [
      ctx.planPath, ctx.transcriptsDir, ctx.manifestPath, "--previsual",
    ]),
  };
}

export function claudeCutAuthoringBashPatterns(ctx: AutoEditCtx): string[] {
  const value = commands(ctx);
  return [value.speech, value.approval];
}

function providerRule(ctx: AutoEditCtx, provider: BrainProvider): string {
  const root = pipelineAuthorityPath(ctx, "scripts/producer");
  return provider === "codex"
    ? `The repository at ${REPO_ROOT} is READ-ONLY. Use only the pinned commands below from ${root}; write only ${ctx.planPath} and scratch JSON inside ${ctx.dir}.`
    : `Use only the pinned commands below from ${root}; write only ${ctx.planPath} and scratch JSON inside ${ctx.dir}.`;
}

export function buildCutAuthoringPrompt(
  ctx: AutoEditCtx,
  provider: BrainProvider = "legacy",
): string {
  const value = commands(ctx);
  const skill = doctrinePromptPath(ctx, ".agents/skills/producer/SKILL.md");
  const ledger = doctrinePromptPath(
    ctx, "scripts/producer/docs/findings/FAILURE_LEDGER.md",
  );
  return [
    `You are the CUT EDITOR for the first controller-owned authoring stage. Do not plan visuals or render.`,
    provider === "legacy"
      ? `Before any other action, invoke the producer skill for this retained Claude Code session.`
      : `Apply the complete pinned Producer doctrine named below.`,
    `Write ${ctx.planPath} from ${ctx.manifestPath} and its word-level transcripts.`,
    providerRule(ctx, provider),
    `The only populated top-level fields permitted in this stage are planVersion, target, cutTrack, and cutDecisions. Keep every downstream field absent or empty, including graphics, captions, motion, transitions, b-roll, chapters, baseline look/color, effects, music, audio, and reframe decisions.`,
    `Do not inspect application source, schemas, tests, or renderer code to discover the plan shape. This is the complete writable shape: {"planVersion":1,"target":{"mode":"longform|shortform","scope":"clean|produced","excerpt":true when controller-specified,"lanes":{...},"durationTargetS":number},"cutTrack":[{"sourceId":"manifest id","start":number,"end":number,"speed":1,"rationale":"at least 12 characters"}],"cutDecisions":{"schemaVersion":1,"removals":[{"sourceId":"manifest id","start":number,"end":number,"kind":"retake|false-start|filler|pause|other","rationale":"specific editorial reason","evidence":{"beforeWord":"exact transcript word","afterWord":"exact transcript word","removedText":"exact removed transcript text"}}]}}. Preserve the controller-provided target and lanes exactly.`,
    `Never invent ids or timestamps. Every boundary must be transcript-safe and every removal evidence-backed.`,
    `For each VERBATIM BASH COMMAND, copy the command byte-for-byte in one Bash call, including its quoting; never prepend cd, combine commands, or rewrite paths. This is a noninteractive least-privilege process. If an exact command is denied, do not retry it, inspect permission/settings files, test the interpreter, or search for another spelling: print exactly CUT_AUTHORING_BLOCKED permission_allowlist_mismatch and stop.`,
    `Pinned doctrine root: ${doctrinePromptRoot(ctx)}.`,
    `Read ${skill}, the Brain lessons in ${ledger}, ${ctx.manifestPath}, and every manifest transcript before editing.`,
    `1. Run ${verbatimBashCommand(value.speech)} and use its cutTrack as the deterministic starting point. Then read the kept words in order and actively remove false restarts, adjacent repeated words or phrases, disposable fillers, and an incomplete opening or ending. Multiple transcript-safe cuts are correct when one long contiguous segment would preserve a defect. Preserve meaning and natural cadence; do not overcut intentional emphasis.`,
    targetStep(ctx, 2),
    `3. Add a >=12-character rationale to every kept cut. Add cutDecisions {"schemaVersion":1,"removals":[...]} with one exact sourceId/start/end entry per inter-cut gap. Every removal needs kind, rationale, and evidence {beforeWord,afterWord,removedText}.`,
    `4. Read the assembled kept transcript once more as a viewer: it must begin with a complete hook, progress without a duplicated restart, and end on a complete thought. Run ${verbatimBashCommand(value.approval)}. Revise only cutTrack/cutDecisions/target until it exits 0. Never add a visual or retention lane. An independent controller critic will review this cut after the deterministic command passes.`,
    `When it passes, print exactly: CUT_AUTHORED ok segments=<cutTrack length> removals=<removals length>`,
  ].join("\n");
}
