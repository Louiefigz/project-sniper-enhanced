/** TEST-only bounded static project TS imports; not native, package, dynamic-import or execution qualification. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import ts from "typescript";

export const SOURCE_COLOR_CLEANUP_ROOTS = ["src/lib/server/guided-source-color-cleanup-workflow.ts",
  "src/lib/server/guided-source-color-cleanup-recovery.ts", "src/lib/server/guided-source-color-cleanup-final-read.ts",
  "src/lib/server/guided-opening-cleanup.ts", "src/lib/server/guided-source-color-readback.ts",
  "src/lib/server/guided-source-color-readback-history.ts", "src/lib/server/guided-source-color-approval.ts",
  "src/lib/server/guided-source-color-approval-read.ts", "src/lib/server/guided-body-authority.ts",
  "src/lib/server/guided-body-lineage.ts",
  "src/lib/server/guided-opening-controller.ts", "scripts/producer/guided-opening.ts", "scripts/producer/guided-body.ts"];
const MAX_FILES = 512;
const MAX_FILE_BYTES = 2 * 1024 * 1024;
const MAX_SOURCE_BYTES = 32 * 1024 * 1024;

/** Declaration-level and named-only type imports/exports do not execute. External packages are out of scope. */
export function staticProjectSpecifiers(source: string): string[] {
  const ast = ts.createSourceFile("TEST.ts", source, ts.ScriptTarget.Latest, true), output: string[] = [];
  for (const item of ast.statements) {
    if (!ts.isImportDeclaration(item) && !ts.isExportDeclaration(item)) continue;
    if (!item.moduleSpecifier || !ts.isStringLiteral(item.moduleSpecifier)) continue;
    if (ts.isImportDeclaration(item) && item.importClause?.isTypeOnly || ts.isExportDeclaration(item) && item.isTypeOnly) continue;
    const names = ts.isImportDeclaration(item) ? item.importClause?.namedBindings : item.exportClause;
    const members = names && (ts.isNamedImports(names) || ts.isNamedExports(names)) ? names.elements : undefined;
    if (members?.length && members.every(member => member.isTypeOnly) && !(ts.isImportDeclaration(item) && item.importClause?.name)) continue;
    const value = item.moduleSpecifier.text;
    if (value.startsWith("@/") || value.startsWith(".")) output.push(value);
  }
  return output;
}

/** Resolve only existing project TS targets, retaining normal .ts/.tsx/index resolution order. */
function resolveProjectTs(file: string, specifier: string): string | null {
  const target = specifier.startsWith("@/") ? `src/${specifier.slice(2)}` : path.normalize(path.join(path.dirname(file), specifier));
  assert(!path.isAbsolute(target) && !target.split(path.sep).includes(".."), `Project import escaped: ${specifier}`);
  const variants = path.extname(target) ? [target] : [target + ".ts", target + ".tsx", path.join(target, "index.ts"), path.join(target, "index.tsx")];
  const actual = variants.find(candidate => fs.existsSync(candidate)); assert(actual, `Unresolved project import ${file} -> ${specifier}`);
  return /\.tsx?$/.test(actual) ? actual.split(path.sep).join("/") : null;
}

/** Fresh uncached read of <=512 TS files and <=32MiB; no evaluating imports or modifying project bytes. */
export function sourceColorStaticImportClosure(): string[] {
  const pending = [...SOURCE_COLOR_CLEANUP_ROOTS], seen = new Set<string>(); let bytes = 0;
  while (pending.length) {
    const file = pending.pop()!; if (seen.has(file)) continue;
    seen.add(file); assert(seen.size <= MAX_FILES, "Static TS closure exceeds TEST bound");
    const absolute = path.join(process.cwd(), file), info = fs.lstatSync(absolute);
    assert(info.isFile() && !info.isSymbolicLink()); assert.equal(fs.realpathSync(absolute), absolute);
    assert(info.size <= MAX_FILE_BYTES); bytes += info.size; assert(bytes <= MAX_SOURCE_BYTES);
    const source = new TextDecoder("utf-8", { fatal: true }).decode(fs.readFileSync(absolute));
    const children = staticProjectSpecifiers(source).map(specifier => resolveProjectTs(file, specifier));
    pending.push(...children.filter((child): child is string => child !== null));
  }
  return [...seen].sort();
}
