import { palmierRpc } from "../_lib";

interface ToolContent {
  content?: { type?: string; text?: string }[];
  isError?: boolean;
}

/** Open the known project and make the verified generated timeline visible. */
export async function activateGeneratedTimeline(
  projectPath: string,
  timelineId: string,
): Promise<{ id: string; name: string | null }> {
  let lastError: unknown;
  for (let attempt = 0; attempt < 5; attempt += 1) {
    try {
      return await activateOnce(projectPath, timelineId);
    } catch (error) {
      lastError = error;
      await delay(250 * (attempt + 1));
    }
  }
  const message = lastError instanceof Error ? lastError.message : "Palmier did not become ready";
  throw new Error(`Could not activate the generated Palmier timeline: ${message}`);
}

async function activateOnce(
  projectPath: string,
  timelineId: string,
): Promise<{ id: string; name: string | null }> {
  const init = await palmierRpc(
    "initialize",
    {
      protocolVersion: "2025-06-18",
      capabilities: {},
      clientInfo: { name: "sniper-open-palmier", version: "1.0" },
    },
    null,
    1,
  );
  await palmierRpc("notifications/initialized", {}, init.sessionId, null);
  await callTool("open_project", { path: projectPath }, init.sessionId, 2);
  await callTool("set_active_timeline", { timelineId }, init.sessionId, 3);
  const timeline = await callTool("get_timeline", {}, init.sessionId, 4);
  if (timeline.id !== timelineId) {
    throw new Error(`Palmier activated timeline ${String(timeline.id)}, expected ${timelineId}`);
  }
  return {
    id: timelineId,
    name: typeof timeline.name === "string" ? timeline.name : null,
  };
}

async function callTool(
  name: string,
  args: Record<string, unknown>,
  sessionId: string | null,
  id: number,
): Promise<Record<string, unknown>> {
  const response = await palmierRpc(
    "tools/call",
    { name, arguments: args },
    sessionId,
    id,
    3000,
  );
  const result = (response.result ?? {}) as ToolContent;
  const text = (result.content ?? [])
    .filter((entry) => entry.type === "text")
    .map((entry) => entry.text ?? "")
    .join("");
  if (result.isError) throw new Error(`${name}: ${text || "tool error"}`);
  const parsed = JSON.parse(text || "{}") as unknown;
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error(`${name}: Palmier returned a non-object result`);
  }
  return parsed as Record<string, unknown>;
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
