import path from "path";
import { existsSync } from "fs";
import { NextRequest, NextResponse } from "next/server";
import { findProjectRoot, readProjectJson } from "../../../_lib/workspace";
import { autoEditQcApproval, findManifest } from "../_lib";
import { activatePalmierView } from "../view/activate";
import { loadViewTarget } from "../view/target";
import { canonicalPalmierDir, localPalmierRejection } from "../request";
import { ensurePalmierApp } from "./launch";
import { createPalmierDraft } from "./runner";

export const dynamic = "force-dynamic";

interface RequestBody {
  dir?: unknown;
  mode?: unknown;
  name?: unknown;
}

/** Create/open a labeled source or saved-cut working view; never claims mirror approval. */
export async function POST(req: NextRequest) {
  if (process.platform !== "darwin") {
    return NextResponse.json({ error: "Palmier launching is only supported on macOS." }, { status: 400 });
  }
  const rejection = localPalmierRejection(req);
  if (rejection) return NextResponse.json({ error: rejection.error }, { status: rejection.status });
  const body = await req.json().catch(() => null) as RequestBody | null;
  let dir: string;
  try { dir = canonicalPalmierDir(body?.dir); } catch (error) {
    return NextResponse.json({ error: (error as Error).message }, { status: 400 });
  }
  const manifestPath = findManifest(dir);
  if (!manifestPath) {
    return NextResponse.json({ error: "Prepare media before opening its Palmier working view." }, { status: 409 });
  }
  const mode = storedMode(dir) ?? requestMode(body?.mode);
  if (!mode) {
    return NextResponse.json({ error: "Choose and save Short or Long before opening Palmier." }, { status: 409 });
  }
  const name = typeof body?.name === "string" && body.name.trim()
    ? body.name.trim() : path.basename(findProjectRoot(dir) ?? dir);
  try {
    await ensurePalmierApp();
    const savedCut = workingMedia(dir);
    const result = await createPalmierDraft({
      manifestPath, dir, name, mode,
      ...(savedCut ? { workingPath: savedCut } : {}),
    });
    if (result.code !== 0) {
      const message = String(result.event.reason ?? result.event.error ?? result.stderr);
      return NextResponse.json({ error: message || "Palmier working view could not be created." }, {
        status: result.code === 75 ? 409 : 500,
      });
    }
    const target = loadViewTarget(dir);
    if ("error" in target) {
      return NextResponse.json({ error: target.error }, { status: target.status });
    }
    const timeline = await activatePalmierView(target);
    return NextResponse.json({
      ok: true,
      viewOnly: false,
      ownership: target.ownership,
      ownershipChanged: false,
      kind: target.kind,
      verified: target.verified,
      timelineId: timeline.id,
      timelineName: timeline.name,
      message: target.kind === "working-draft"
          ? savedCut
          ? "Palmier is showing the latest saved cut. Manual changes become the working source of truth; governed AI changes start from this exact revision."
          : "Palmier is showing the managed source view. Manual changes become the working source of truth; Sniper will not overwrite them with a stale plan."
        : "Palmier is showing the latest managed edit. Opening alone changes nothing; manual edits become the working source of truth.",
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Could not prepare Palmier.";
    return NextResponse.json({ error: message }, { status: 502 });
  }
}

function workingMedia(dir: string): string | null {
  const approvedFinal = path.join(dir, "final.mp4");
  if (existsSync(approvedFinal) && autoEditQcApproval(dir).approved) return approvedFinal;
  const savedCut = path.join(dir, "base_final.mp4");
  return existsSync(savedCut) ? savedCut : null;
}

function storedMode(dir: string): "short" | "longform" | null {
  const root = findProjectRoot(dir);
  if (!root) return null;
  const mode = readProjectJson(root)?.resolvedIntent?.mode ?? readProjectJson(root)?.intent?.mode;
  return mode === "short" || mode === "longform" ? mode : null;
}

function requestMode(value: unknown): "short" | "longform" | null {
  return value === "short" || value === "longform" ? value : null;
}
