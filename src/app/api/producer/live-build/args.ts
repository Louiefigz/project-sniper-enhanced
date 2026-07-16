import { claudeModelArgs } from "../../_lib/ai-provider";
import { PALMIER_MCP_URL } from "../palmier/_lib";

const PALMIER_TOOLS = [
  "get_timeline",
  "get_transcript",
  "inspect_media",
  "import_media",
  "add_clips",
  "insert_clips",
  "split_clips",
  "move_clips",
  "remove_clips",
  "ripple_delete_ranges",
  "set_clip_properties",
  "set_keyframes",
  "add_texts",
  "update_text",
  "add_captions",
  "apply_color",
  "apply_effect",
  "apply_layout",
  "manage_tracks",
  "sync_clips",
  "remove_silence",
  "remove_words",
  "denoise_audio",
  "detect_beats",
  "inspect_timeline",
] as const;

export const LIVE_BUILD_ALLOWED_TOOLS = [
  "Skill(producer)",
  "Read",
  "Glob",
  "Grep",
  ...PALMIER_TOOLS.map((tool) => `mcp__palmier-pro__${tool}`),
] as const;

export function liveBuildMcpConfig(): string {
  return JSON.stringify({
    mcpServers: {
      "palmier-pro": { type: "http", url: PALMIER_MCP_URL },
    },
  });
}

export interface LiveBuildArgsInput {
  prompt: string;
  sessionId: string;
  resume: boolean;
  readDirs: string[];
}

/** Exact skill-enabled, strict-MCP invocation proved by the disposable smoke. */
export function buildLiveBuildArgs(input: LiveBuildArgsInput): string[] {
  const session = input.resume
    ? ["--resume", input.sessionId]
    : ["--session-id", input.sessionId];
  return [
    "-p", input.prompt,
    ...session,
    ...claudeModelArgs(),
    "--effort", "low",
    "--output-format", "stream-json",
    "--verbose",
    "--mcp-config", liveBuildMcpConfig(),
    "--strict-mcp-config",
    "--permission-mode", "dontAsk",
    "--allowedTools", LIVE_BUILD_ALLOWED_TOOLS.join(","),
    ...[...new Set(input.readDirs)].flatMap((dir) => ["--add-dir", dir]),
  ];
}
