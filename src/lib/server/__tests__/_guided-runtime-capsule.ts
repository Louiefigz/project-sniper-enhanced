/** TEST-only runtime capsule construction/verification. No child launch, project adoption, or approval. */
import { chmodSync, closeSync, fsyncSync, lstatSync, mkdirSync, openSync, readdirSync, readlinkSync, realpathSync, symlinkSync } from "node:fs";
import path from "node:path";
import { captureCapsuleSources, verifyCapsuleSources, type CapsuleSourceInventory, type PipelineInventoryRow } from "./_guided-runtime-capsule-inventory";
import { captureDependencies, verifyDependencies, type DependencyInventory, type DependencyRoots, type CapsuleTools } from "./_guided-runtime-capsule-dependencies";
import { assertFileIdentity, boundedBytes, byteHash, canonicalDirectory, copyFileHeld, logicalPath, observeFile, SOURCE_BYTES, writeNewBytes,
  type CapsuleFile, type CapsuleGuard } from "./_guided-runtime-capsule-io";

const RECEIPT_LIMIT = 128 * 1024 * 1024, BUILD_LIMIT_MS = 300_000;
const SCOPE = "TEST-only-exact-runtime-version-not-current-checkout-or-creator-approval";
interface CapsuleInput {
  destination: string; source: { root: string; pipeline: PipelineInventoryRow[] };
  dependencies: { roots: DependencyRoots; tools: CapsuleTools };
}
export interface CapsuleReceipt {
  schemaVersion: 1; kind: "TEST-guided-runtime-capsule"; scope: typeof SCOPE; root: string;
  source: CapsuleSourceInventory; dependencies: DependencyInventory; files: CapsuleFile[];
  links: Array<{ path: string; target: string }>; createdAt: string;
  qualification: "not-run"; originalDriverModified: false; sourceMutationPermission: false;
}
export interface HeldCapsule { receiptPath: string; receiptSha256: string; root: string }

function boundedGuard(parent: CapsuleGuard): CapsuleGuard {
  const began = performance.now();
  return () => { parent(); if (performance.now() - began >= BUILD_LIMIT_MS) throw new Error("TEST capsule original build/verification deadline expired"); };
}

function outside(file: string, root: string): boolean {
  return file !== root && !file.startsWith(root + path.sep) && !root.startsWith(file + path.sep);
}

function destination(input: CapsuleInput): string {
  const parent = canonicalDirectory(path.dirname(input.destination));
  if (path.join(parent, path.basename(input.destination)) !== input.destination
      || !/^[a-zA-Z0-9][a-zA-Z0-9._-]{0,95}$/u.test(path.basename(input.destination))) throw new Error("TEST capsule destination is not canonical");
  for (const original of [canonicalDirectory(input.source.root), ...Object.values(input.dependencies.roots)]) {
    if (!outside(input.destination, canonicalDirectory(original))) throw new Error("TEST capsule cannot overlap source/dependency trees");
  }
  mkdirSync(input.destination, { mode: 0o700 }); // Existing, partial, or completed capsule always refuses replay.
  const root = path.join(input.destination, "repo"); mkdirSync(root, { mode: 0o700 }); return root;
}

function assertDependencyLayout(root: string, deps: DependencyInventory, guard: CapsuleGuard): void {
  const expected = { nodeModules: path.join(root, "node_modules"), motionNodeModules: path.join(root, "templates/motion/node_modules") };
  for (const key of ["nodeModules", "motionNodeModules"] as const) {
    if (realpathSync(expected[key]) !== deps.roots[key]) throw new Error("TEST installed dependency does not belong to the selected checkout");
  }
  const venv = deps.roots.venv, config = boundedBytes(path.join(venv, "pyvenv.cfg"), 64 * 1024, guard).bytes.toString("utf8");
  const version = /^version\s*=\s*(\d+\.\d+)\.\d+\s*$/mu.exec(config)?.[1];
  if (!version || realpathSync(path.join(venv, "bin/python3")) !== deps.tools.python
      || !deps.tools.python.startsWith(deps.roots.pythonBase + path.sep)
      || !lstatSync(path.join(deps.roots.pythonBase, `lib/python${version}`)).isDirectory()
      || realpathSync(path.join(deps.roots.pythonBase, `lib/python${version}/site-packages`)) !== deps.roots.pythonBaseSitePackages
      || !lstatSync(path.join(venv, `lib/python${version}/site-packages`)).isDirectory()) {
    throw new Error("TEST Python base/venv layout is unsupported; never infer a package fallback");
  }
}

/** Low-level copying is independently testable with inert TEST files, never a production inventory override. */
export function materializeCapsuleSources(source: CapsuleSourceInventory, root: string, guard: CapsuleGuard): CapsuleFile[] {
  canonicalDirectory(root);
  if (readdirSync(root).length) throw new Error("TEST capsule source destination must be new and empty");
  const copied: CapsuleFile[] = [];
  for (const row of source.files) {
    guard(); const relative = logicalPath(path.relative(source.root, row.path)), target = path.join(root, relative);
    if (relative === "node_modules" || relative.startsWith("node_modules/") || relative.includes("/node_modules/")) throw new Error("TEST source inventory cannot masquerade as dependencies");
    mkdirSync(path.dirname(target), { recursive: true, mode: 0o700 });
    copied.push(copyFileHeld(row, target, guard));
  }
  guard(); return copied;
}

