import { spawn } from "child_process";
import { activateGeneratedTimeline } from "../open/activate";
import type { PalmierViewTarget } from "./target";

/** Reveal a known managed timeline without changing Sniper/Palmier ownership. */
export async function activatePalmierView(target: PalmierViewTarget) {
  const opened = await openPath(target.projectPath);
  if (opened.code !== 0) throw new Error(opened.error || "Could not open Palmier Pro.");
  return activateGeneratedTimeline(target.projectPath, target.timelineId);
}

function openPath(projectPath: string): Promise<{ code: number; error: string }> {
  return new Promise((resolve) => {
    const child = spawn("open", [projectPath]);
    let error = "";
    child.stderr.on("data", (data) => (error += data.toString()));
    child.on("close", (code) => resolve({ code: code ?? 1, error: error.trim() }));
    child.on("error", (reason) => resolve({ code: 1, error: reason.message }));
  });
}
