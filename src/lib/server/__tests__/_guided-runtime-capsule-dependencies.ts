/** TEST-only complete installed-tree closure. Never installs packages or traverses undeclared link targets. */
import { lstatSync, readdirSync, readlinkSync, realpathSync } from "node:fs";
import path from "node:path";
import { assertFileIdentity, canonicalDirectory, FILE_BYTES, observeFile, type CapsuleFile, type CapsuleGuard } from "./_guided-runtime-capsule-io";

export const DEPENDENCY_ROLES = ["nodeModules", "motionNodeModules", "venv", "pythonBase", "pythonBaseSitePackages"] as const;
export const TOOL_ROLES = ["node", "python", "ffmpeg", "ffprobe", "browser", "docker", "fcMatch", "fcQuery"] as const;
export type DependencyRoots = Record<typeof DEPENDENCY_ROLES[number], string>;
export type CapsuleTools = Record<typeof TOOL_ROLES[number], string>;
export interface DependencyLink { path: string; target: string; resolved: string }
export interface DependencyDirectory { path: string; entries: string[] }
export interface DependencyInventory {
  roots: DependencyRoots; tools: CapsuleTools; files: CapsuleFile[];
  directories: DependencyDirectory[]; links: DependencyLink[]; totalBytes: number;
}
const MAX_ENTRIES = 300_000, MAX_BYTES = 32 * 1024 * 1024 * 1024;

function beneath(file: string, root: string): boolean {
  return file === root || file.startsWith(root + path.sep);
}

function requireRoles(value: Record<string, string>, roles: readonly string[]): void {
  if (!value || Object.keys(value).sort().join("\0") !== [...roles].sort().join("\0")
      || roles.some((role) => typeof value[role] !== "string")) throw new Error("TEST dependency role set is not closed");
}

function controls(roots: DependencyRoots, tools: CapsuleTools): void {
  requireRoles(roots, DEPENDENCY_ROLES); requireRoles(tools, TOOL_ROLES);
  const values = Object.values(roots).map(canonicalDirectory);
  if (values.some((root, index) => values.some((other, at) => at !== index && beneath(root, other)))) {
    throw new Error("TEST dependency roots overlap or alias");
  }
  for (const file of Object.values(tools)) {
    if (!path.isAbsolute(file) || realpathSync(file) !== file || !lstatSync(file).isFile()) {
      throw new Error("TEST tool reference is not a canonical regular file");
    }
  }
}

function assertLinkAllowed(file: string, roots: DependencyRoots, tools: CapsuleTools): void {
  if (![...Object.values(roots)].some((root) => beneath(file, root)) && !Object.values(tools).includes(file)) {
    throw new Error("TEST installed dependency link escapes its complete declared roots/tools");
  }
}

interface WalkState { result: DependencyInventory; pending: string[]; seen: Set<string>; guard: CapsuleGuard }

function visitLink(file: string, state: WalkState): void {
  const target = readlinkSync(file), resolved = realpathSync(file);
  assertLinkAllowed(resolved, state.result.roots, state.result.tools);
  state.result.links.push({ path: file, target, resolved });
  // Its resolved file/tree is inventoried through its declared root/tool, never an arbitrary expansion.
}

function visitEntry(file: string, state: WalkState): void {
  state.guard();
  if (state.seen.has(file)) return;
  state.seen.add(file);
  if (state.seen.size > MAX_ENTRIES) throw new Error("TEST installed dependency entry bound exceeded");
  const info = lstatSync(file);
  if (info.isSymbolicLink()) return visitLink(file, state);
  if (info.isDirectory()) {
    const entries = readdirSync(file).sort();
    if (entries.length + state.seen.size + state.pending.length > MAX_ENTRIES) throw new Error("TEST dependency directory is too large");
    state.result.directories.push({ path: file, entries });
    state.pending.push(...entries.map((name) => path.join(file, name))); return;
  }
  if (!info.isFile()) throw new Error("TEST dependency tree includes unsupported special file");
  state.result.totalBytes += info.size;
  if (state.result.totalBytes > MAX_BYTES) throw new Error("TEST installed dependency byte bound exceeded");
  state.result.files.push(observeFile(file, FILE_BYTES, state.guard));
}

function assertTreeShape(result: DependencyInventory, guard: CapsuleGuard): void {
  for (const row of result.directories) {
    guard(); canonicalDirectory(row.path);
    if (JSON.stringify(readdirSync(row.path).sort()) !== JSON.stringify(row.entries)) throw new Error("TEST installed directory changed");
  }
  for (const row of result.links) {
    guard();
    if (!lstatSync(row.path).isSymbolicLink() || readlinkSync(row.path) !== row.target || realpathSync(row.path) !== row.resolved) {
      throw new Error("TEST installed dependency link changed");
    }
  }
  for (const row of result.files) assertFileIdentity(row, guard);
  guard();
}

/** Includes every regular file, directory entry and link, not package-name/framework guesses. */
export function captureDependencies(roots: DependencyRoots, tools: CapsuleTools, guard: CapsuleGuard): DependencyInventory {
  guard(); controls(roots, tools);
  const result: DependencyInventory = { roots: { ...roots }, tools: { ...tools }, files: [], directories: [], links: [], totalBytes: 0 };
  const state: WalkState = { result, pending: [...Object.values(roots), ...Object.values(tools)], seen: new Set(), guard };
  while (state.pending.length) visitEntry(state.pending.pop()!, state);
  for (const rows of [result.files, result.directories, result.links]) rows.sort((left, right) => left.path < right.path ? -1 : left.path > right.path ? 1 : 0);
  assertTreeShape(result, guard);
  return result;
}

/** Full byte recheck is admission/final verification cost, never run once per UI status poll. */
export function verifyDependencies(expected: DependencyInventory, guard: CapsuleGuard): void {
  const actual = captureDependencies(expected.roots, expected.tools, guard);
  if (JSON.stringify(actual) !== JSON.stringify(expected)) throw new Error("TEST installed dependency closure changed");
  guard();
}
