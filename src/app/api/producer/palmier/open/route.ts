import { spawn } from "child_process";
import { existsSync } from "fs";
import path from "path";
import { NextRequest, NextResponse } from "next/server";
import { palmierStatePath, readJsonObject } from "../_lib";
import { activateGeneratedTimeline } from "./activate";
import { currentPreflight } from "./current";
import { runPalmierOwnership } from "../ownership/runner";
import { producerRunActive } from "@/lib/server/producer-run-registry";

export const dynamic = "force-dynamic";

export interface Handoff {
  projectPath: string;
  timelineId: string;
  planHash: string;
  ownership: "sniper" | "palmier";
}

interface HandoffError {
  error: string;
  status: number;
}

/** Open the verified project and reveal its exact generated Sniper timeline. */
export async function POST(req: NextRequest) {
  if (process.platform !== "darwin") {
    return NextResponse.json({ error: "Palmier launching is only supported on macOS." }, { status: 400 });
  }
  const body = (await req.json().catch(() => null)) as { dir?: unknown } | null;
  const dir = typeof body?.dir === "string" ? body.dir.replace(/\/$/, "") : "";
  if (!dir || !path.isAbsolute(dir) || dir.split("/").includes("..")) {
    return NextResponse.json({ error: "dir must be an absolute Producer directory" }, { status: 400 });
  }
  const activeBlock = activePalmierHandoffBlock(dir);
  if (activeBlock) return NextResponse.json({ error: activeBlock }, { status: 409 });
  if (!existsSync(path.join(dir, "edit_plan.json")) || !existsSync(path.join(dir, "final.mp4"))) {
    return NextResponse.json({ error: "Project is not finished yet." }, { status: 409 });
  }

  const handoff = loadHandoff(dir);
  if ("error" in handoff) {
    return NextResponse.json({ error: handoff.error }, { status: handoff.status });
  }

  if (handoff.ownership === "sniper") {
    const stale = await currentGate(dir, handoff.planHash);
    if (stale) return stale;
    const ownership = await runPalmierOwnership(dir, "handoff");
    if (ownership.code !== 0) {
      const status = ownership.code === 75 ? 409 : 500;
      return NextResponse.json({
        error: ownership.verdict.error || "Could not hand control to Palmier.",
      }, { status });
    }
  }

  const result = await runOpen([handoff.projectPath]);
  if (result.code !== 0) {
    return NextResponse.json({ error: result.error || "Could not open Palmier Pro." }, { status: 500 });
  }
  let timeline: { id: string; name: string | null };
  try {
    timeline = await activateGeneratedTimeline(handoff.projectPath, handoff.timelineId);
  } catch (error) {
    const message = error instanceof Error ? error.message : "Could not select the generated timeline.";
    return NextResponse.json({ error: message }, { status: 502 });
  }
  return NextResponse.json({
    ok: true,
    openedProject: true,
    timelineId: timeline.id,
    timelineName: timeline.name,
    ownership: "palmier",
    message: `Opened the verified Palmier edit${timeline.name ? ` (${timeline.name})` : ""}; Palmier now owns this handoff.`,
  });
}

/** Ownership may not move while Sniper is still changing the managed project. */
export function activePalmierHandoffBlock(dir: string): string | null {
  return producerRunActive(dir)
    ? "Sniper is still working on this project. Stop and keep its checkpoint before taking control in Palmier."
    : null;
}

async function currentGate(dir: string, expectedHash: string): Promise<Response | null> {
  try {
    const current = await currentPreflight(dir);
    if (current.ok && current.planHash === expectedHash) return null;
    return NextResponse.json(
      { error: current.blocked || "Palmier handoff is behind the current edit. Sync again." },
      { status: 409 },
    );
  } catch (error) {
    const message = error instanceof Error ? error.message : "Could not verify the current plan.";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

export function loadHandoff(dir: string): Handoff | HandoffError {
  const state = readJsonObject(palmierStatePath(dir));
  const projectPath = typeof state?.projectPath === "string" && existsSync(state.projectPath)
    ? state.projectPath
    : null;
  const timelineId = typeof state?.latestTimelineId === "string" ? state.latestTimelineId : null;
  const planHash = typeof state?.lastPushPlanHash === "string" ? state.lastPushPlanHash : null;
  const ownership = state?.ownership === "palmier" ? "palmier" : "sniper";
  if (!projectPath || !timelineId || !planHash) {
    return { error: "No verified Palmier handoff exists for this project yet.", status: 409 };
  }
  const parity = asObject(state?.parity);
  const verification = asObject(state?.verification);
  const proofMatches = verification?.planHash === planHash
    && verification?.timelineId === timelineId;
  if (state?.schemaVersion !== 4 || state?.mirrorMode !== "visual-master"
      || parity?.mirrorReady !== true || verification?.ok !== true || !proofMatches) {
    return {
      error: "Palmier mirror proof is incomplete. Update the mirror before opening it.",
      status: 409,
    };
  }
  return { projectPath, timelineId, planHash, ownership };
}

function asObject(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function runOpen(args: string[]): Promise<{ code: number; error: string }> {
  return new Promise((resolve) => {
    const child = spawn("open", args);
    let error = "";
    child.stderr.on("data", (data) => (error += data.toString()));
    child.on("close", (code) => resolve({ code: code ?? 1, error: error.trim() }));
    child.on("error", (err) => resolve({ code: 1, error: err.message }));
  });
}
