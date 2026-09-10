export const AUTHORING_OUTPUT_MAX_BYTES = 16 * 1024 * 1024;

export interface AuthoringBlock {
  marker: "CUT_AUTHORING_BLOCKED";
  reason: string;
}

export interface AuthoringTextState {
  authored: { segments: number; graphics: number } | null;
  blocked: AuthoringBlock | null;
  protocolFailure: string | null;
  providerFailure: string | null;
}

/** Retain only the parsed outcome, never an unbounded conversation transcript. */
export function authoringTextState(): AuthoringTextState {
  return { authored: null, blocked: null, protocolFailure: null, providerFailure: null };
}

/** Retain a transport failure without interpreting any raw bytes as editor text. */
export function failAuthoringProtocol(state: AuthoringTextState): void {
  state.protocolFailure ??= "Authoring structured-output protocol failed";
  state.authored = null;
}

/** Match only the existing bounded runner's exact output-cap failure, not arbitrary errors. */
export function observeCodexAuthoringError(state: AuthoringTextState, message: string): void {
  if (message === `Codex exceeded its ${AUTHORING_OUTPUT_MAX_BYTES}-byte output budget`) failAuthoringProtocol(state);
}

/** A standalone editor stop is terminal, including unknown or missing reasons. */
export function observeAuthoringText(state: AuthoringTextState, text: string, finalResult = true): void {
  if (state.blocked || state.protocolFailure || state.providerFailure) return;
  const block = text.match(/^[ \t]*CUT_AUTHORING_BLOCKED(?:[ \t]+([^\r\n]*))?[ \t]*\r?$/m);
  if (block) {
    state.blocked = { marker: "CUT_AUTHORING_BLOCKED", reason: block[1]?.trim().slice(0, 256) || "missing_block_reason" };
    state.authored = null;
    return;
  }
  if (!finalResult) return;
  const authored = text.match(/AUTHORED ok segments=(\d+) graphics=(\d+)/);
  state.authored = authored ? { segments: Number(authored[1]), graphics: Number(authored[2]) } : null;
}

/** Accept an event envelope without coercing arrays or primitive values. */
function object(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;
}

/** Known root assistant envelopes must carry typed content; nontext blocks remain opaque. */
function observeClaudeMessage(state: AuthoringTextState, event: Record<string, unknown>): void {
  const message = object(event.message);
  if (message?.role !== "assistant" || !Array.isArray(message.content)) return failAuthoringProtocol(state);
  for (const value of message.content) {
    const row = object(value);
    if (!row || typeof row.type !== "string" || !row.type) return failAuthoringProtocol(state);
    if (row.type !== "text") continue;
    if (typeof row.text !== "string") return failAuthoringProtocol(state);
    observeAuthoringText(state, row.text, false);
  }
}

/** Completed noneditor items stay opaque; an editor item must have exact text type. */
function observeCodexItem(state: AuthoringTextState, event: Record<string, unknown>): void {
  const item = object(event.item);
  if (!item || typeof item.type !== "string" || !item.type) return failAuthoringProtocol(state);
  if (item.type !== "agent_message") return;
  if (typeof item.text !== "string") return failAuthoringProtocol(state);
  observeAuthoringText(state, item.text, false);
}

/** Error results are failures even without text; successful terminal results require text. */
function observeTerminalResult(state: AuthoringTextState, event: Record<string, unknown>): void {
  if (event.is_error !== undefined && typeof event.is_error !== "boolean") return failAuthoringProtocol(state);
  if (event.is_error === true) {
    state.providerFailure = "Authoring provider reported an error result";
    state.authored = null;
    return;
  }
  if (typeof event.result !== "string") return failAuthoringProtocol(state);
  observeAuthoringText(state, event.result);
}

/** Parse only root editor envelopes: never tool output, prompts, commands or deltas. */
export function observeAuthoringEvent(state: AuthoringTextState, provider: "codex" | "legacy", value: unknown): void {
  if (state.protocolFailure || state.providerFailure) return;
  const event = object(value);
  if (!event || typeof event.type !== "string" || !event.type || event.type === "raw") {
    return failAuthoringProtocol(state);
  }
  if (event.parent_tool_use_id != null || state.blocked) return;
  if (event.type === "result") return observeTerminalResult(state, event);
  if (provider === "codex" && event.type === "item.completed") observeCodexItem(state, event);
  if (provider === "legacy" && event.type === "assistant") observeClaudeMessage(state, event);
}

/** Return the first noninteractive Claude permission denial in one JSONL row. */
export function authoringPermissionDenial(line: string): string | null {
  try {
    const value = JSON.parse(line) as { message?: { content?: unknown[] } };
    const rows = Array.isArray(value.message?.content) ? value.message.content : [];
    for (const row of rows) {
      if (!row || typeof row !== "object") continue;
      const item = row as {
        type?: string; is_error?: boolean; content?: unknown;
      };
      if (item.type !== "tool_result" || item.is_error !== true
          || typeof item.content !== "string") continue;
      if (/requires approval|permission denied|not allowed by permission/i.test(item.content)) {
        return item.content;
      }
    }
  } catch { return null; }
  return null;
}

/** Extract the retained Claude conversation identity from one stream row. */
export function authoringStreamSessionId(line: string): string | null {
  try {
    const value = JSON.parse(line) as { session_id?: unknown };
    return typeof value.session_id === "string" ? value.session_id : null;
  } catch { return null; }
}
