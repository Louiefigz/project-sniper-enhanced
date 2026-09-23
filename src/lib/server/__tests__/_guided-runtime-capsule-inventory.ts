/** TEST-only additions to an independently held pipeline inventory; no second production capture policy. */
import { existsSync, lstatSync, realpathSync } from "node:fs";
import { builtinModules, createRequire } from "node:module";
import path from "node:path";
import ts from "typescript";
import { assertPipelineAssetClosure } from "../auto-edit-pipeline-assets";
import { PRODUCER_CORE_DOCTRINE_PATHS, PRODUCER_REFERENCED_DOCTRINE_PATHS } from "../auto-edit-doctrine";
import { assertFileIdentity, boundedBytes, canonicalDirectory, logicalPath, observeFile, SOURCE_BYTES,
  type CapsuleFile, type CapsuleGuard } from "./_guided-runtime-capsule-io";

export interface PipelineInventoryRow { path: string; hash: string }
export interface CapsuleSourceInventory { root: string; pipeline: PipelineInventoryRow[]; files: CapsuleFile[]; totalBytes: number }
const SHA = /^[0-9a-f]{64}$/u, MAX_SOURCE_FILES = 20_000, SOURCE_FILE_BYTES = 64 * 1024 * 1024;
export const CAPSULE_ENTRYPOINTS = ["src/lib/server/__tests__/_guided-body-live-fixture.ts",
  "scripts/producer/guided-opening.ts", "scripts/producer/guided-body.ts"] as const;
const HARNESS_FILES = ["_guided-runtime-capsule.ts", "_guided-runtime-capsule-io.ts",
  "_guided-runtime-capsule-inventory.ts", "_guided-runtime-capsule-dependencies.ts",
  "_guided-runtime-capsule-python.ts", "_guided-runtime-capsule-owner.ts"]
  .map((name) => `src/lib/server/__tests__/${name}`);
// Includes conditional local imports; these remain TEST files, never production approval inputs.
const PYTHON_FIXTURE_FILES = ["_cut_preview_fixture.py", "_guided_body_audio.py", "_guided_body_program.py",
  "_guided_longform_program.py", "_guided_longform_check.py", "_guided_longform_treatment.py",
  "_guided_longform_treatment_check.py", "_ingest_admission_fixture.py"].map((name) => `scripts/producer/tests/${name}`);
const STYLE_DOCS = ["docs/studies/RESTRAINED_STYLE.md", "scripts/producer/docs/findings/PUNCH_STYLE.md", "docs/studies/SLIDEWARE_STYLE.md"];

function checkedPipeline(rows: PipelineInventoryRow[]): PipelineInventoryRow[] {
  if (!Array.isArray(rows) || rows.length < 1 || rows.length > MAX_SOURCE_FILES) throw new Error("TEST source inventory is unbounded");
  const seen = new Set<string>();
  for (const row of rows) {
    if (!row || Object.keys(row).sort().join(",") !== "hash,path" || typeof row.path !== "string"
        || typeof row.hash !== "string" || !SHA.test(row.hash) || seen.has(logicalPath(row.path))) {
      throw new Error("TEST pipeline inventory contains malformed/duplicate rows");
    }
    seen.add(row.path);
  }
  assertPipelineAssetClosure(rows);
  return rows.map((row) => ({ ...row })).sort((left, right) => left.path < right.path ? -1 : 1);
}

function resolveImport(root: string, from: string, specifier: string): string | null {
  if (!specifier.startsWith(".") && !specifier.startsWith("@/")) {
    if (specifier.startsWith("node:") || builtinModules.includes(specifier)) return null;
    if (specifier.includes(":") || path.isAbsolute(specifier) || specifier.startsWith("#")) throw new Error("TEST runtime import uses unsupported resolution");
    const installed = realpathSync(path.join(root, "node_modules"));
    const resolved = realpathSync(createRequire(from).resolve(specifier));
    if (!resolved.startsWith(installed + path.sep)) throw new Error("TEST bare import escapes the complete held Node installation");
    // The complete installed dependency tree supplies this package; no package subset is selected here.
    return null;
  }
  const base = specifier.startsWith("@/") ? path.join(root, "src", specifier.slice(2)) : path.resolve(path.dirname(from), specifier);
  const resolved = ["", ".ts", ".tsx", ".js", ".mjs", ".cjs", ".json", "/index.ts", "/index.tsx", "/index.js"]
    .map((suffix) => base + suffix).find((file) => existsSync(file) && lstatSync(file).isFile());
  if (!resolved || !resolved.startsWith(root + path.sep)) throw new Error("TEST runtime import is missing or escapes its source root");
  return resolved;
}

