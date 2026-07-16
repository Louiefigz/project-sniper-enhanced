import { NextRequest, NextResponse } from "next/server";
import { realpathSync } from "node:fs";
import path from "node:path";
import { findProjectRoot, workspaceRoot } from "../../../_lib/workspace";
import { localApiRejection } from "@/lib/server/local-request-policy";
import {
  AutoEditStopConflictError,
  AutoEditStopSignalError,
  stopAutoEdit,
} from "@/lib/server/auto-edit-stop";

export const dynamic = "force-dynamic";

class StopRequestError extends Error {}

function canonicalProducerDir(value: unknown): string {
  if (typeof value !== "string" || !path.isAbsolute(value)) {
    throw new StopRequestError("dir must be an absolute Producer project path");
  }
  let dir: string;
  try { dir = realpathSync(value.replace(/\/$/, "")); } catch {
    throw new StopRequestError(`dir not found: ${value}`);
  }
  const workspace = realpathSync(workspaceRoot());
  const relative = path.relative(workspace, dir);
  const root = findProjectRoot(dir);
  const outside = relative === "" || relative.startsWith("..") || path.isAbsolute(relative);
  if (outside || !root || dir !== path.join(realpathSync(root), "producer")) {
    throw new StopRequestError("Stop may target only a canonical producer/ directory in the local workspace");
  }
  return dir;
}

function requiredToken(value: unknown): string {
  if (typeof value !== "string" || !value || value.length > 240 || /[\r\n\0]/.test(value)) {
    throw new StopRequestError("token must identify the current Auto Edit attempt");
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
    const result = stopAutoEdit({
      dir: canonicalProducerDir(body.dir),
      token: requiredToken(body.token),
    });
    return NextResponse.json({ ok: true, ...result });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    if (error instanceof AutoEditStopConflictError) {
      return NextResponse.json({ error: message }, { status: 409 });
    }
    if (error instanceof AutoEditStopSignalError) {
      return NextResponse.json({ error: message, interrupted: true }, { status: 500 });
    }
    if (error instanceof StopRequestError) {
      return NextResponse.json({ error: message }, { status: 400 });
    }
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
