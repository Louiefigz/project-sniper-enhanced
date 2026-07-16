import { spawn } from "child_process";
import { palmierRpc } from "../_lib";

/** Launch Palmier when needed, then wait for its loopback MCP endpoint. */
export async function ensurePalmierApp(): Promise<void> {
  if (await ready()) return;
  const opened = await openApplication("Palmier Pro") || await openApplication("Palmier");
  if (!opened) throw new Error("Palmier could not be launched on this Mac.");
  for (let attempt = 0; attempt < 20; attempt += 1) {
    await delay(500);
    if (await ready()) return;
  }
  throw new Error("Palmier opened, but its local editing service did not become ready.");
}

async function ready(): Promise<boolean> {
  try {
    await palmierRpc("initialize", {
      protocolVersion: "2025-06-18",
      capabilities: {},
      clientInfo: { name: "sniper-palmier-workspace", version: "1.0" },
    }, null, 1, 1000);
    return true;
  } catch {
    return false;
  }
}

function openApplication(name: string): Promise<boolean> {
  return new Promise((resolve) => {
    const child = spawn("open", ["-a", name]);
    child.on("close", (code) => resolve(code === 0));
    child.on("error", () => resolve(false));
  });
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
