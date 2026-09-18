import { NextRequest, NextResponse } from "next/server";
import path from "node:path";
import { realpathSync } from "node:fs";
import { localApiRejection } from "@/lib/server/local-request-policy";
import { prepareNativeShortAppRequest } from "@/lib/server/native-short-app-preparation";
import { findProjectRoot, workspaceRoot } from "../../_lib/workspace";

export const dynamic = "force-dynamic";

/** Local preparation only. The native CLI owns execution; no subscription call here. */
export async function POST(req: NextRequest) {
  const rejection = localApiRejection({ method: req.method, pathname: req.nextUrl.pathname,
    protocol: req.nextUrl.protocol, host: req.headers.get("host"), origin: req.headers.get("origin"),
    secFetchSite: req.headers.get("sec-fetch-site"), contentType: req.headers.get("content-type") });
  if (rejection) return NextResponse.json({ error: rejection.error }, { status: rejection.status });
  try {
    const body = await req.json();
    if (!body || typeof body.dir !== "string" || Object.keys(body).some((key) => key !== "dir")) {
      throw new Error("Native Short preparation needs only the stored producer directory");
    }
    const dir = realpathSync(body.dir), workspace = realpathSync(workspaceRoot());
    if (!dir.startsWith(workspace + path.sep) || path.basename(dir) !== "producer") throw new Error("Producer directory must belong to the configured workspace");
    const root = findProjectRoot(dir);
    if (!root || dir !== path.join(root, "producer")) throw new Error("Producer directory is not a workspace project");
    return prepareNativeShortAppRequest({ dir, root });
  } catch (error) {
    return NextResponse.json({ error: (error as Error).message }, { status: 400 });
  }
}
