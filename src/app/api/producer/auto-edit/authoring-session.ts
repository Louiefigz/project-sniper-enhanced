import { randomUUID } from "node:crypto";

const CLAUDE_SESSION_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

/** Reuse only a UUID Claude Code can actually resume. */
export function retainedClaudeSessionId(value: unknown): string {
  return typeof value === "string" && CLAUDE_SESSION_ID.test(value)
    ? value : randomUUID();
}
