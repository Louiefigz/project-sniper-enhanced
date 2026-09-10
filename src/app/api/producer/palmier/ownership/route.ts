import { realpathSync } from "node:fs";
import path from "node:path";
import { NextRequest, NextResponse } from "next/server";
import { findProjectRoot, workspaceRoot } from "../../../_lib/workspace";
import { localApiRejection } from "@/lib/server/local-request-policy";
import {
  runPalmierOwnership,
  type PalmierOwnershipAction,
} from "./runner";
import {
  guardProjectMutation,
  mutationProjectRoot,
} from "../../../_lib/project-mutation";

export const dynamic = "force-dynamic";

class OwnershipRequestError extends Error {}

function canonicalProducerDir(value: unknown): string {
  if (typeof value !== "string" || !path.isAbsolute(value)) {
    throw new OwnershipRequestError("dir must be an absolute Producer project path");
  }
  let dir: string;
  try { dir = realpathSync(value.replace(/\/$/, "")); } catch {
    throw new OwnershipRequestError(`dir not found: ${value}`);
  }
  const workspace = realpathSync(workspaceRoot());
  const relative = path.relative(workspace, dir);
  const root = findProjectRoot(dir);
  const outside = relative === "" || relative.startsWith("..") || path.isAbsolute(relative);
  if (outside || !root || dir !== path.join(realpathSync(root), "producer")) {
    throw new OwnershipRequestError(
      "Ownership may target only a canonical producer/ directory in the local workspace",
    );
  }
  return dir;
}

function ownershipAction(value: unknown): PalmierOwnershipAction {
  if (value !== "handoff" && value !== "reclaim") {
    throw new OwnershipRequestError("action must be handoff or reclaim");
  }
  return value;
}

export async function POST(req: NextRequest) {
  const rejection = localApiRejection({
    method: req.method,
    pathname: req.nextUrl.pathname,
    protocol: req.nextUrl.protocol,
    host: req.headers.get("host"),
    origin: req.headers.get("origin"),
    secFetchSite: req.headers.get("sec-fetch-site"),
    contentType: req.headers.get("content-type"),
  });
  if (rejection) return NextResponse.json({ error: rejection.error }, { status: rejection.status });
  try {
    const body = await req.json() as Record<string, unknown>;
    const dir = canonicalProducerDir(body.dir);
    const action = ownershipAction(body.action);
    const guarded = guardProjectMutation({
      projectRoot: mutationProjectRoot(dir),
      producerDir: dir,
      operation: `${action === "handoff" ? "handing off" : "reclaiming"} Palmier ownership`,
    });
    if (guarded.response) return guarded.response;
    try {
      const result = await runPalmierOwnership(dir, action);
      const status = result.code === 0 ? 200 : result.code === 75 ? 409 : 500;
      return NextResponse.json(result.verdict, { status });
    } finally {
      guarded.lease.release();
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    const status = error instanceof OwnershipRequestError ? 400 : 500;
    return NextResponse.json({ error: message }, { status });
  }
}
