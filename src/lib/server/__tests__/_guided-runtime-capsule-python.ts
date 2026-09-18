/** TEST-only Python startup observation; never replaces the complete installed dependency byte closure. */
import { lstatSync, readdirSync, realpathSync } from "node:fs";
import path from "node:path";
import { runCutPreviewProcess } from "../../../app/api/producer/auto-edit/cut-preview-process";
import type { DependencyInventory } from "./_guided-runtime-capsule-dependencies";
import { boundedBytes, canonicalDirectory, observeFile, type CapsuleFile, type CapsuleGuard } from "./_guided-runtime-capsule-io";

const OUTPUT_LIMIT = 32 * 1024, PROBE_LIMIT_MS = 10_000;
const METADATA = `import json, os, site, sys
def resolved(value):
    return os.path.realpath(value)
def customizer(name):
    module = sys.modules.get(name)
    return None if module is None else resolved(getattr(module, '__file__', '<unknown>'))
print(json.dumps(dict(
    version='.'.join(map(str, sys.version_info[:3])),
    prefix=resolved(sys.prefix), execPrefix=resolved(sys.exec_prefix),
    basePrefix=resolved(sys.base_prefix), baseExecPrefix=resolved(sys.base_exec_prefix),
    executable=resolved(sys.executable), paths=[resolved(p) for p in sys.path],
    sitePackages=[resolved(p) for p in site.getsitepackages()],
    userSite=site.ENABLE_USER_SITE, sitecustomize=customizer('sitecustomize'),
    usercustomize=customizer('usercustomize'), isolated=sys.flags.isolated,
    noUserSite=sys.flags.no_user_site, safePath=sys.flags.safe_path,
    dontWriteBytecode=sys.dont_write_bytecode), sort_keys=True))`;

export interface CapsulePythonInput {
  dependencies: DependencyInventory; cwd: string; env: NodeJS.ProcessEnv;
  /** Original caller-owned performance.now() deadline, shared by build/prelaunch/final as appropriate. */
  expiresAt: number; signal?: AbortSignal;
}
interface PythonMetadata {
  version: string; prefix: string; execPrefix: string; basePrefix: string; baseExecPrefix: string;
  executable: string; paths: string[]; sitePackages: string[]; userSite: false;
  sitecustomize: string | null; usercustomize: null;
  isolated: 1; noUserSite: 1; safePath: true; dontWriteBytecode: true;
}
export interface CapsulePythonStartup {
  schemaVersion: 1; kind: "TEST-capsule-python-startup"; metadata: PythonMetadata;
  config: CapsuleFile; customizers: CapsuleFile[]; absentZip: string;
}
interface Layout { config: CapsuleFile; version: string; stdlib: string; site: string; zip: string; command: string }

function originalGuard(input: CapsulePythonInput, guard: CapsuleGuard): CapsuleGuard {
  return () => {
    guard();
    if (!Number.isFinite(input.expiresAt) || input.signal?.aborted || performance.now() >= input.expiresAt) {
      throw new Error("TEST Python startup original deadline expired or was cancelled");
    }
  };
}

function heldFile(input: CapsulePythonInput, file: string, guard: CapsuleGuard, limit = 1024 * 1024 * 1024): CapsuleFile {
  const expected = input.dependencies.files.find((row) => row.path === file);
  if (!expected) throw new Error("TEST Python startup file is outside the held inventory");
  const actual = observeFile(file, Math.min(limit, Math.max(1, expected.sizeBytes)), guard);
  if (JSON.stringify(actual) !== JSON.stringify(expected)) throw new Error("TEST Python startup held bytes changed");
  return actual;
}

function configValue(source: string, key: string): string {
  const rows = source.split(/\r?\n/u).filter((line) => line.split("=", 1)[0].trim().toLowerCase() === key);
  if (rows.length !== 1) throw new Error("TEST Python configuration is missing or ambiguous");
  return rows[0].slice(rows[0].indexOf("=") + 1).trim();
}

