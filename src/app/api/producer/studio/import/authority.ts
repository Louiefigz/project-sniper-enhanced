import fs from "node:fs";
import path from "node:path";
import { assertStudioPaths, verifyStudioMedia } from "../paths";
import { ImportError, type Capture } from "./model";
import { decodeText, readBytes, readText, sha } from "./files";

const IGNORED = new Set([".hyperframes", ".thumbnails", ".waveform-cache", ".DS_Store", ".studio-server.json"]);
const SOURCE_ROOT = path.join(process.cwd(), "templates", "motion");
const PIPELINE = path.join(process.cwd(), "scripts", "producer");

function walk(root: string, exclude: Set<string>, limit = 4_000): string[] {
  const pending = [root]; const files: string[] = [];
  let count = 0;
  while (pending.length) {
    const item = pending.pop()!;
    if (++count > limit) throw new ImportError("Studio import input tree exceeds the bounded limit");
    if (fs.realpathSync(item) !== item) throw new ImportError("Studio import input tree contains a symlink");
    const stat = fs.lstatSync(item);
    if (stat.isFile()) files.push(item);
    else if (stat.isDirectory()) pending.push(...fs.readdirSync(item).filter((name) => !exclude.has(name)).map((name) => path.join(item, name)));
    else throw new ImportError("Studio import input tree contains a special file");
  }
  return files.sort();
}

function sourceAuthority(): string {
  const roots = [path.join(SOURCE_ROOT, "compositions"), path.join(SOURCE_ROOT, "icons"),
    path.join(SOURCE_ROOT, "assets"), path.join(SOURCE_ROOT, "vendor", "gsap"), PIPELINE];
  const exclude = new Set(["__pycache__", "tests", "node_modules", "renders", "cache", "docs"]);
  const files = roots.flatMap((root) => fs.existsSync(root) ? walk(root, exclude) : []);
  files.push(path.join(SOURCE_ROOT, "tokens.css"), path.join(SOURCE_ROOT, "motion-tokens.js"));
  files.push(...walk(path.join(process.cwd(), "src", "app", "api", "producer", "studio", "import"), new Set(["__pycache__"]))
    .filter((file) => !file.endsWith(".test.ts") && !file.endsWith("_test.py") && !file.endsWith("_test.ts")));
  files.push(...["src/app/api/producer/save-plan/transaction.ts", "src/app/api/_lib/plan-refit-receipt.ts",
    "src/app/api/_lib/plan-snapshots.ts", "src/lib/server/atomic-file.ts", "src/lib/producer/graphic-ids.ts",
    "src/lib/server/template-usage-approval.ts"].map((file) => path.join(process.cwd(), file)));
  files.push(...["review-policy.json", "review-shell.cjs", "review-shell-runtime.cjs", "review-shell-ui.js",
    "review-only.cjs", "review-attribute-interop.cjs", "loopback-only.cjs"]
    .map((file) => path.join(process.cwd(), "src/app/api/producer/studio", file)));
  const rows = files.filter((file) => /\.(?:py|ts|html|css|c?js|svg|png|jpe?g|webp|json)$/iu.test(file))
    .map((file) => [file, sha(readBytes(file))]);
  return sha(JSON.stringify(rows));
}

function baseIdentity(dir: string, relative: string): string[][] {
  return [path.join(dir, "base_final.mp4"), path.join(dir, "studio", relative)].map((file) => {
    const stat = fs.statSync(file, { bigint: true });
    return [file, stat.dev, stat.ino, stat.size, stat.mtimeNs, stat.ctimeNs].map(String);
  });
}

function projectParents(dir: string): string {
  const root = path.dirname(dir);
  const names = [path.join(root, "project.json"), ...["asset_manifest.json", "base_plan.json", "base.fingerprint.json"].map((name) => path.join(dir, name))];
  const manifest = JSON.parse(readText(path.join(dir, "asset_manifest.json"))) as { sources?: { transcriptPath?: unknown }[] };
  for (const source of manifest.sources ?? []) {
    if (source.transcriptPath == null) continue;
    if (typeof source.transcriptPath !== "string") throw new ImportError("Manifest transcript binding is malformed");
    const file = path.resolve(dir, source.transcriptPath);
    if (!file.startsWith(`${root}/`)) throw new ImportError("Studio import requires project-local transcript evidence");
    names.push(file);
  }
  return sha(JSON.stringify(names.sort().map((file) => [file, sha(readText(file))])));
}

/** Exact non-media inputs, excluding only the upstream's known runtime/cache files. */
export function captureStudio(dir: string, baseHash: string): Capture {
  assertStudioPaths(dir);
  const studio = path.join(dir, "studio");
  const manifestText = readText(path.join(studio, "studio.manifest.json"));
  const manifest = JSON.parse(manifestText) as { media: { rel: string }; entries: { file: string }[] };
  const textPaths = new Set(["index.html", ...manifest.entries.map((entry) => entry.file)]);
  const files: Record<string, string> = {}; const textFiles: Record<string, string> = {};
  for (const file of walk(studio, IGNORED)) {
    const relative = path.relative(studio, file);
    if (relative === manifest.media.rel) continue;
    const bytes = readBytes(file);
    files[relative] = sha(bytes);
    if (textPaths.has(relative)) textFiles[relative] = decodeText(bytes);
  }
  const planText = readText(path.join(dir, "edit_plan.json"));
  const authority = sha(JSON.stringify([baseHash, baseIdentity(dir, manifest.media.rel), projectParents(dir), sourceAuthority(), manifestText]));
  return { planText, planHash: sha(planText), authority, manifestText, files, textFiles, baseHash,
    snapshot: sha(JSON.stringify([files, baseHash])) };
}

export async function stableCapture(dir: string): Promise<Capture> {
  assertStudioPaths(dir);
  const baseHash = await verifyStudioMedia(dir);
  const before = captureStudio(dir, baseHash);
  const after = captureStudio(dir, await verifyStudioMedia(dir));
  if (before.snapshot !== after.snapshot || before.authority !== after.authority || before.planHash !== after.planHash) {
    throw new ImportError("Studio or project inputs changed while preparing the review; try again");
  }
  return after;
}

/** No async work between this final exact check and the ordinary atomic plan save. */
export function assertCaptureCurrent(dir: string, capture: Capture): void {
  const current = captureStudio(dir, capture.baseHash);
  if (current.planHash !== capture.planHash || JSON.stringify(current.files) !== JSON.stringify(capture.files)
      || current.authority !== capture.authority) throw new ImportError("Reviewed Studio or project inputs changed; prepare changes again");
}