function dependencyLinks(root: string, dependencies: DependencyInventory, guard: CapsuleGuard): CapsuleReceipt["links"] {
  const rows = [{ path: path.join(root, "node_modules"), target: dependencies.roots.nodeModules },
    { path: path.join(root, "templates/motion/node_modules"), target: dependencies.roots.motionNodeModules }];
  for (const row of rows) {
    guard(); canonicalDirectory(path.dirname(row.path)); symlinkSync(row.target, row.path, "dir");
  }
  guard(); return rows;
}

function sealDirectories(root: string, guard: CapsuleGuard): void {
  guard(); const pending = [root], directories: string[] = [];
  while (pending.length) {
    const current = pending.pop()!; directories.push(current); guard();
    pending.push(...readdirSync(current).map((name) => path.join(current, name)).filter((file) => lstatSync(file).isDirectory()));
  }
  for (const directory of directories.reverse()) {
    guard(); const fd = openSync(directory, "r");
    try { fsyncSync(fd); } finally { closeSync(fd); }
    chmodSync(directory, 0o500);
  }
  guard();
}

/** Consumes held source rows; the untouched driver later performs its own real NEW pipeline capture. */
export function buildTestRuntimeCapsule(input: CapsuleInput, parentGuard: CapsuleGuard = () => {}): HeldCapsule {
  const guard = boundedGuard(parentGuard), began = performance.now(); guard();
  const root = destination(input), marker = path.join(input.destination, "BUILDING.json");
  writeNewBytes(marker, Buffer.from(JSON.stringify({ scope: SCOPE, startedAt: new Date().toISOString(), automaticRetry: false })), guard);
  const source = captureCapsuleSources(input.source.root, input.source.pipeline, guard), sourceMs = performance.now() - began;
  const dependencies = captureDependencies(input.dependencies.roots, input.dependencies.tools, guard);
  assertDependencyLayout(source.root, dependencies, guard); const dependenciesMs = performance.now() - began - sourceMs;
  const files = materializeCapsuleSources(source, root, guard), links = dependencyLinks(root, dependencies, guard);
  verifyCapsuleSources(source, guard); verifyDependencies(dependencies, guard);
  const receipt: CapsuleReceipt = { schemaVersion: 1, kind: "TEST-guided-runtime-capsule", scope: SCOPE, root, source,
    dependencies, files, links, createdAt: new Date().toISOString(), qualification: "not-run",
    originalDriverModified: false, sourceMutationPermission: false };
  verifyCopiedFiles(receipt, guard); sealDirectories(root, guard);
  const receiptPath = path.join(input.destination, "capsule.json"), bytes = Buffer.from(JSON.stringify(receipt));
  if (bytes.length > RECEIPT_LIMIT) throw new Error("TEST capsule receipt exceeds its byte bound");
  guard(); writeNewBytes(receiptPath, bytes, guard);
  writeNewBytes(path.join(input.destination, "BUILD-COST.json"), Buffer.from(JSON.stringify({ sourceMs, dependenciesMs,
    totalMs: performance.now() - began, includesCopyAndBothFinalChecks: true, mediaWork: false })), guard);
  guard(); return { receiptPath, receiptSha256: byteHash(bytes), root };
}

function verifyCopiedFiles(receipt: CapsuleReceipt, guard: CapsuleGuard): void {
  if (receipt.files.length !== receipt.source.files.length || receipt.files.length > 20_000
      || receipt.source.totalBytes > SOURCE_BYTES) throw new Error("TEST capsule source cardinality is invalid");
  const expected = new Map(receipt.files.map((row) => [row.path, row]));
  if (expected.size !== receipt.files.length) throw new Error("TEST capsule contains duplicate source refs");
  receipt.source.files.forEach((original, index) => {
    const row = receipt.files[index], relative = logicalPath(path.relative(receipt.source.root, original.path));
    if (row.path !== path.join(receipt.root, relative) || row.sha256 !== original.sha256 || row.sizeBytes !== original.sizeBytes) throw new Error("TEST capsule source projection changed");
    const actual = observeFile(row.path, Math.max(1, row.sizeBytes), guard);
    if (JSON.stringify(actual) !== JSON.stringify(row)) throw new Error("TEST capsule copied source changed");
  });
  const links = new Map(receipt.links.map((row) => [row.path, row.target])), pending = [receipt.root]; let entries = 0;
  for (const [file, target] of links) {
    guard();
    if (!lstatSync(file).isSymbolicLink() || readlinkSync(file) !== target || realpathSync(file) !== target) throw new Error("TEST capsule dependency link changed or disappeared");
  }
  while (pending.length) {
    guard(); const current = pending.pop()!; canonicalDirectory(current);
    for (const name of readdirSync(current)) inspectCopiedEntry(path.join(current, name), { expected, links, pending });
    entries += readdirSync(current).length;
    if (entries > 50_000) throw new Error("TEST capsule directory inventory exceeds its bound");
  }
  guard();
}

