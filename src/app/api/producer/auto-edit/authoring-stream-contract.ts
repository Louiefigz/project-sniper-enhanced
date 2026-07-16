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
