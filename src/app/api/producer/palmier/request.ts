import { realpathSync } from "node:fs";
import path from "node:path";
import type { NextRequest } from "next/server";
import { findProjectRoot, workspaceRoot } from "../../_lib/workspace";
import { localApiRejection } from "@/lib/server/local-request-policy";

export interface PalmierRequestError {
  error: string;
  status: number;
}

export function localPalmierRejection(req: NextRequest): PalmierRequestError | null {
  return localApiRejection({
    method: req.method,
    pathname: req.nextUrl.pathname,
    protocol: req.nextUrl.protocol,
    host: req.headers.get("host"),
    origin: req.headers.get("origin"),
    secFetchSite: req.headers.get("sec-fetch-site"),
    contentType: req.headers.get("content-type"),
  });
}

/** Limit Palmier app/MCP mutations to one canonical local producer directory. */
export function canonicalPalmierDir(value: unknown): string {
  if (typeof value !== "string" || !path.isAbsolute(value)) {
    throw new Error("dir must be an absolute Producer project path");
  }
  let dir: string;
  try { dir = realpathSync(value.replace(/\/$/, "")); } catch {
    throw new Error(`dir not found: ${value}`);
  }
  const workspace = realpathSync(workspaceRoot());
  const relative = path.relative(workspace, dir);
  const root = findProjectRoot(dir);
  const outside = relative === "" || relative.startsWith("..") || path.isAbsolute(relative);
  if (outside || !root || dir !== path.join(realpathSync(root), "producer")) {
    throw new Error("Palmier may target only a canonical producer/ directory in the local workspace");
  }
  return dir;
}
