/** Bounded supplied HTML -> ensureHfIds only. No HTML execution or project writes. */
import fs from "node:fs";
import crypto from "node:crypto";
import { createRequire } from "node:module";
import { ensureHfIds } from "@hyperframes/parsers/hf-ids";

const TOKEN = "hf-ids-0.8.31", MAX_INPUT = 4 * 1024 * 1024, MAX_OUTPUT = 8 * 1024 * 1024;

function readRequest(args) {
  if (args.length !== 3) throw new Error("Expected one bounded Studio ID request reference");
  const [file, sha256, size] = args;
  if (!/^[a-f0-9]{64}$/.test(sha256) || !/^[1-9][0-9]*$/.test(size)
    || Number(size) > MAX_INPUT || fs.realpathSync(file) !== file) throw new Error("Invalid Studio ID input reference");
  const fd = fs.openSync(file, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW);
  try {
    const before = fs.fstatSync(fd);
    if (!before.isFile() || before.nlink !== 1 || before.uid !== process.getuid()
      || before.size !== Number(size)) throw new Error("Invalid original Studio ID file");
    const raw = fs.readFileSync(fd), after = fs.fstatSync(fd);
    if (raw.length !== before.size || after.size !== before.size || after.mtimeMs !== before.mtimeMs
      || after.ctimeMs !== before.ctimeMs || crypto.createHash("sha256").update(raw).digest("hex") !== sha256) {
      throw new Error("Studio ID input changed");
    }
    return JSON.parse(raw.toString("utf8"));
  } finally { fs.closeSync(fd); }
}

function entries(value) {
  if (!value || Array.isArray(value) || typeof value !== "object"
    || Object.keys(value).sort().join(",") !== "instances,normalizer,schemaVersion"
    || value.schemaVersion !== 1 || value.normalizer !== TOKEN) throw new Error("Unknown Studio ID request");
  const rows = value.instances;
  if (!rows || Array.isArray(rows) || typeof rows !== "object"
    || Object.keys(rows).length < 1 || Object.keys(rows).length > 1024) throw new Error("Invalid Studio composition batch");
  return Object.entries(rows).map(([key, html]) => {
    if (!/^compositions\/[^/\\]+\.html$/.test(key) || key.length > 256
      || typeof html !== "string" || html.length < 1 || html.length > 1024 * 1024) throw new Error("Invalid Studio composition");
    return [key, html];
  });
}

function main(args) {
  if (createRequire(import.meta.url)("@hyperframes/parsers/package.json").version !== "0.8.31") {
    throw new Error("Studio IDs require the installed parser version 0.8.31");
  }
  const original = entries(readRequest(args)), output = {};
  let bytes = 0;
  for (const [key, html] of original) {
    const normalized = ensureHfIds(html);
    bytes += Buffer.byteLength(normalized, "utf8");
    if (bytes > MAX_OUTPUT) throw new Error("Studio ID output exceeds its aggregate bound");
    output[key] = normalized;
  }
  const text = JSON.stringify({ schemaVersion: 1, normalizer: TOKEN, instances: output });
  if (Buffer.byteLength(text, "utf8") > MAX_OUTPUT) throw new Error("Studio ID response exceeds 8 MiB");
  process.stdout.write(text);
}

try { main(process.argv.slice(2)); }
catch (error) { process.stderr.write(String(error.message)); process.exitCode = 1; }
