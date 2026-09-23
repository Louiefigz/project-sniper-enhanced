import { createHash } from "node:crypto";
import {
  existsSync,
  lstatSync,
  readFileSync,
  readdirSync,
} from "node:fs";
import path from "node:path";
import type {
  PipelineAuthorityFile,
} from "@/app/api/producer/auto-edit/stream";

const SOURCE_EXTENSIONS =
  /\.(?:py|ts|tsx|js|cjs|mjs|json|html|css|md|markdown|svg|png|jpe?g|txt)$/i;
const ASSET_EXTENSIONS = /\.(?:otf|ttf|onnx|wav|mp3)$/i;
const NEVER_CAPTURE = /\.(?:mov|mp4|pyc)$/i;
const EXCLUDED_PARTS = new Set([
  "__pycache__", "__tests__", "node_modules", "renders", "cache", "tests", "study",
  "artifacts", ".sniper-native-runtime",
]);
const EXCLUDED_PREFIXES = ["scripts/producer/docs/"];

const REQUIRED_HASHES = new Map([
  ["scripts/producer/audio/models/bd.rnnn",
    "ae3f7411e1e6a884f839a4a145c394408398f09854dbc1216ee02faafc98a17b"],
]);

const REQUIRED_FILES = [
  "schemas/producer/visual-source-policy-v1.json",
  "vendor/hyperframes-catalog/catalog-index.json",
  "vendor/hyperframes-catalog/hyperframes-catalog-lock.json",
  "docs/producer/catalog-study/catalog-study.json",
  "package.json",
  "package-lock.json",
  "scripts/producer/headless/node_isolated_user.cjs",
  "docs/producer/command-driven-editing/contracts/render-effect-registry-v1.json",
  "schemas/producer/render-effect-registry-v1.schema.json",
  "templates/motion/hyperframes.json",
  "templates/motion/index.html",
  "templates/motion/motion-tokens.js",
  "templates/motion/package.json",
  "templates/motion/tokens.css",
  "templates/motion/vendor/gsap/gsap.min.js",
] as const;

const REQUIRED_PREFIXES = [
  "assets/fonts/",
  "assets/models/",
  "assets/music/",
  "assets/sfx/",
  "docs/producer/command-driven-editing/contracts/",
  "schemas/producer/",
  "scripts/producer/",
  "templates/motion/compositions/",
] as const;

const SOURCE_PATHS = [
  "vendor/hyperframes-catalog",
  "docs/producer/catalog-study",
  "scripts/producer",
  "templates/motion",
  "schemas/producer",
  "docs/producer/command-driven-editing/contracts",
  "assets/fonts",
  "assets/models",
  "assets/music",
  "assets/sfx",
  "src/app/api/producer/auto-edit",
  "src/app/api/producer/native-short",
  "src/app/api/producer/ai-edit",
  "src/app/api/producer/live-build",
  "src/app/api/producer/palmier",
  "src/app/api/_lib",
  "src/app/api/producer/studio/import/files.ts",
  "src/app/api/producer/studio/import/evidence.ts",
  "src/app/api/producer/studio/import/model.ts",
  "src/lib/debug.ts",
  "src/lib/producer",
  "src/lib/server",
  "package.json",
  "package-lock.json",
  "tsconfig.json",
  "next.config.ts",
] as const;

export interface CapturedPipelineFile extends PipelineAuthorityFile {
  bytes: Buffer;
}

function logicalPath(root: string, filePath: string): string {
  return path.relative(root, filePath).split(path.sep).join("/");
}

function excluded(relative: string): boolean {
  if (NEVER_CAPTURE.test(relative)) return true;
  if (EXCLUDED_PREFIXES.some((prefix) => relative.startsWith(prefix))) return true;
  return relative.split("/").some((part) => EXCLUDED_PARTS.has(part));
}

function captureable(relative: string): boolean {
  if (REQUIRED_HASHES.has(relative)) return true;
  if (relative.startsWith("assets/")) return ASSET_EXTENSIONS.test(relative)
    || SOURCE_EXTENSIONS.test(relative);
  return SOURCE_EXTENSIONS.test(relative);
}

function walk(root: string, item: string): string[] {
  if (!existsSync(item)) return [];
  const relative = logicalPath(root, item);
  if (excluded(relative)) return [];
  const stat = lstatSync(item);
  if (stat.isSymbolicLink()) return [];
  if (stat.isFile()) return captureable(relative) ? [item] : [];
  if (!stat.isDirectory()) return [];
  return readdirSync(item).sort().flatMap((name) => walk(root, path.join(item, name)));
}

function bytesHash(bytes: Buffer): string {
  return createHash("sha256").update(bytes).digest("hex");
}

function assertRequiredSources(root: string): void {
  for (const relative of SOURCE_PATHS) {
    const source = path.join(root, ...relative.split("/"));
    if (!existsSync(source) || lstatSync(source).isSymbolicLink()) {
      throw new Error(`Required Producer pipeline source is missing: ${relative}`);
    }
  }
}

/** Require the runtime data/preloads that source-only extension scans can miss. */
export function assertPipelineAssetClosure(
  files: readonly PipelineAuthorityFile[],
): void {
  const present = new Map(files.map((row) => [row.path, row.hash]));
  for (const required of REQUIRED_FILES) {
    if (!present.has(required)) {
      throw new Error(`Required Producer pipeline asset is missing: ${required}`);
    }
  }
  for (const prefix of REQUIRED_PREFIXES) {
    if (![...present.keys()].some((relative) => relative.startsWith(prefix))) {
      throw new Error(`Required Producer pipeline asset set is empty: ${prefix}`);
    }
  }
  for (const [required, expectedHash] of REQUIRED_HASHES) {
    const actualHash = present.get(required);
    if (!actualHash) throw new Error(`Required Producer pipeline asset is missing: ${required}`);
    if (actualHash !== expectedHash) {
      throw new Error(`Required Producer pipeline asset failed verification: ${required}`);
    }
  }
}

/** Capture the closed repository-owned code, contracts, schemas, and render assets. */
export function capturePipelineAssets(root: string): CapturedPipelineFile[] {
  assertRequiredSources(root);
  const paths = [...new Set(SOURCE_PATHS.flatMap((relative) =>
    walk(root, path.join(root, ...relative.split("/")))))].sort();
  const captured = paths.map((filePath) => {
    const bytes = readFileSync(filePath);
    return { path: logicalPath(root, filePath), hash: bytesHash(bytes), bytes };
  });
  assertPipelineAssetClosure(captured);
  return captured;
}
