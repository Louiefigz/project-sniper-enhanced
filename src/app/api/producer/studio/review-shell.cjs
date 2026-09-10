"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { createHash } = require("node:crypto");
const { AsyncLocalStorage } = require("node:async_hooks");
const { syncBuiltinESMExports } = require("node:module");
const policy = require("./review-policy.json");
const runtime = require("./review-shell-runtime.cjs");
const studio = path.resolve(__dirname, "../../../../../templates/motion/node_modules/hyperframes/dist/studio");
const index = path.join(studio, "index.html");
const scriptPath = "/__sniper_studio_review_ui.js";
const originalRead = fs.readFileSync;
const shellRequest = new AsyncLocalStorage();

for (const [relative, sha] of Object.entries(policy.uiSha256)) {
  const bytes = originalRead(path.join(studio, relative));
  if (createHash("sha256").update(bytes).digest("hex") !== sha) {
    throw new Error("Sniper Studio review controls require the audited frontend assets");
  }
}
const offlineBundle = runtime.transformStudioBundle(originalRead(path.join(studio, runtime.BUNDLE)));
const offlineFonts = runtime.localFontStyles(originalRead(path.resolve(studio, "../../../../tokens.css")));

// The pinned shell handler reads this exact file at CLI111071, then adds its
// own environment/bootstrap scripts and constructs the Hono response. Alter
// only that in-memory read in GET /'s async context. No file writes, response
// buffering, CSP relaxation, stream interception or content-length rewriting.
fs.readFileSync = function (file, ...args) {
  const value = Reflect.apply(originalRead, this, [file, ...args]);
  if (String(file) !== index || !shellRequest.getStore()) return value;
  const html = Buffer.isBuffer(value) ? value.toString("utf8") : value;
  const changed = html.replace("</head>", `<script src="${scriptPath}"></script>\n<link rel="stylesheet" href="${runtime.FONT_PATH}">\n</head>`);
  return Buffer.isBuffer(value) ? Buffer.from(changed, "utf8") : changed;
};
syncBuiltinESMExports();

function isShellRequest(request) {
  try { return request.method === "GET" && new URL(request.url, "http://127.0.0.1").pathname === "/"; }
  catch { return false; }
}

function runShellRequest(request, handler) {
  return shellRequest.run(isShellRequest(request), handler);
}

/** Resolve aliases only for our three reserved resources. Never let a cache
 * query or encoded static path fall through to the uncorrected vendor bundle. */
function resourcePath(raw) {
  try {
    let pathname = new URL(raw, "http://127.0.0.1").pathname;
    for (let pass = 0; pass < 4 && pathname.includes("%"); pass += 1) pathname = decodeURIComponent(pathname);
    if (pathname.includes("%") || /[\u0000-\u001f\u007f]/u.test(pathname)) return null;
    return new URL(pathname, "http://127.0.0.1").pathname;
  } catch { return null; }
}

function serveShellScript(request, response) {
  if (!["GET", "HEAD"].includes(request.method)) return false;
  const resources = { [scriptPath]: [() => originalRead(path.join(__dirname, "review-shell-ui.js")), "text/javascript"],
    [`/${runtime.BUNDLE}`]: [() => offlineBundle, "text/javascript"],
    [runtime.FONT_PATH]: [() => offlineFonts, "text/css"] };
  const key = resourcePath(request.url);
  if (!Object.hasOwn(resources, key)) return false;
  const [read, mime] = resources[key], bytes = read();
  response.writeHead(200, { "Content-Type": `${mime}; charset=utf-8`,
    "Content-Length": bytes.length, "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" });
  response.end(request.method === "HEAD" ? undefined : bytes);
  return true;
}

module.exports = { runShellRequest, serveShellScript };
