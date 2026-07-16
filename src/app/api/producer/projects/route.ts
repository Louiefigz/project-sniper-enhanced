import { NextRequest, NextResponse } from "next/server";
import path from "path";
import { listProjects, removeProject, upsertProject } from "../../_lib/projects-registry";
import { dlog } from "@/lib/debug";

export const dynamic = "force-dynamic";

// PROJECT BROWSER API over the ~/.project-sniper/projects.json registry.
//   GET    → entries newest-first, each with exists:boolean + dir mtime.
//   POST   {dir, title?} → upsert (flow render completion + editor open).
//   DELETE ?dir=…        → drop a registry entry (for stale/missing dirs).
// The registry stores render OUT dirs only; nothing here reads or writes the
// dirs themselves beyond a stat.

export async function GET() {
  try {
    return NextResponse.json({ projects: listProjects() });
  } catch (e) {
    return NextResponse.json({ error: (e as Error).message }, { status: 500 });
  }
}

export async function POST(req: NextRequest) {
  const body = (await req.json().catch(() => ({}))) as { dir?: string; title?: unknown };
  const dir = (body.dir || "").replace(/\/$/, "");
  if (!dir || !path.isAbsolute(dir)) {
    return NextResponse.json({ error: "dir must be an absolute path" }, { status: 400 });
  }
  if (dir.split("/").includes("..")) {
    return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  }
  if (body.title !== undefined && (typeof body.title !== "string" || !body.title.trim())) {
    return NextResponse.json({ error: "title must be a non-empty string" }, { status: 400 });
  }
  const title = typeof body.title === "string" ? body.title.trim().slice(0, 120) : "";
  try {
    upsertProject(dir, title);
    dlog("producer:projects", "upsert", { dir, title });
    return NextResponse.json({ ok: true });
  } catch (e) {
    return NextResponse.json({ error: (e as Error).message }, { status: 500 });
  }
}

export async function DELETE(req: NextRequest) {
  const dir = (req.nextUrl.searchParams.get("dir") || "").replace(/\/$/, "");
  if (!dir) return NextResponse.json({ error: "Missing dir" }, { status: 400 });
  try {
    removeProject(dir);
    dlog("producer:projects", "removed", { dir });
    return NextResponse.json({ ok: true });
  } catch (e) {
    return NextResponse.json({ error: (e as Error).message }, { status: 500 });
  }
}
