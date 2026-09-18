import { brainModel, brainProvider, type BrainProvider } from "./ai-provider";
import { runClaudeJson, type ClaudeJsonSchema } from "./claude-cli";
import { runCodexJson } from "./codex-cli";

/**
 * Segmenter and Clipper ask the editor brain for one schema-bound JSON answer.
 * The provider selected in ai-provider.ts decides which pinned subscription CLI
 * answers; the prompt text is identical for both. Both run with no tools under
 * the OS media boundary. There is no Anthropic SDK client, no API-key route and
 * no fallback: if the selected CLI fails, the caller receives that failure.
 */
export type BrainJsonSchema = ClaudeJsonSchema;

export interface BrainJsonRequest {
  prompt: string;
  schema: BrainJsonSchema;
  timeoutMs: number;
  signal?: AbortSignal;
}

export interface BrainJsonResult<T> {
  value: T;
  provider: BrainProvider;
  model: string;
}

export interface BrainJsonRunners {
  codex: typeof runCodexJson;
  claude: typeof runClaudeJson;
}

const SUBSCRIPTION_RUNNERS: BrainJsonRunners = { codex: runCodexJson, claude: runClaudeJson };

export async function runBrainJson<T>(
  request: BrainJsonRequest,
  runners: BrainJsonRunners = SUBSCRIPTION_RUNNERS,
): Promise<BrainJsonResult<T>> {
  const provider = brainProvider();
  const model = brainModel(provider);
  const { prompt, schema, timeoutMs, signal } = request;
  const value = provider === "codex"
    ? await runners.codex<T>({ prompt, schema, timeoutMs, signal, tools: "none", jail: true })
    : await runners.claude<T>({ prompt, schema, timeoutMs, signal });
  return { value, provider, model };
}
