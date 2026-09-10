import { brainProvider, brainModel } from "@/app/api/_lib/ai-provider";
import { runCodex } from "@/app/api/_lib/codex-cli";
import { buildClaudeBrainArgs, runLegacyBrainProcess } from "@/app/api/producer/auto-edit/brain-review-process";
import { PRODUCER_CRITIC_REASONING, REVIEW_STAGE_DEADLINE_MS } from "@/app/api/producer/auto-edit/brain-review-settings";
import type { AutoEditCtx } from "@/app/api/producer/auto-edit/stream";
import { parseProposalReadinessReview, assertProposalReviewCoverage } from "@/lib/producer/contracts/proposal-readiness-v1";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { buildProposalReadinessPrompt, type ProposalReadinessPacket } from "./guided-proposal-review-packet";

export interface ProposalReadinessBrainInput {
  packet: ProposalReadinessPacket;
  criticIndex: number;
  ctx: AutoEditCtx;
  cwd: string;
  timeoutMs: number;
  schema: Record<string, unknown>;
}
interface Dependencies { codex: typeof runCodex; legacy: typeof runLegacyBrainProcess }
const OUTPUT_LIMIT = 1024 * 1024;

/** Fresh session for each critic; same configured model and existing independent critic effort. */
export async function runProposalReadinessCritic(input: ProposalReadinessBrainInput, dependencies: Partial<Dependencies> = {}) {
  if (!Number.isInteger(input.timeoutMs) || input.timeoutMs < 1 || input.timeoutMs > REVIEW_STAGE_DEADLINE_MS) throw new Error("Invalid readiness critic deadline");
  const prompt = buildProposalReadinessPrompt(input.packet, input.criticIndex), provider = brainProvider();
  const model = brainModel(provider), effort = provider === "codex" ? PRODUCER_CRITIC_REASONING : "xhigh";
  const result = provider === "codex" ? await (dependencies.codex ?? runCodex)({ prompt,
    sandbox: "read-only", tools: "none", cwd: input.cwd, timeoutMs: input.timeoutMs,
    schema: "producer-proposal-readiness", reasoning: PRODUCER_CRITIC_REASONING, maxOutputBytes: OUTPUT_LIMIT })
    : await (dependencies.legacy ?? runLegacyBrainProcess)({ args: buildClaudeBrainArgs(prompt, input.ctx, "isolated-review", [], input.schema),
      cwd: input.cwd, timeoutMs: input.timeoutMs, maxOutputBytes: OUTPUT_LIMIT });
  if (Buffer.byteLength(result.message, "utf8") > OUTPUT_LIMIT) throw new Error("Readiness output exceeds1 MiB");
  const review = parseProposalReadinessReview(JSON.parse(result.message));
  assertProposalReviewCoverage(review, input.packet.proposal, input.packet.evidence);
  return {
    criticIndex: input.criticIndex,
    packetHash: canonicalJsonSha256(input.packet),
    promptHash: canonicalJsonSha256(prompt),
    provider, model, effort, elapsedMs: result.ms, review,
  };
}
export type ProposalReadinessCriticResult = Awaited<ReturnType<typeof runProposalReadinessCritic>>;

/** Closed metadata and exact packet/prompt/coverage, also applied to injected test providers and stored receipts. */
export function assertProposalCriticResult(value: ProposalReadinessCriticResult, input: { packet: ProposalReadinessPacket; criticIndex: number }): void {
  const keys = ["criticIndex", "elapsedMs", "effort", "model", "packetHash", "promptHash", "provider", "review"];
  if (Object.keys(value).sort().join(",") !== keys.sort().join(",") || value.criticIndex !== input.criticIndex
      || value.packetHash !== canonicalJsonSha256(input.packet) || value.promptHash !== canonicalJsonSha256(buildProposalReadinessPrompt(input.packet, input.criticIndex))
      || !["codex", "legacy"].includes(value.provider) || typeof value.model !== "string" || !value.model || value.model.length > 160
      || value.effort !== (value.provider === "codex" ? PRODUCER_CRITIC_REASONING : "xhigh")
      || !Number.isFinite(value.elapsedMs) || value.elapsedMs < 0 || value.elapsedMs > REVIEW_STAGE_DEADLINE_MS) throw new Error("Readiness critic identity/prompt/metadata changed");
  const review = parseProposalReadinessReview(value.review);
  assertProposalReviewCoverage(review, input.packet.proposal, input.packet.evidence);
}
