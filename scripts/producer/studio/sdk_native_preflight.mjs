/** Official SDK project lint, with no HTML execution, probes, writes or network. */
import fs from "node:fs";
import path from "node:path";
import { createHash } from "node:crypto";
import { pathToFileURL } from "node:url";
import { syncBuiltinESMExports } from "node:module";
import { attempts, forbidWork, forbidWrites } from "../graphics/comp_capability_lint.mjs";

const sha = data => createHash("sha256").update(data).digest("hex");

function requireValue(condition, message) {
  if (!condition) throw new Error(`Native static preflight: ${message}`);
}

function readRequest() {
  const [file, expected] = process.argv.slice(2);
  requireValue(path.isAbsolute(file ?? "") && /^[a-f0-9]{64}$/.test(expected ?? ""), "invalid request reference");
  const info = fs.lstatSync(file);
  requireValue(info.isFile() && !info.isSymbolicLink() && info.size <= 1024 * 1024, "invalid request file");
  const raw = fs.readFileSync(file);
  requireValue(sha(raw) === expected, "request bytes changed");
  const request = JSON.parse(raw);
  requireValue(request.schemaVersion === 1 && request.version === "0.8.31"
    && path.isAbsolute(request.project) && path.isAbsolute(request.packageRoot)
    && request.files && typeof request.files === "object", "invalid request shape");
  requireValue(Object.keys(request.files).length > 0 && Object.keys(request.files).length <= 512, "invalid file count");
  return { request, expected };
}

async function safeSources(request) {
  const { collectSubCompositionSrcs } = await import("@hyperframes/parsers/asset-resolution");
  for (const [relative, row] of Object.entries(request.files)) {
    const file = path.resolve(request.project, relative);
    requireValue(relative && !path.isAbsolute(relative) && file.startsWith(request.project + path.sep)
      && fs.realpathSync(file) === file && fs.lstatSync(file).isFile(), "source escapes project or is linked");
    if (!/\.html?$/i.test(relative)) continue;
    const raw = fs.readFileSync(file);
    requireValue(sha(raw) === row.sha256, "HTML bytes changed");
    for (const src of collectSubCompositionSrcs(raw.toString("utf8"))) checkMount(request, src);
  }
}

function checkMount(request, src) {
  const resolved = path.resolve(request.project, src);
  requireValue(resolved.startsWith(request.project + path.sep), "composition mount escapes project");
  const name = path.relative(request.project, resolved).split(path.sep).join("/");
  requireValue(!name.split("/").some(part => ["node_modules", ".git", ".hyperframes"].includes(part)),
    "composition mount enters an excluded directory");
  if (fs.existsSync(resolved)) requireValue(Boolean(request.files[name]?.sha256), "mount absent from source snapshot");
}

function protectProjectReads(request) {
  const read = fs.readFileSync;
  fs.readFileSync = function (file, options) {
    if (typeof file !== "string") return read(file, options);
    const absolute = path.resolve(file);
    if (!absolute.startsWith(request.project + path.sep)) return read(file, options);
    const relative = path.relative(request.project, absolute).split(path.sep).join("/");
    const expected = request.files[relative]?.sha256;
    requireValue(expected && fs.realpathSync(absolute) === absolute, "unbound SDK text read");
    const raw = read(file);
    requireValue(sha(raw) === expected, "source changed during SDK read");
    const encoding = typeof options === "string" ? options : options?.encoding;
    return encoding ? raw.toString(encoding) : raw;
  };
  syncBuiltinESMExports();
}

async function main() {
  const began = performance.now();
  forbidWork();
  forbidWrites();
  const { request, expected } = readRequest();
  const installed = JSON.parse(fs.readFileSync(path.join(request.packageRoot, "package.json")));
  requireValue(installed.name === "@hyperframes/lint" && installed.version === request.version
    && installed.exports["."].import === "./dist/index.js", "unexpected installed SDK linter");
  // This command is explicitly static-only. The SDK otherwise probes video
  // codecs, catching probe failures as false; do not silently claim that check.
  const unavailableProbe = path.join(process.argv[2], "static-only-no-codec-probe");
  requireValue(!fs.existsSync(unavailableProbe), "static-only probe sentinel must not exist");
  process.env.HYPERFRAMES_FFPROBE_PATH = unavailableProbe;
  protectProjectReads(request);
  await safeSources(request);
  const { dependencyFindings, coverageFindings } = await import("./native_preflight_dependencies.mjs");
  const dependencies = dependencyFindings(request);
  // The SDK reads linked stylesheets; refuse unbound targets before that read.
  requireValue(!dependencies.some(row => row.code === "native_unbound_dependency"), "unbound SDK stylesheet dependency");
  const api = await import(pathToFileURL(path.join(request.packageRoot, "dist/index.js")));
  const result = await api.lintProject(request.project);
  dependencies.push(...coverageFindings(request, result.results));
  requireValue(attempts.length === 0, "SDK attempted forbidden work");
  const blocked = dependencies.length > 0 || api.shouldBlockRender(true, false, result.totalErrors, result.totalWarnings);
  process.stdout.write(JSON.stringify({ schemaVersion: 1, scope: "native-static-preflight-only",
    requestSha256: expected, version: request.version, result, blocked,
    dependencyFindings: dependencies,
    codecProbePerformed: false, deniedAttempts: attempts, elapsedMs: performance.now() - began }) + "\n");
  if (blocked) process.exitCode = 1;
}

try {
  await main();
} catch (error) {
  process.stderr.write(JSON.stringify({ error: String(error), deniedAttempts: attempts }) + "\n");
  process.exitCode = 1;
}