function layout(input: CapsulePythonInput, guard: CapsuleGuard): Layout {
  const { roots, tools } = input.dependencies;
  canonicalDirectory(input.cwd); canonicalDirectory(roots.venv); canonicalDirectory(roots.pythonBase);
  const configPath = path.join(roots.venv, "pyvenv.cfg"), config = heldFile(input, configPath, guard, 64 * 1024);
  const observed = boundedBytes(configPath, 64 * 1024, guard);
  if (JSON.stringify(observed.file) !== JSON.stringify(config)) throw new Error("TEST Python configuration changed");
  const text = new TextDecoder("utf-8", { fatal: true }).decode(observed.bytes), version = configValue(text, "version");
  if (!/^3\.\d{1,2}\.\d{1,3}$/u.test(version) || configValue(text, "include-system-site-packages") !== "false") {
    throw new Error("TEST Python requires an explicit isolated venv configuration");
  }
  const minor = version.split(".").slice(0, 2).join("."), stdlib = path.join(roots.pythonBase, `lib/python${minor}`);
  const site = path.join(roots.venv, `lib/python${minor}/site-packages`), command = path.join(roots.venv, "bin/python3");
  canonicalDirectory(stdlib); canonicalDirectory(site); canonicalDirectory(path.join(stdlib, "lib-dynload"));
  if (realpathSync(command) !== tools.python || !tools.python.startsWith(roots.pythonBase + path.sep)
      || realpathSync(path.join(stdlib, "site-packages")) !== roots.pythonBaseSitePackages) {
    throw new Error("TEST Python executable/base-site-packages layout differs from held roles");
  }
  heldFile(input, tools.python, guard);
  return { config, version, stdlib, site, command, zip: path.join(roots.pythonBase, `lib/python${minor.replace(".", "")}.zip`) };
}

function requireMissingZip(file: string, guard: CapsuleGuard): void {
  guard(); canonicalDirectory(path.dirname(file));
  try { lstatSync(file); }
  catch (error) { if ((error as NodeJS.ErrnoException).code === "ENOENT") return; throw error; }
  throw new Error("TEST Python expected absent stdlib zip appeared; no implicit archive admission");
}

function requireNoPth(input: CapsulePythonInput, actual: Layout, guard: CapsuleGuard): void {
  const { roots, files, links } = input.dependencies;
  if ([...files, ...links].some((row) => row.path.startsWith(roots.venv + path.sep) && row.path.endsWith(".pth"))) {
    throw new Error("TEST Python venv .pth loaders are unsupported");
  }
  guard(); const names = readdirSync(actual.site);
  if (names.length > 300_000 || names.some((name) => name.endsWith(".pth"))) throw new Error("TEST Python venv .pth or entry bound changed");
  guard(); requireMissingZip(actual.zip, guard);
}

function startupFile(input: CapsulePythonInput, file: string, guard: CapsuleGuard): CapsuleFile {
  guard();
  if (path.basename(file).startsWith("usercustomize")) throw new Error("TEST Python user customizer is unsupported");
  return heldFile(input, file, guard, 1024 * 1024);
}

function startupNames(directory: string, guard: CapsuleGuard): string[] {
  guard(); let names: string[];
  try { canonicalDirectory(directory); names = readdirSync(directory); }
  catch (error) { if ((error as NodeJS.ErrnoException).code === "ENOENT") return []; throw error; }
  if (names.length > 300_000) throw new Error("TEST Python startup directory exceeds bound");
  return names.filter((name) => /^(?:sitecustomize|usercustomize)(?:\.|$)/u.test(name)).sort();
}

function startupFiles(input: CapsulePythonInput, actual: Layout, guard: CapsuleGuard): CapsuleFile[] {
  const directories = [actual.stdlib, actual.site, path.join(actual.stdlib, "__pycache__"), path.join(actual.site, "__pycache__")];
  const result: CapsuleFile[] = [];
  for (const directory of directories) {
    for (const name of startupNames(directory, guard)) {
      result.push(startupFile(input, path.join(directory, name), guard));
    }
  }
  guard(); return result;
}

