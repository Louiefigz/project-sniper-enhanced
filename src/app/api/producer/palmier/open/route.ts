import { spawn } from "child_process";
import { existsSync } from "fs";
import path from "path";
import { NextRequest, NextResponse } from "next/server";
import { activePalmierHandoffBlock, loadHandoff } from "../_lib";
import { activateGeneratedTimeline } from "./activate";
import { currentPreflight } from "./current";
import { runPalmierOwnership } from "../ownership/runner";
import { canonicalPalmierDir, localPalmierRejection } from "../request";
import {
  guardProjectMutation,
  mutationProjectRoot,
} from "../../../_lib/project-mutation";

export const dynamic = "force-dynamic";

/** Open the verified project and reveal its exact generated Sniper timeline. */
export async function POST(req: NextRequest) {
  if (process.platform !== "darwin") {
    return NextResponse.json({ error: "Palmier launching is only supported on macOS." }, { status: 400 });
  }
  const rejection = localPalmierRejection(req);
  if (rejection) {
    return NextResponse.json({ error: rejection.error }, { status: rejection.status });
  }
  const body = (await req.json().catch(() => null)) as { dir?: unknown } | null;
  let dir: string;
  try {
    dir = canonicalPalmierDir(body?.dir);
  } catch (error) {
    return NextResponse.json({ error: (error as Error).message }, { status: 400 });
  }
  const guarded = guardProjectMutation({
    projectRoot: mutationProjectRoot(dir),
    producerDir: dir,
    operation: "opening and handing off a Palmier revision",
  });
  if (guarded.response) return guarded.response;
  try {
    return await openPalmierHandoff(dir);
  } finally {
    guarded.lease.release();
  }
}

async function openPalmierHandoff(dir: string): Promise<Response> {
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

function runOpen(args: string[]): Promise<{ code: number; error: string }> {
  return new Promise((resolve) => {
    const child = spawn("open", args);
    let error = "";
    child.stderr.on("data", (data) => (error += data.toString()));
    child.on("close", (code) => resolve({ code: code ?? 1, error: error.trim() }));
    child.on("error", (err) => resolve({ code: 1, error: err.message }));
  });
}
