import { NextRequest, NextResponse } from "next/server";
import path from "node:path";
import { realpathSync } from "node:fs";
import { localApiRejection } from "@/lib/server/local-request-policy";
import { stageSupportingMedia } from "@/lib/server/supporting-media-intake";
import { findProjectRoot, workspaceRoot } from "../../_lib/workspace";

export const dynamic = "force-dynamic";

/** Copy locally before source admission; never modifies an accepted guided manifest. */
export async function POST(req: NextRequest) {
  const rejection = localApiRejection({ method: req.method, pathname: req.nextUrl.pathname,
    protocol: req.nextUrl.protocol, host: req.headers.get("host"), origin: req.headers.get("origin"),
    secFetchSite: req.headers.get("sec-fetch-site"), contentType: req.headers.get("content-type") });
  if (rejection) return NextResponse.json({ error: rejection.error }, { status: rejection.status });
  try {
    const body = await req.json();
    if (!body || typeof body.dir !== "string" || typeof body.inputPath !== "string"
        || Object.keys(body).some(key => !["dir", "inputPath"].includes(key))) throw new Error("Supporting media needs only dir and inputPath");
    const dir = realpathSync(body.dir), workspace = realpathSync(workspaceRoot()), root = findProjectRoot(dir);
    if (!dir.startsWith(workspace + path.sep) || !root || dir !== path.join(root, "producer")) {
      throw new Error("Producer directory must belong to the configured workspace");
    }
    return await stageSupportingMedia({ dir, root, inputPath: body.inputPath, signal: req.signal });
  } catch (error) {
    return NextResponse.json({ error: (error as Error).message }, { status: 400 });
  }
}
