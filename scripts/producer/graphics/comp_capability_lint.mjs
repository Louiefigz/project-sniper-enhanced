/** Official root lint only. No rendering, child tools, downloads, or networking. */
import fs from "node:fs";
import path from "node:path";
import { createHash } from "node:crypto";
import { createRequire, syncBuiltinESMExports } from "node:module";
import { pathToFileURL } from "node:url";

const require = createRequire(import.meta.url);
export const attempts = [];
const started = performance.now();
const sha256 = (data) => createHash("sha256").update(data).digest("hex");

function deny(label) {
  return () => {
    if (attempts.length < 32) attempts.push(label);
    throw new Error(`Static root lint forbids ${label}`);
  };
}

export function forbidWork() {
  const child = require("node:child_process");
  for (const name of ["spawn", "spawnSync", "exec", "execSync", "execFile", "execFileSync", "fork"]) child[name] = deny(`child_process.${name}`);
  for (const protocol of ["http", "https"]) {
    const transport = require(`node:${protocol}`);
    transport.request = deny(`${protocol}.request`);
    transport.get = deny(`${protocol}.get`);
  }
  require("node:net").Socket.prototype.connect = deny("net.connect");
  require("node:tls").connect = deny("tls.connect");
  require("node:dgram").createSocket = deny("dgram.createSocket");
  require("node:dns").lookup = deny("dns.lookup");
  require("node:dns").promises.lookup = deny("dns.promises.lookup");
  require("node:worker_threads").Worker = deny("worker_threads.Worker");
  globalThis.fetch = deny("fetch");
  syncBuiltinESMExports();
}

export function forbidWrites() {
  for (const name of ["writeFile", "appendFile", "truncate", "ftruncate", "rename", "unlink", "rm", "rmdir",
    "mkdir", "mkdtemp", "copyFile", "cp", "link", "symlink", "chmod", "fchmod", "chown", "fchown", "lchown",
    "utimes", "futimes", "lutimes", "write", "writev"]) {
    if (typeof fs[name] === "function") fs[name] = deny(`fs.${name}`);
    if (typeof fs[name + "Sync"] === "function") fs[name + "Sync"] = deny(`fs.${name}Sync`);
    if (typeof fs.promises[name] === "function") fs.promises[name] = deny(`fs.promises.${name}`);
  }
  fs.createWriteStream = deny("fs.createWriteStream");
  for (const [owner, name] of [[fs, "open"], [fs, "openSync"], [fs.promises, "open"]]) {
    const original = owner[name];
    owner[name] = function (file, flags, ...rest) {
      if (flags !== "r" && flags !== fs.constants.O_RDONLY) return deny(`fs.${name}:write-flags`)();
      return original.call(this, file, flags, ...rest);
    };
  }
  syncBuiltinESMExports();
}

function readRequest() {
  const [requestPath, expectedHash] = process.argv.slice(2);
  if (!path.isAbsolute(requestPath ?? "") || !/^[a-f0-9]{64}$/.test(expectedHash ?? "")) throw new Error("Invalid root-lint request reference");
  const info = fs.lstatSync(requestPath);
  if (!info.isFile() || info.isSymbolicLink() || info.size > 128 * 1024) throw new Error("Invalid root-lint request file");
  const raw = fs.readFileSync(requestPath);
  if (sha256(raw) !== expectedHash) throw new Error("Root-lint request changed");
  const request = JSON.parse(raw.toString("utf8"));
  if (request.schemaVersion !== 1 || request.version !== "0.8.31" || !Array.isArray(request.entries)
    || request.entries.length < 1 || request.entries.length > 128) throw new Error("Invalid root-lint request shape");
  for (const entry of request.entries) {
    if (entry.path !== path.join(request.motion, "compositions", `${entry.kind}.html`)
      || !/^[a-z0-9-]+$/.test(entry.kind) || !/^[a-f0-9]{64}$/.test(entry.sha256)) throw new Error("Invalid root-lint entry");
  }
  return { request, expectedHash };
}

async function run(request) {
  const packagePath = path.join(request.packageRoot, "package.json");
  const installed = JSON.parse(fs.readFileSync(packagePath, "utf8"));
  if (installed.name !== "@hyperframes/lint" || installed.version !== request.version
    || installed.exports["."].import !== "./dist/index.js") throw new Error("Unexpected official lint installation");
  const api = await import(pathToFileURL(path.join(request.packageRoot, installed.exports["."].import)));
  const rows = [];
  for (const entry of request.entries) {
    if (sha256(fs.readFileSync(entry.path)) !== entry.sha256) throw new Error("Original root-lint entry changed");
    const result = await api.lintProject(request.motion, entry.path);
    rows.push({ ...entry, result });
  }
  const blocked = api.shouldBlockRender(true, false,
    rows.reduce((count, row) => count + row.result.totalErrors, 0),
    rows.reduce((count, row) => count + row.result.totalWarnings, 0));
  return { rows, blocked };
}

async function main() {
  forbidWork();
  const { request, expectedHash } = readRequest();
  const result = await run(request);
  const value = { schemaVersion: 1, scope: "official-root-lint-not-render-or-approval",
    version: request.version, requestSha256: expectedHash, ...result,
    deniedAttempts: attempts, elapsedMs: performance.now() - started };
  process.stdout.write(`${JSON.stringify(value)}\n`);
  if (attempts.length || result.blocked) process.exitCode = 1;
}

if (process.argv[1] && pathToFileURL(path.resolve(process.argv[1])).href === import.meta.url) {
  try {
    await main();
  } catch (error) {
    process.stderr.write(`${JSON.stringify({ error: String(error), deniedAttempts: attempts })}\n`);
    process.exitCode = 1;
  }
}
