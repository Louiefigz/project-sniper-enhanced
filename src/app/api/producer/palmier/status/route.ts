import { NextResponse } from "next/server";
import { palmierRpc } from "../_lib";

export const dynamic = "force-dynamic";

// Palmier destination probe (docs/PIPELINE.md): is the app open with a
// project? A dead socket / timeout = {up:false} — the chip shows offline,
// nothing errors. When up, the active project name rides along so the editor
// can show WHERE a push would land.
export async function GET() {
  try {
    const init = await palmierRpc(
      "initialize",
      {
        protocolVersion: "2025-06-18",
        capabilities: {},
        clientInfo: { name: "sniper-producer-ui", version: "1.0" },
      },
      null,
      1,
    );
    await palmierRpc("notifications/initialized", {}, init.sessionId, null);
    const projects = await palmierRpc(
      "tools/call",
      { name: "get_projects", arguments: {} },
      init.sessionId,
      2,
    );
    // Tool results carry JSON as text content — parse best-effort; a probe
    // that can't name the project is still "up".
    let project: string | null = null;
    let projectPath: string | null = null;
    let projectId: string | null = null;
    try {
      const content = (projects.result as { content?: { type: string; text?: string }[] })
        ?.content;
      const text = (content ?? [])
        .filter((c) => c.type === "text")
        .map((c) => c.text ?? "")
        .join("");
      const parsed = JSON.parse(text) as {
        active?: { name?: string; path?: string };
        projects?: { id?: string; path?: string; isActive?: boolean }[];
      };
      project = parsed.active?.name ?? null;
      projectPath = parsed.active?.path ?? null;
      projectId = parsed.projects?.find((p) => p.isActive)?.id ?? null;
    } catch {
      project = null;
    }
    return NextResponse.json({ up: true, project, projectPath, projectId });
  } catch {
    return NextResponse.json({ up: false, project: null, projectPath: null, projectId: null });
  }
}
