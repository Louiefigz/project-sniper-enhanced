export type PalmierOpStatus = "applying" | "applied" | "failed";

export interface PalmierOpEvent {
  event: "palmier_op" | "palmier_op_result";
  operationId: string;
  tool?: string;
  lane?: string;
  summary?: string;
  status: PalmierOpStatus;
  input?: Record<string, unknown>;
  detail?: string;
  elapsedMs: number;
}

interface ContentBlock {
  type?: string;
  id?: string;
  name?: string;
  input?: unknown;
  tool_use_id?: string;
  is_error?: boolean;
  content?: unknown;
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown> : {};
}

function contentBlocks(value: Record<string, unknown>): ContentBlock[] {
  const message = record(value.message);
  const content = message.content;
  return Array.isArray(content)
    ? content.filter((item): item is ContentBlock => Boolean(item && typeof item === "object"))
    : [];
}

function shortTool(name: string): string | null {
  const prefix = "mcp__palmier-pro__";
  return name.startsWith(prefix) ? name.slice(prefix.length) : null;
}

function laneFor(tool: string, input: Record<string, unknown>): string {
  if (["add_texts", "update_text", "apply_layout"].includes(tool)) return "graphics";
  if (["add_captions"].includes(tool)) return "captions";
  if (["apply_color"].includes(tool)) return "color";
  if (["denoise_audio", "detect_beats"].includes(tool)) return "audio";
  if (tool === "set_keyframes") return input.property === "volume" ? "audio" : "motion";
  if (["apply_effect"].includes(tool)) return "transitions";
  if (["import_media", "search_media", "inspect_media"].includes(tool)) return "assets";
  if (["get_timeline", "get_transcript", "inspect_timeline", "get_projects"].includes(tool)) return "readback";
  if (["open_project", "set_active_timeline"].includes(tool)) return "authority";
  return "cuts";
}

function count(value: unknown): number | null {
  return Array.isArray(value) ? value.length : null;
}

function summaryFor(tool: string, input: Record<string, unknown>): string {
  const entries = count(input.entries);
  if (tool === "add_texts") return `Add ${entries ?? 1} editable text element${entries === 1 ? "" : "s"}`;
  if (tool === "add_clips" || tool === "insert_clips") return `Place ${entries ?? 1} editable clip${entries === 1 ? "" : "s"}`;
  if (tool === "import_media") return `Import ${String(record(input.source).path ?? input.name ?? "media")}`;
  if (tool === "set_keyframes") return `Set ${String(input.property ?? "property")} keyframes`;
  if (tool === "remove_words") return "Apply transcript-grounded word cuts";
  if (tool === "ripple_delete_ranges") return "Ripple-delete approved ranges";
  if (tool === "apply_color") return "Apply editable color treatment";
  if (tool === "add_captions") return "Add editable captions";
  if (tool === "get_timeline") return "Read back the active timeline";
  if (tool === "set_active_timeline") return "Bind the approved Palmier timeline";
  if (tool === "open_project") return "Open the linked Palmier project";
  return tool.replaceAll("_", " ");
}

function detail(value: unknown): string {
  if (typeof value === "string") return value.slice(0, 1_000);
  try { return JSON.stringify(value).slice(0, 1_000); } catch { return ""; }
}

/** Convert Claude stream-json MCP blocks into stable operation-level UI events. */
export function palmierOpEvents(
  value: Record<string, unknown>,
  elapsedMs: number,
): PalmierOpEvent[] {
  const events: PalmierOpEvent[] = [];
  for (const block of contentBlocks(value)) {
    if (block.type === "tool_use" && block.id && block.name) {
      const tool = shortTool(block.name);
      if (!tool) continue;
      const input = record(block.input);
      events.push({
        event: "palmier_op", operationId: block.id, tool,
        lane: laneFor(tool, input), summary: summaryFor(tool, input),
        status: "applying", input, elapsedMs,
      });
    }
    if (block.type === "tool_result" && block.tool_use_id) {
      events.push({
        event: "palmier_op_result", operationId: block.tool_use_id,
        status: block.is_error ? "failed" : "applied",
        detail: detail(block.content), elapsedMs,
      });
    }
  }
  return events;
}
