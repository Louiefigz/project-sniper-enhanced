import fs from "node:fs";
import path from "node:path";
import http from "node:http";
import { readStudioJson } from "./paths";
import { runStudioCommand, STUDIO_CLI } from "./process";
import { StudioError, type StudioRecord } from "./model";
import reviewPolicy from "./review-policy.json";

export function readStudioRecord(dir: string): StudioRecord | null {
  const row = readStudioJson(path.join(dir, "studio", ".studio-server.json"));
  if (!row) return null;
  if (!Number.isInteger(row.pid) || Number(row.pid) <= 0
      || !Number.isInteger(row.port) || Number(row.port) < 3990 || Number(row.port) > 3999
      || typeof row.startedAt !== "string" || !Number.isFinite(Date.parse(row.startedAt))) {
    throw new StudioError("Studio server record is invalid; no process was stopped");
  }
  return { pid: Number(row.pid), port: Number(row.port), startedAt: row.startedAt };
}

export function studioUrl(record: StudioRecord): string {
  return `http://127.0.0.1:${record.port}/#project/studio`;
}

/** Require the exact pinned preview command; arbitrary recorded PIDs are not authority. */
export async function ownsStudioProcess(dir: string, record: StudioRecord): Promise<boolean> {
  try {
    const line = (await runStudioCommand("ps", ["-o", "command=", "-p", String(record.pid)], 2_000)).trim();
    return line.includes(`${STUDIO_CLI} preview ${path.join(dir, "studio")} --port ${record.port}`)
      && /(?:^|\/)node(?:\s|$)/u.test(line);
  } catch { return false; }
}

export async function loopbackListener(record: StudioRecord,
  run = runStudioCommand): Promise<boolean> {
  try {
    const output = await run("lsof", ["-nP", "-a", "-p", String(record.pid),
      `-iTCP:${record.port}`, "-sTCP:LISTEN", "-Fn"], 2_000);
    const listeners = output.split("\n").filter((line) => line.startsWith("n"));
    return listeners.length > 0 && listeners.every((line) => line === `n127.0.0.1:${record.port}`
      || line === `n[::1]:${record.port}`);
  } catch { return false; }
}

/** Read a bounded identity response directly from loopback, without redirects. */
export function probeStudio(record: StudioRecord, get = http.get): Promise<Record<string, unknown> | null> {
  return new Promise((resolve) => {
    const request = get({ hostname: "127.0.0.1", port: record.port,
      path: "/__hyperframes_config", timeout: 750 }, (response) => {
      if (response.statusCode !== 200 || response.headers[reviewPolicy.header] !== reviewPolicy.identity) {
        response.resume(); resolve(null); return;
      }
      let text = "";
      response.on("data", (chunk) => {
        text += chunk.toString();
        if (text.length > 64_000) { request.destroy(); resolve(null); }
      });
      response.on("error", () => resolve(null));
      response.on("end", () => {
        try { resolve(JSON.parse(text)); } catch { resolve(null); }
      });
    });
    request.on("error", () => resolve(null));
    request.on("timeout", () => { request.destroy(); resolve(null); });
  });
}

/** A ready session proves process, listener scope and exact served project. */
export async function studioSessionReady(dir: string, record: StudioRecord): Promise<boolean> {
  if (!await ownsStudioProcess(dir, record) || !await loopbackListener(record)) return false;
  const identity = await probeStudio(record);
  return identity?.isHyperframes === true && identity.projectDir === path.join(dir, "studio");
}

export async function waitForStudio(dir: string, record: StudioRecord): Promise<void> {
  const deadline = Date.now() + 10_000;
  while (Date.now() < deadline) {
    if (await studioSessionReady(dir, record)) return;
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  throw new StudioError("Studio did not become ready on its assigned loopback port", 504, "STUDIO_TIMEOUT");
}

/** Only clean up a new process this request started; never stop a reused session. */
export async function cleanupStartedStudio(dir: string, previous: StudioRecord | null): Promise<void> {
  const record = readStudioRecord(dir);
  if (!record || record.pid === previous?.pid || !await ownsStudioProcess(dir, record)) return;
  try { process.kill(record.pid, "SIGTERM"); } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ESRCH") throw error;
  }
  const current = readStudioRecord(dir);
  if (current?.pid === record.pid && current.startedAt === record.startedAt) {
    fs.unlinkSync(path.join(dir, "studio", ".studio-server.json"));
  }
}