function inspectCopiedEntry(file: string, state: { expected: Map<string, CapsuleFile>; links: Map<string, string>; pending: string[] }): void {
  const info = lstatSync(file);
  if (info.isSymbolicLink()) {
    if (state.links.get(file) !== realpathSync(file)) throw new Error("TEST capsule has an unexpected source/dependency link");
    return;
  }
  if (info.isDirectory()) { state.pending.push(file); return; }
  if (!info.isFile() || info.nlink !== 1 || !state.expected.has(file)) throw new Error("TEST capsule has an extra or aliased source file");
}

/** This raw reference must be retained by the launcher before any child; it is TEST provenance, not approval. */
export function verifyTestRuntimeCapsule(held: HeldCapsule, parentGuard: CapsuleGuard = () => {}): CapsuleReceipt {
  const guard = boundedGuard(parentGuard), actual = boundedBytes(held.receiptPath, RECEIPT_LIMIT, guard);
  if (actual.file.sha256 !== held.receiptSha256) throw new Error("TEST capsule receipt bytes changed");
  const receipt = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(actual.bytes)) as CapsuleReceipt;
  if (receipt.schemaVersion !== 1 || receipt.kind !== "TEST-guided-runtime-capsule" || receipt.scope !== SCOPE
      || receipt.root !== held.root || receipt.root !== path.join(path.dirname(held.receiptPath), "repo")
      || receipt.qualification !== "not-run" || receipt.originalDriverModified !== false || receipt.sourceMutationPermission !== false) {
    throw new Error("TEST capsule receipt identity is unsupported");
  }
  const expectedLinks = [{ path: path.join(receipt.root, "node_modules"), target: receipt.dependencies.roots.nodeModules },
    { path: path.join(receipt.root, "templates/motion/node_modules"), target: receipt.dependencies.roots.motionNodeModules }];
  if (JSON.stringify(receipt.links) !== JSON.stringify(expectedLinks)) throw new Error("TEST capsule dependency projection changed");
  verifyCopiedFiles(receipt, guard); verifyDependencies(receipt.dependencies, guard);
  for (const row of receipt.files) assertFileIdentity(row, guard);
  if (observeFile(held.receiptPath, RECEIPT_LIMIT, guard).sha256 !== held.receiptSha256) throw new Error("TEST capsule receipt changed during verification");
  guard(); return receipt;
}

/** No process launch here. Caller must keep the same held capsule through every final readback/cleanup. */
export function capsuleInvocation(held: HeldCapsule, guard: CapsuleGuard = () => {}) {
  const receipt = verifyTestRuntimeCapsule(held, guard);
  const tools = receipt.dependencies.tools;
  const toolPath = [...new Set([...Object.values(tools).map((file) => path.dirname(file)), "/usr/bin", "/bin"])].join(path.delimiter);
  return { cwd: receipt.root, node: receipt.dependencies.tools.node, env: {
    SNIPER_RUNTIME_REPO_ROOT: receipt.root, SNIPER_PYTHON_VENV_ROOT: receipt.dependencies.roots.venv,
    SNIPER_NODE_PATH: tools.node, HYPERFRAMES_BROWSER_PATH: tools.browser,
    HYPERFRAMES_FFMPEG_PATH: tools.ffmpeg, HYPERFRAMES_FFPROBE_PATH: tools.ffprobe, SNIPER_DOCKER_PATH: tools.docker,
    PATH: toolPath,
    TSX_TSCONFIG_PATH: path.join(receipt.root, "tsconfig.json"),
    TSX_DISABLE_CACHE: "1", PYTHONDONTWRITEBYTECODE: "1", PYTHONNOUSERSITE: "1",
    SNIPER_PIPELINE_ROOT: undefined, PYTHONPATH: undefined, PYTHONHOME: undefined, NODE_PATH: undefined, NODE_OPTIONS: undefined,
    PYTHONSTARTUP: undefined, PYTHONUSERBASE: undefined, PYTHONEXECUTABLE: undefined, __PYVENV_LAUNCHER__: undefined,
    PYTHONINSPECT: undefined, PYTHONPLATLIBDIR: undefined, PYTHONPYCACHEPREFIX: undefined,
    LD_PRELOAD: undefined, LD_LIBRARY_PATH: undefined, DYLD_INSERT_LIBRARIES: undefined,
    DYLD_LIBRARY_PATH: undefined, DYLD_FRAMEWORK_PATH: undefined, DYLD_FALLBACK_LIBRARY_PATH: undefined,
    DYLD_FALLBACK_FRAMEWORK_PATH: undefined,
  } };
}
