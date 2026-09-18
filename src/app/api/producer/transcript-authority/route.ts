import { NextRequest, NextResponse } from "next/server";
import fs from "node:fs";
import path from "node:path";
import { findProjectRoot } from "../../_lib/workspace";
import { guardProjectMutation } from "../../_lib/project-mutation";
import { pythonInterpreter, SCRIPTS_DIR } from "../../_lib/spawn-python";
import { localApiRejection } from "@/lib/server/local-request-policy";
import { spawn } from "node:child_process";

export const dynamic = "force-dynamic";
export const maxDuration = 600;

const RUNNER = path.join(
  SCRIPTS_DIR, "producer", "promote_transcript_authority.py",
);

interface RequestBody {
  dir?: unknown;
  candidateManifest?: unknown;
  sourceId?: unknown;
}

function localRejection(req: NextRequest): Response | null {
  const rejected = localApiRejection({
    method: req.method,
    pathname: req.nextUrl.pathname,
    protocol: req.nextUrl.protocol,
    host: req.headers.get("host"),
    origin: req.headers.get("origin"),
    secFetchSite: req.headers.get("sec-fetch-site"),
    contentType: req.headers.get("content-type"),
  });
  return rejected
    ? NextResponse.json({ error: rejected.error }, { status: rejected.status })
    : null;
}

function prepare(body: RequestBody): {
  root: string; producerDir: string; args: string[];
} {
  if (typeof body.dir !== "string" || !path.isAbsolute(body.dir)) {
    throw new Error("dir must be an absolute Project Sniper project path");
  }
  const root = findProjectRoot(body.dir.replace(/\/$/u, ""));
  if (!root) throw new Error(`no Project Sniper project found for ${body.dir}`);
  if (typeof body.candidateManifest !== "string"
      || !path.isAbsolute(body.candidateManifest)
      || !fs.existsSync(body.candidateManifest)) {
    throw new Error("candidateManifest must be an existing absolute path");
  }
  const sourceId = body.sourceId === undefined ? "raw-1" : body.sourceId;
  if (typeof sourceId !== "string" || !/^raw-[1-9][0-9]*$/u.test(sourceId)) {
    throw new Error("sourceId must use the raw-N vocabulary");
  }
  const target = path.join(root, "source", "asset_manifest.json");
  if (!fs.existsSync(target)) throw new Error("target asset manifest is missing");
  return {
    root,
    producerDir: path.join(root, "producer"),
    args: [RUNNER, target, body.candidateManifest, "--source-id", sourceId],
  };
}

function run(args: string[]): Promise<Record<string, unknown>> {
  return new Promise((resolve, reject) => {
    const child = spawn(pythonInterpreter(), args, { env: { ...process.env } });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (data: Buffer) => { stdout += data.toString(); });
    child.stderr.on("data", (data: Buffer) => { stderr += data.toString(); });
    child.on("error", reject);
    child.on("close", (code) => {
      const line = stdout.trim().split("\n").filter(Boolean).at(-1) || "";
      if (code !== 0) {
        reject(new Error(stderr.trim() || line || `promotion exited ${code}`));
        return;
      }
      try {
        resolve(JSON.parse(line) as Record<string, unknown>);
      } catch {
        reject(new Error("transcript promotion returned malformed evidence"));
      }
    });
  });
}

export async function POST(req: NextRequest): Promise<Response> {
  const rejected = localRejection(req);
  if (rejected) return rejected;
  let input;
  try {
    input = prepare(await req.json() as RequestBody);
  } catch (error) {
    return NextResponse.json(
      { error: (error as Error).message }, { status: 400 });
  }
  const guarded = guardProjectMutation({
    projectRoot: input.root,
    producerDir: input.producerDir,
    operation: "promoting an exact-media transcript authority",
  });
  if (guarded.response) return guarded.response;
  try {
    return NextResponse.json(await run(input.args));
  } catch (error) {
    return NextResponse.json(
      { error: (error as Error).message }, { status: 409 });
  } finally {
    guarded.lease.release();
  }
}