function parseMetadata(stdout: string): PythonMetadata {
  if (Buffer.byteLength(stdout, "utf8") > OUTPUT_LIMIT) throw new Error("TEST Python startup output is oversized");
  const value = JSON.parse(stdout) as PythonMetadata;
  const keys = ["version", "prefix", "execPrefix", "basePrefix", "baseExecPrefix", "executable", "paths", "sitePackages",
    "userSite", "sitecustomize", "usercustomize", "isolated", "noUserSite", "safePath", "dontWriteBytecode"];
  if (!value || Array.isArray(value) || Object.keys(value).sort().join("\0") !== keys.sort().join("\0")
      || value.userSite !== false || value.usercustomize !== null || value.isolated !== 1 || value.noUserSite !== 1
      || value.safePath !== true || value.dontWriteBytecode !== true) throw new Error("TEST Python startup metadata is unsupported");
  return value;
}

function validateMetadata(input: CapsulePythonInput, actual: Layout, value: PythonMetadata): void {
  const { roots, tools } = input.dependencies;
  const expected = [actual.zip, actual.stdlib, path.join(actual.stdlib, "lib-dynload"), actual.site];
  if (value.version !== actual.version || value.prefix !== roots.venv || value.execPrefix !== roots.venv
      || value.basePrefix !== roots.pythonBase || value.baseExecPrefix !== roots.pythonBase || value.executable !== tools.python
      || JSON.stringify(value.paths) !== JSON.stringify(expected) || JSON.stringify(value.sitePackages) !== JSON.stringify([actual.site])) {
    throw new Error("TEST Python startup has unknown runtime paths, prefixes, or binary");
  }
}

function customizers(input: CapsulePythonInput, actual: Layout, value: PythonMetadata, guard: CapsuleGuard): CapsuleFile[] {
  if (value.sitecustomize === null) return [];
  const allowed = [path.join(actual.stdlib, "sitecustomize.py"), path.join(actual.site, "sitecustomize.py")];
  if (!allowed.includes(value.sitecustomize)) throw new Error("TEST Python startup customizer is unsupported");
  return [heldFile(input, value.sitecustomize, guard)];
}

/** Same installed venv/env/cwd; one bounded owned metadata process, no provider or media invocation.
 * Caller retains/compares this result at build, prelaunch and final, alongside complete byte rechecks.
 * An -I observation proves startup roots only; production script/source imports remain independently held.
 */
export async function observeCapsulePythonStartup(input: CapsulePythonInput, parentGuard: CapsuleGuard,
  run: typeof runCutPreviewProcess = runCutPreviewProcess): Promise<CapsulePythonStartup> {
  const guard = originalGuard(input, parentGuard); guard();
  const actual = layout(input, guard); requireNoPth(input, actual, guard);
  const startup = startupFiles(input, actual, guard); guard();
  const timeoutMs = Math.floor(Math.min(PROBE_LIMIT_MS, input.expiresAt - performance.now()));
  if (timeoutMs < 1) throw new Error("TEST Python startup has no remaining original time");
  const output = await run({ command: actual.command, args: ["-I", "-B", "-c", METADATA], cwd: input.cwd,
    env: input.env, timeoutMs, signal: input.signal, trackForShutdown: true });
  guard();
  if (output.stderr) throw new Error("TEST Python startup emitted unexpected diagnostics");
  const metadata = parseMetadata(output.stdout); validateMetadata(input, actual, metadata);
  const observedCustomizers = customizers(input, actual, metadata, guard);
  const final = layout(input, guard); requireNoPth(input, final, guard);
  if (JSON.stringify(actual) !== JSON.stringify(final) || JSON.stringify(startupFiles(input, final, guard)) !== JSON.stringify(startup)) {
    throw new Error("TEST Python startup layout changed during observation");
  }
  guard(); return { schemaVersion: 1, kind: "TEST-capsule-python-startup", metadata, config: actual.config,
    customizers: observedCustomizers, absentZip: actual.zip };
}
