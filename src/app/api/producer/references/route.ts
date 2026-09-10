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
} from "../../_lib/reference-intake-policy";
import { admitReferenceMedia } from "../../_lib/reference-media-admission";
import {
  admitReferenceVtt,
  type ReferenceTextAdmission,
} from "../../_lib/reference-sidecar";

export const dynamic = "force-dynamic";
export const maxDuration = 1800;

function referencesRoot(): string {
  return path.join(workspaceRoot(), "_references");
}

function createDirectory(directory: string): boolean {
  try {
    fs.mkdirSync(directory);
    return true;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "EEXIST") return false;
    throw error;
  }
}

function createReferenceDir(src: string): string {
  const root = referencesRoot();
  fs.mkdirSync(root, { recursive: true });
  const base = slugify(path.basename(src));
  for (let n = 1; ; n++) {
    const dir = path.join(root, n === 1 ? base : `${base}-${n}`);
    if (createDirectory(dir)) return dir;
  }
}

function copySiblingVtts(
  src: string,
  video: string,
): ReferenceTextAdmission[] {
  const parent = path.dirname(src);
  const stem = path.parse(src).name;
  const names = fs.readdirSync(parent)
    .filter((name) => name.startsWith(stem) && name.toLowerCase().endsWith(".vtt"));
  if (names.length > 20) throw new ReferenceMediaError("reference has too many VTT sidecars");
  const destinationStem = path.parse(video).name;
  return names.map((name) => {
    const source = path.join(parent, name);
    const destination = path.join(
      path.dirname(video), `${destinationStem}${name.slice(stem.length)}`,
    );
    return admitReferenceVtt(source, destination);
  });
}

export async function GET() {
  try {
    return NextResponse.json({ references: listReferenceLibrary() });
  } catch (error) {
    return NextResponse.json({ error: (error as Error).message }, { status: 500 });
  }
}

async function registerReference(
  src: string,
  dir: string,
  signal: AbortSignal,
): Promise<NextResponse> {
  let registered = false;
  try {
    const pending = path.join(dir, ".sniper-admission-pending");
    fs.writeFileSync(pending, `${new Date().toISOString()}\n`, { flag: "wx" });
    const admission = await admitReferenceMedia(src, dir, signal);
    const video = admission.snapshotPath;
    const transcripts = copySiblingVtts(src, video);
    upsertProject(dir, path.basename(src), "reference");
    registered = true;
    writeReferenceSource(dir, {
      kind: "local", originalPath: src,
      importedAt: new Date().toISOString(), transcripts, admission,
    });
    fs.unlinkSync(pending);
    const id = stableReferenceId(video);
    const reference = findReferenceById(id);
    dlog("producer:references", "registered", { id, dir, video });
    return NextResponse.json({ ok: true, id, dir, video, reference });
  } catch (error) {
    if (registered) removeProject(dir);
    fs.rmSync(dir, { recursive: true, force: true });
    const status = error instanceof ReferenceMediaError ? 422 : 500;
    return NextResponse.json({ error: (error as Error).message }, { status });
  }
}

export async function POST(req: NextRequest) {
  const body = (await req.json().catch(() => null)) as { path?: string } | null;
  const src = (body?.path || "").replace(/\/$/, "");
  if (!src || !path.isAbsolute(src)) {
    return NextResponse.json({ error: "path must be an absolute file path" }, { status: 400 });
  }
  if (!fs.existsSync(src) || !fs.lstatSync(src).isFile() ||
      fs.lstatSync(src).isSymbolicLink()) {
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
  let dir: string;
  try {
    dir = createReferenceDir(src);
  } catch (error) {
    return NextResponse.json(
      { error: `could not allocate reference storage: ${(error as Error).message}` },
      { status: 500 },
    );
  }
  return registerReference(src, dir, req.signal);
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
