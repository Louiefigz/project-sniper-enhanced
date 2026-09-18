import { createHash, randomUUID } from "node:crypto";
import { readFileSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";
import {
  brainProvider,
  claudeModelArgs,
  type BrainProvider,
} from "../../_lib/ai-provider";
import { runCodexJson } from "../../_lib/codex-cli";
import {
  type BrainProcessResult,
  type LegacyBrainInvocation,
} from "../auto-edit/brain-review-runner";
import {
  parseProducerReview,
  validateProducerReview,
  type ProducerReview,
} from "../auto-edit/review-contract";
import {
  buildPalmierNativePlannerPrompt,
  palmierAuthorityPath,
  palmierNativeReadDirs,
  type PalmierNativePromptInput,
} from "./palmier-native-prompt";
import { doctrinePromptLines } from "./doctrine";
import {
  runPalmierNativeGate,
  writePalmierNativeGateEnvelope,
} from "./palmier-native-gate";
import {
  assertAuthorityUnchanged,
  validateExecuteVerdict,
  validatePalmierNativeAuthority,
  validatePalmierNativeDraft,
  validateReconcileVerdict,
  type PalmierNativeAuthority,
  type PalmierNativeDraft,
  type PalmierNativeResult,
} from "./palmier-native-contract";
import {
  bindPalmierNativeQcAuthority,
  capturePalmierNativeQcAuthority,
  finalizePalmierNativeQcAuthority,
  type PalmierNativePlan,
} from "./palmier-native-authority";
import { runLegacyNative, runNativeCli } from "./palmier-native-process";
import { assertCandidateSlotAvailable } from "@/lib/server/palmier-candidate-qc";
import { palmierNativeCapabilityFailure,
  type PalmierNativeCapabilityFailure } from "./palmier-native-capabilities";

const MODEL_TIMEOUT_MS = 20 * 60 * 1000;
type CodexJsonRunner = (options: Parameters<typeof runCodexJson>[0]) => Promise<unknown>;
type LegacyRunner = (
  invocation: LegacyBrainInvocation,
  signal?: AbortSignal,
) => Promise<BrainProcessResult>;

export interface NativeRunnerDependencies {
  provider?: () => BrainProvider;
  codex?: CodexJsonRunner;
  legacy?: LegacyRunner;
  cli?: (args: string[], signal?: AbortSignal) => Promise<Record<string, unknown>>;
  gate?: typeof runPalmierNativeGate;
  critic?: (
    input: PalmierNativePromptInput,
    draft: PalmierNativeDraft,
    signal?: AbortSignal,
  ) => Promise<ProducerReview>;
  captureAuthority?: typeof capturePalmierNativeQcAuthority;
  finalizeAuthority?: typeof finalizePalmierNativeQcAuthority;
  bindAuthority?: typeof bindPalmierNativeQcAuthority;
  capability?: (input: PalmierNativePromptInput) => PalmierNativeCapabilityFailure | null;
}

export interface PalmierNativeRunOptions {
  signal?: AbortSignal;
  onEvent?: (event: Record<string, unknown>) => void;
  planReviewsRequired?: number;
  keepCandidateActive?: boolean;
}

type NativeCliRunner = (
  args: string[],
  signal?: AbortSignal,
  onEvent?: (event: Record<string, unknown>) => void,
) => Promise<Record<string, unknown>>;
function requestHash(request: string): string {
  return createHash("sha256").update(request).digest("hex");
}

function assertActive(signal?: AbortSignal): void {
  if (signal?.aborted) throw new Error("Palmier native edit was cancelled");
}

function emitProgress(
  options: PalmierNativeRunOptions,
  status: string,
  fields: Record<string, unknown> = {},
): void {
  options.onEvent?.({ event: "palmier_native_progress", status, ...fields });
}

function reviewCount(options: PalmierNativeRunOptions): number {
  const requested = options.planReviewsRequired ?? 1;
  if (!Number.isInteger(requested) || requested < 1 || requested > 4) {
    throw new Error("Palmier native plan reviews must be an integer from 1 to 4");
  }
  return requested;
}

function claudePlannerArgs(prompt: string, input: PalmierNativePromptInput): string[] {
  return [
    "-p", prompt, ...claudeModelArgs(), "--output-format", "stream-json", "--verbose",
    "--permission-mode", "acceptEdits", "--allowedTools", "Read,Glob,Grep",
    ...palmierNativeReadDirs(input).flatMap((dir) => ["--add-dir", dir]),
  ];
}

async function draftPlan(
  input: PalmierNativePromptInput,
  provider: BrainProvider,
  deps: NativeRunnerDependencies,
  signal?: AbortSignal,
): Promise<PalmierNativeDraft> {
  const prompt = buildPalmierNativePlannerPrompt(input);
  let value: unknown;
  if (provider === "codex") {
    const runner = deps.codex ?? runCodexJson;
    value = await runner({ prompt, timeoutMs: MODEL_TIMEOUT_MS, cwd: input.dir,
      schema: "palmier-mutation-plan", addDirs: palmierNativeReadDirs(input), signal });
  } else {
    const result = await (deps.legacy ?? runLegacyNative)({
      args: claudePlannerArgs(prompt, input), cwd: input.dir, timeoutMs: MODEL_TIMEOUT_MS,
    }, signal);
    value = JSON.parse(result.message) as unknown;
  }
  return validatePalmierNativeDraft(value, input.scope);
}

function criticPrompt(input: PalmierNativePromptInput, draft: PalmierNativeDraft): string {
  const doctrine = input.doctrineFiles?.map((file) => `- ${file}`)
    ?? doctrinePromptLines(input.scope);
  return [
    "You are a fresh read-only critic of a proposed Palmier-native surgical edit.",
    `Read ${palmierAuthorityPath(input.dir)} and these doctrine files completely:`,
    ...doctrine,
    `Operator request JSON: ${JSON.stringify({ request: input.request })}`,
    `Controller lanes: ${input.scope.lanes.join(", ")}`,
    `Proposed native operations JSON: ${JSON.stringify(draft)}`,
    "Judge only the Palmier-native vocabulary actually proposed. Do not imply that edit_plan gates ran or that plain text/keyframes implement a studied template or true transition.",
    "Reject any operation whose reason or requested result overstates that native capability.",
    "Reject invented ids/frames, adjacent-lane churn, destructive overwrite risk, weak reasons, or an edit that does not satisfy the request.",
    "Return exactly the producer-review JSON schema with stage='plan'. A pass has zero materialIssues.",
  ].join("\n");
}

async function reviewDraft(
  input: PalmierNativePromptInput,
  draft: PalmierNativeDraft,
  provider: BrainProvider,
  deps: NativeRunnerDependencies,
  signal?: AbortSignal,
): Promise<ProducerReview> {
  const prompt = criticPrompt(input, draft);
  if (provider === "codex") {
    const runner = deps.codex ?? runCodexJson;
    const review = await runner({ prompt, timeoutMs: MODEL_TIMEOUT_MS, cwd: input.dir,
      schema: "producer-review", addDirs: palmierNativeReadDirs(input), signal });
    return parseProducerReview(JSON.stringify(review), "plan");
  }
  const result = await (deps.legacy ?? runLegacyNative)({
    args: claudePlannerArgs(prompt, input), cwd: input.dir, timeoutMs: MODEL_TIMEOUT_MS,
  }, signal);
  return parseProducerReview(result.message, "plan");
}

async function reviewPlan(
  input: PalmierNativePromptInput,
  draft: PalmierNativeDraft,
  provider: BrainProvider,
  deps: NativeRunnerDependencies,
  options: PalmierNativeRunOptions,
): Promise<void> {
  const required = reviewCount(options);
  for (let round = 1; round <= required; round += 1) {
    assertActive(options.signal);
    emitProgress(options, "plan_review_started", { round, required });
    const review = deps.critic
      ? validateProducerReview(
        await deps.critic(input, draft, options.signal), "plan",
      )
      : await reviewDraft(input, draft, provider, deps, options.signal);
    if (review.verdict !== "pass" || review.materialIssues.length) {
      throw new Error(`Palmier native critic ${round}/${required} rejected the edit: ${review.summary}`);
    }
    emitProgress(options, "plan_review_passed", { round, required });
  }
}

export async function runPalmierNativeEdit(
  input: PalmierNativePromptInput,
  dependencies: NativeRunnerDependencies = {},
  options: PalmierNativeRunOptions = {},
): Promise<PalmierNativeResult> {
  const capability = (dependencies.capability ?? palmierNativeCapabilityFailure)(input);
  if (input.workflow !== "initial-auto-edit" && capability) {
    throw new Error(`${capability.code}: ${capability.message}`);
  }
  const cli = dependencies.cli ?? runNativeCli;
  const reconciled = await cli([input.dir, "--reconcile"], options.signal);
  assertActive(options.signal);
  const authority = readAuthority(input.dir);
  validateReconcileVerdict(reconciled, authority);
  emitProgress(options, "baseline_reconciled", {
    timelineId: authority.timelineId,
    message: "Palmier's visible working head is the verified AI baseline.",
  });
  assertCandidateSlotAvailable(input.dir);
  const hash = requestHash(input.request);
  const capture = (dependencies.captureAuthority ?? capturePalmierNativeQcAuthority)(
    input, authority, hash,
  );
  const governedInput: PalmierNativePromptInput = {
    ...input,
    doctrineFiles: Object.values(capture.ctx.doctrine!.files),
  };
  const provider = (dependencies.provider ?? brainProvider)();
  emitProgress(options, "planning", {
    message: input.workflow === "initial-auto-edit"
      ? "Planning the first native edit from the visible Palmier source timeline."
      : "Planning the requested native change from Palmier's current working head.",
  });
  const draft = await draftPlan(governedInput, provider, dependencies, options.signal);
  emitProgress(options, "plan_authored", { operationCount: draft.operations.length });
  assertActive(options.signal);
  const plan: PalmierNativePlan = { ...draft, requestHash: hash, parent: {
    projectId: authority.projectId, timelineId: authority.timelineId,
    fingerprint: authority.fingerprint,
  } };
  const planPath = path.join(input.dir, `.palmier-native-plan.${randomUUID()}.json`);
  const gatePath = writePalmierNativeGateEnvelope({
    dir: input.dir, request: input.request, expectedLanes: input.scope.lanes,
  });
  try {
    assertActive(options.signal);
    writeFileSync(planPath, `${JSON.stringify(plan, null, 2)}\n`, { flag: "wx", mode: 0o600 });
    await (dependencies.gate ?? runPalmierNativeGate)({
      dir: input.dir, planPath, request: input.request, expectedLanes: input.scope.lanes,
      envelopePath: gatePath,
      cliPath: path.join(capture.ctx.pipeline!.snapshotRoot,
        "scripts", "producer", "palmier", "native_gate_cli.py"),
    }, options.signal);
    assertActive(options.signal);
    emitProgress(options, "deterministic_gate_passed", {
      operationCount: draft.operations.length,
    });
    await reviewPlan(governedInput, draft, provider, dependencies, options);
    const qcAuthority = (dependencies.finalizeAuthority ?? finalizePalmierNativeQcAuthority)(
      capture, input, authority, plan,
    );
    const executeCli: NativeCliRunner = dependencies.cli
      ?? ((args, signal, onEvent) => runNativeCli(
        args, signal, path.join(qcAuthority.ctx.pipeline!.snapshotRoot,
          "scripts", "producer", "palmier", "native_delta_cli.py"), onEvent,
      ));
    const progressArgs = options.onEvent ? ["--progress"] : [];
    const visibilityArgs = options.keepCandidateActive
      ? ["--keep-candidate-active"] : [];
    const verdict = await executeCli(
      [input.dir, "--execute", planPath, "--gate-envelope", gatePath,
        "--name", input.workflow === "initial-auto-edit"
          ? "Sniper initial edit" : "Sniper AI candidate",
        ...progressArgs, ...visibilityArgs],
      options.signal, options.onEvent,
    );
    const result = validateExecuteVerdict(verdict, authority, hash, draft);
    assertAuthorityUnchanged(readAuthority(input.dir), authority);
    (dependencies.bindAuthority ?? bindPalmierNativeQcAuthority)(
      input.dir, result, authority, qcAuthority,
    );
    return result;
  } finally {
    rmSync(planPath, { force: true });
    rmSync(gatePath, { force: true });
  }
}

export { runLegacyNative } from "./palmier-native-process";

function readAuthority(dir: string): PalmierNativeAuthority {
  try {
    return validatePalmierNativeAuthority(
      JSON.parse(readFileSync(palmierAuthorityPath(dir), "utf8")) as unknown,
    );
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    throw new Error(`Could not read the reconciled Palmier working authority: ${detail}`);
  }
}
