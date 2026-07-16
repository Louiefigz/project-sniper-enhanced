import { NextRequest, NextResponse } from "next/server";
import fs from "fs";
import path from "path";
import { slugify, workspaceRoot } from "../../_lib/workspace";
import { removeProject, upsertProject } from "../../_lib/projects-registry";
import {
  findReferenceById,
  ignoreReferenceIds,
  listReferenceLibrary,
  stableReferenceId,
  videoExtensions,
  writeReferenceSource,
} from "../../_lib/reference-library";
import { dlog } from "@/lib/debug";
import {
  localIntakePreflight,
  ReferenceMediaError,
  validateCopiedReference,
} from "../../_lib/reference-intake-policy";

export const dynamic = "force-dynamic";

function referencesRoot(): string {
  return path.join(workspaceRoot(), "_references");
}

function nextReferenceDir(src: string): string {
  const base = slugify(path.basename(src));
  let dir = path.join(referencesRoot(), base);
  for (let n = 2; fs.existsSync(dir); n++) dir = path.join(referencesRoot(), `${base}-${n}`);
  return dir;
}

function localStagingDir(): string {
  const root = referencesRoot();
  fs.mkdirSync(root, { recursive: true });
  return fs.mkdtempSync(path.join(root, ".incoming-local-"));
}

function copySiblingVtts(src: string, dir: string): string[] {
  const parent = path.dirname(src);
  const stem = path.parse(src).name;
  const names = fs.readdirSync(parent)
    .filter((name) => name.startsWith(stem) && name.toLowerCase().endsWith(".vtt"));
  for (const name of names) fs.copyFileSync(path.join(parent, name), path.join(dir, name));
  return names.map((name) => path.join(dir, name));
}

export async function GET() {
  try {
    return NextResponse.json({ references: listReferenceLibrary() });
  } catch (error) {
    return NextResponse.json({ error: (error as Error).message }, { status: 500 });
  }
}

export async function POST(req: NextRequest) {
  const body = (await req.json().catch(() => null)) as { path?: string } | null;
  const src = (body?.path || "").replace(/\/$/, "");
  if (!src || !path.isAbsolute(src)) {
    return NextResponse.json({ error: "path must be an absolute file path" }, { status: 400 });
  }
  if (!fs.existsSync(src) || !fs.statSync(src).isFile()) {
    return NextResponse.json({ error: `not a file: ${src}` }, { status: 404 });
  }
  if (!videoExtensions().has(path.extname(src).toLowerCase())) {
    return NextResponse.json({ error: `unsupported reference video: ${src}` }, { status: 422 });
  }
  const root = referencesRoot();
  fs.mkdirSync(root, { recursive: true });
  const sourceStat = fs.statSync(src, { bigint: true });
  const storage = fs.statfsSync(root, { bigint: true });
  const preflight = localIntakePreflight(sourceStat.size, storage.bavail * storage.bsize);
  if (preflight) {
    return NextResponse.json({ error: preflight.message }, { status: preflight.status });
  }
  const staging = localStagingDir();
  const dir = nextReferenceDir(src);
  let promoted = false;
  let registered = false;
  try {
    const stagedVideo = path.join(staging, path.basename(src));
    await fs.promises.copyFile(src, stagedVideo);
    validateCopiedReference(stagedVideo);
    copySiblingVtts(src, staging);
    fs.renameSync(staging, dir);
    promoted = true;
    const video = path.join(dir, path.basename(src));
    const transcripts = fs.readdirSync(dir)
      .filter((name) => name.toLowerCase().endsWith(".vtt"))
      .map((name) => path.join(dir, name));
    upsertProject(dir, path.basename(src), "reference");
    registered = true;
    writeReferenceSource(dir, {
      kind: "local",
      originalPath: src,
      importedAt: new Date().toISOString(),
      transcripts,
    });
    const id = stableReferenceId(video);
    const reference = findReferenceById(id);
    dlog("producer:references", "registered", { id, dir, video });
    return NextResponse.json({ ok: true, id, dir, video, reference });
  } catch (error) {
    if (registered) removeProject(dir);
    fs.rmSync(promoted ? dir : staging, { recursive: true, force: true });
    const status = error instanceof ReferenceMediaError ? 422 : 500;
    return NextResponse.json({ error: (error as Error).message }, { status });
  }
}

export async function DELETE(req: NextRequest) {
  const id = (req.nextUrl.searchParams.get("id") || "").trim();
  const dir = (req.nextUrl.searchParams.get("dir") || "").replace(/\/$/, "");
  if (!id && !dir) return NextResponse.json({ error: "Missing id" }, { status: 400 });
  try {
    const references = listReferenceLibrary();
    const targets = id ? references.filter((entry) => entry.id === id) :
      references.filter((entry) => path.resolve(entry.dir) === path.resolve(dir));
    if (!targets.length) return NextResponse.json({ error: "reference not found" }, { status: 404 });
    ignoreReferenceIds(targets.map((entry) => entry.id));
    for (const target of targets) removeProject(target.dir);
    dlog("producer:references", "tombstoned", { ids: targets.map((entry) => entry.id) });
    return NextResponse.json({ ok: true, ids: targets.map((entry) => entry.id) });
  } catch (error) {
    return NextResponse.json({ error: (error as Error).message }, { status: 500 });
  }
}
