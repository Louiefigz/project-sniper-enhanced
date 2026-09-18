import { NextRequest, NextResponse } from "next/server";
import fs from "fs";
import path from "path";
import {
  findProjectRoot,
  readProjectJson,
  recordProjectIntentResolution,
} from "../../_lib/workspace";
import { guardProjectMutation } from "../../_lib/project-mutation";
import { reconcileIntentCapabilities } from "@/lib/producer/intent-capabilities";
import { validateIntent } from "@/lib/producer/intent-presets";
import type { AssetManifest } from "@/lib/producer/types";
import { dlog } from "@/lib/debug";

export const dynamic = "force-dynamic";

// INTENT round-trip over project.json — the stored "what did the operator ask
// for" that prefills Auto-edit and badges the project cards / editor header.
//   GET  ?dir=…          → {projectRoot, intent|null} (dir = project root OR producer/)
//   POST {dir, intent}   → validate (edit_scope vocabulary, fail loudly) + write
// The ingest route also writes intent at project creation; this route covers
// updates on existing projects and gives the brain a stable read/write seam.

function resolveRoot(rawDir: string): string {
  const dir = rawDir.replace(/\/$/, "");
  if (!dir || !path.isAbsolute(dir)) throw new Error("dir must be an absolute path");
  const root = findProjectRoot(dir);
  if (!root) throw new Error(`no project.json found for ${dir}`);
  return root;
}

function readManifest(root: string): AssetManifest {
  const manifestPath = path.join(root, "source", "asset_manifest.json");
  if (!fs.existsSync(manifestPath)) {
    throw new Error("Prepare the project media before saving an edit request.");
  }
  return JSON.parse(fs.readFileSync(manifestPath, "utf8")) as AssetManifest;
}

export async function GET(req: NextRequest) {
  try {
    const root = resolveRoot(req.nextUrl.searchParams.get("dir") || "");
    const project = readProjectJson(root);
    return NextResponse.json({
      projectRoot: root,
      intent: project?.resolvedIntent ?? project?.intent ?? null,
      requestedIntent: project?.requestedIntent ?? project?.intent ?? null,
      intentDecisions: project?.intentDecisions ?? [],
    });
  } catch (e) {
    const msg = (e as Error).message;
    return NextResponse.json({ error: msg }, { status: msg.startsWith("no project.json") ? 404 : 400 });
  }
}

export async function POST(req: NextRequest) {
  const body = (await req.json().catch(() => null)) as { dir?: string; intent?: unknown } | null;
  if (!body) return NextResponse.json({ error: "body must be JSON" }, { status: 400 });
  let root: string;
  try {
    root = resolveRoot(body.dir || "");
  } catch (e) {
    const msg = (e as Error).message;
    return NextResponse.json({ error: msg }, { status: msg.startsWith("no project.json") ? 404 : 400 });
  }
  const guarded = guardProjectMutation({
    projectRoot: root,
    producerDir: path.join(root, "producer"),
    operation: "saving this edit request",
  });
  if (guarded.response) return guarded.response;
  try {
    const intent = validateIntent(body.intent);
    const resolution = reconcileIntentCapabilities(intent, readManifest(root));
    recordProjectIntentResolution(root, resolution, "intent");
    dlog("producer:intent", "set", { root, resolution });
    if (!resolution.ok) {
      return NextResponse.json({
        error: resolution.error,
        projectRoot: root,
        requestedIntent: resolution.requestedIntent,
        intent: null,
        intentDecisions: resolution.decisions,
      }, { status: 409 });
    }
    return NextResponse.json({
      ok: true,
      projectRoot: root,
      requestedIntent: resolution.requestedIntent,
      intent: resolution.resolvedIntent,
      intentDecisions: resolution.decisions,
    });
  } catch (e) {
    return NextResponse.json({ error: (e as Error).message }, { status: 400 });
  } finally {
    guarded.lease.release();
  }
}
