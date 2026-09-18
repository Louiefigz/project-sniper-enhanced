/** Stage an operator-selected file for the existing sandbox admission/rescan path. */
import { createHash, randomUUID } from "node:crypto";
import { createReadStream, lstatSync, mkdirSync, realpathSync, renameSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";
import { copyStableSource, stableCopySource } from "@/app/api/producer/ingest/source-copy";
import { guardProjectMutation } from "@/app/api/_lib/project-mutation";
import { cutPreviewLeaseGuard } from "@/app/api/producer/auto-edit/cut-preview-lease";
import { SUPPORTING_MEDIA_EXTENSIONS } from "@/lib/producer/native-media-picker";
import { canonicalJson } from "./auto-edit-hash";

interface IntakeInput { dir: string; root: string; inputPath: string; signal: AbortSignal }
interface Dependencies { copy: typeof copyStableSource }

function canonicalDirectory(directory: string): void {
  if (realpathSync(directory) !== directory || !lstatSync(directory).isDirectory()) {
    throw new Error("Supporting-media destination must be a canonical project directory");
  }
}

function selectedFile(file: string) {
  if (!path.isAbsolute(file) || realpathSync(file) !== file) throw new Error("Select a canonical local supporting file");
  const info = lstatSync(file, { bigint: true });
  if (!info.isFile() || info.nlink !== BigInt(1) || info.size < BigInt(1) || info.size > BigInt(1024 ** 3)) {
    throw new Error("Supporting media must be a regular file between 1 byte and 1 GiB");
  }
  if (path.basename(file).startsWith(".") || !(SUPPORTING_MEDIA_EXTENSIONS as readonly string[]).includes(path.extname(file).toLowerCase())) {
    throw new Error("Choose PNG, JPEG, WebP, MP4 or MOV; SVG and other formats need a supported local derivative");
  }
  return stableCopySource(file, path.basename(file), info);
}

async function digestFile(file: string, signal: AbortSignal): Promise<string> {
  const hash = createHash("sha256");
  for await (const chunk of createReadStream(file, { signal })) hash.update(chunk);
  return hash.digest("hex");
}

async function stageSelection(input: IntakeInput, copy: typeof copyStableSource, guard: () => void) {
  guard(); input.signal.throwIfAborted();
  const entry = selectedFile(input.inputPath), source = path.join(input.root, "source"), broll = path.join(source, "broll");
  canonicalDirectory(source); mkdirSync(broll, { recursive: true, mode: 0o700 }); canonicalDirectory(broll);
  const id = randomUUID(), staging = path.join(broll, `.supporting-${id}`), destination = path.join(broll, `import-${id}`);
  mkdirSync(staging, { mode: 0o700 });
  try {
    const staged = path.join(staging, entry.relative);
    await copy(entry, staged, () => { guard(); input.signal.throwIfAborted(); }, input.signal);
    const sha256 = await digestFile(staged, input.signal);
    const receipt = { schemaVersion: 1, status: "staged-awaiting-sandbox-admission", originalPath: entry.source,
      path: path.join(destination, entry.relative), sha256, sizeBytes: entry.size, importedAt: new Date().toISOString() };
    writeFileSync(path.join(staging, ".sniper-supplied.json"), canonicalJson(receipt), { flag: "wx", mode: 0o600 });
    guard(); input.signal.throwIfAborted(); canonicalDirectory(source); canonicalDirectory(broll); canonicalDirectory(staging);
    renameSync(staging, destination);
    return { ...receipt, sourceDir: source, providerCalls: 0 };
  } finally { rmSync(staging, { recursive: true, force: true }); }
}

/** Ordinary mutation admission deliberately refuses any accepted guided checkpoint. */
export async function stageSupportingMedia(input: IntakeInput, dependencies: Partial<Dependencies> = {}): Promise<Response> {
  const held = guardProjectMutation({ projectRoot: input.root, producerDir: input.dir, operation: "adding supporting media" });
  if (held.response) return held.response;
  try {
    const guard = cutPreviewLeaseGuard(input.dir, held.lease);
    const result = await stageSelection(input, dependencies.copy ?? copyStableSource, guard);
    return Response.json(result);
  } finally { held.lease.release(); }
}