/** Literal imports only. A newly introduced dynamic import/require requires an explicit reviewed inventory update. */
function imports(root: string, file: string, guard: CapsuleGuard): string[] {
  const bytes = boundedBytes(file, 2 * 1024 * 1024, guard).bytes;
  if (file.endsWith(".json")) return [];
  const source = ts.createSourceFile(file, new TextDecoder("utf-8", { fatal: true }).decode(bytes), ts.ScriptTarget.Latest, true);
  const result: string[] = [];
  const add = (name: string): void => { const resolved = resolveImport(root, file, name); if (resolved) result.push(resolved); };
  const visit = (node: ts.Node): void => {
    guard();
    if ((ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) && node.moduleSpecifier && ts.isStringLiteral(node.moduleSpecifier)) add(node.moduleSpecifier.text);
    if (ts.isCallExpression(node) && (node.expression.kind === ts.SyntaxKind.ImportKeyword
        || (ts.isIdentifier(node.expression) && node.expression.text === "require"))) {
      if (node.arguments.length !== 1 || !ts.isStringLiteral(node.arguments[0])) throw new Error("TEST runtime has an unenumerated dynamic import");
      add(node.arguments[0].text);
    }
    ts.forEachChild(node, visit);
  };
  visit(source); return result;
}

function fixtureClosure(root: string, guard: CapsuleGuard): string[] {
  const pending = [...CAPSULE_ENTRYPOINTS, ...HARNESS_FILES].map((file) => path.join(root, file)), seen = new Set<string>();
  while (pending.length) {
    const file = pending.pop()!;
    if (seen.has(file)) continue;
    seen.add(file);
    if (seen.size > 4096) throw new Error("TEST runtime import closure is too large");
    pending.push(...imports(root, file, guard));
  }
  return [...seen].map((file) => logicalPath(path.relative(root, file)));
}

function sourceFiles(root: string, names: string[], guard: CapsuleGuard): CapsuleFile[] {
  let bytes = 0;
  const sizes = names.map((name) => {
    guard(); const file = path.join(root, logicalPath(name)), info = lstatSync(file);
    bytes += info.size;
    if (!info.isFile() || info.isSymbolicLink() || info.nlink !== 1 || info.size < 1
        || info.size > SOURCE_FILE_BYTES || bytes > SOURCE_BYTES) throw new Error("TEST source inventory exceeds regular-file/byte policy");
    return { file, size: info.size };
  });
  return sizes.map(({ file, size }) => observeFile(file, size, guard));
}

/** The caller independently holds this existing production inventory; this does not mint a run/job authority. */
export function captureCapsuleSources(root: string, pipeline: PipelineInventoryRow[], guard: CapsuleGuard): CapsuleSourceInventory {
  guard(); canonicalDirectory(root); const held = checkedPipeline(pipeline);
  const names = [...new Set([...held.map((row) => row.path), ...fixtureClosure(root, guard), ...HARNESS_FILES,
    ...PYTHON_FIXTURE_FILES, ...PRODUCER_CORE_DOCTRINE_PATHS, ...PRODUCER_REFERENCED_DOCTRINE_PATHS, ...STYLE_DOCS])].sort();
  if (names.length > MAX_SOURCE_FILES) throw new Error("TEST complete source inventory is too large");
  const files = sourceFiles(root, names, guard), byPath = new Map(files.map((row) => [path.relative(root, row.path), row.sha256]));
  if (held.some((row) => byPath.get(row.path) !== row.hash)) throw new Error("TEST held pipeline inventory is stale at capture");
  for (const row of files) assertFileIdentity(row, guard);
  guard(); return { root, pipeline: held, files, totalBytes: files.reduce((sum, row) => sum + row.sizeBytes, 0) };
}

export function verifyCapsuleSources(expected: CapsuleSourceInventory, guard: CapsuleGuard): void {
  const actual = captureCapsuleSources(expected.root, expected.pipeline, guard);
  if (JSON.stringify(actual) !== JSON.stringify(expected)) throw new Error("TEST source or fixture/doctrine closure changed");
  guard();
}
