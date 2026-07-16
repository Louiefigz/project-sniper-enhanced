import { NextRequest, NextResponse } from "next/server";
import fs from "fs";
import path from "path";
import { createProjectRoot, writeProjectJson } from "../../_lib/workspace";
import { upsertProject } from "../../_lib/projects-registry";
import { dlog } from "@/lib/debug";

export const runtime = "nodejs";

// CLIPPER → WORKSPACE (smallest possible touch). The FCPXML is built
// client-side; this just persists a copy into a NEW workspace project's
// clipper/ dir with provenance (project.json origin:"clipper") and registers
// the project. The browser download stays the primary export path.
export async function POST(req: NextRequest) {
  let body: { files?: unknown };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }
  const files = body.files as { name?: unknown; xml?: unknown }[] | undefined;
  if (!Array.isArray(files) || files.length === 0) {
    return NextResponse.json({ error: "No files" }, { status: 400 });
  }
  for (const f of files) {
    const bad =
      typeof f?.name !== "string" ||
      !f.name.endsWith(".fcpxml") ||
      f.name.includes("/") ||
      f.name.includes("..") ||
      typeof f?.xml !== "string" ||
      f.xml.length === 0;
    if (bad) {
      return NextResponse.json(
        { error: "each file needs a flat *.fcpxml name and non-empty xml" },
        { status: 400 },
      );
    }
  }

  try {
    const projectRoot = createProjectRoot((files[0].name as string).replace(/\.fcpxml$/, ""));
    const clipperDir = path.join(projectRoot, "clipper");
    fs.mkdirSync(clipperDir, { recursive: true });
    const written = files.map((f) => {
      const dest = path.join(clipperDir, f.name as string);
      fs.writeFileSync(dest, f.xml as string);
      return dest;
    });
    writeProjectJson(projectRoot, {
      origin: "clipper",
      history: [{ stage: "source", at: new Date().toISOString() }],
    });
    upsertProject(projectRoot, path.basename(projectRoot));
    dlog("clipper:workspace", "saved", { projectRoot, files: written.length });
    return NextResponse.json({ ok: true, projectRoot, files: written });
  } catch (e) {
    return NextResponse.json({ error: e instanceof Error ? e.message : String(e) }, { status: 500 });
  }
}
