"use strict";

// This policy is scoped to route-launched Studio, not the Sniper server.
// Re-audit the pinned CLI's HTTP/upgrade routes before updating this digest.
// Studio 0.7.33 uses SSE for edits/events; it needs no WebSocket upgrade.
// Its deliverable start is POST /api/projects/:id/render. Related render
// history/job endpoints and the separate /render server are denied too.
// The identity header is checked alongside process/project/listener proofs.
const http = require("node:http");
const fs = require("node:fs");
const path = require("node:path");
const { createHash } = require("node:crypto");
const policy = require("./review-policy.json");
const cli = path.resolve(__dirname, "../../../../../templates/motion/node_modules/hyperframes/dist/cli.js");
if (createHash("sha256").update(fs.readFileSync(cli)).digest("hex") !== policy.cliSha256) {
  throw new Error(`Sniper Studio review guard requires the audited HyperFrames ${policy.cliVersion} CLI`);
}
require("./review-attribute-interop.cjs").registerCliInterop(cli);

function deniedPath(rawUrl) {
  try {
    let value = new URL(rawUrl, "http://127.0.0.1").pathname;
    for (let pass = 0; pass < 4 && value.includes("%"); pass += 1) {
      value = decodeURIComponent(value);
    }
    if (value.includes("%") || /[\u0000-\u001f\u007f]/u.test(value)) return true;
    return value.toLowerCase().split(/[\\/;]/u)
      .some((part) => /^(?:renders?|exports?)(?:\.|$)/u.test(part));
  } catch { return true; }
}

function refuseRequest(request, response) {
  request.resume();
  response.writeHead(403, { "content-type": "application/json", "cache-control": "no-store", connection: "close",
    [policy.header]: policy.identity });
  response.end(JSON.stringify({ error: "Studio is review-only. Render updated video in Sniper for full QC.",
    code: "SNIPER_STUDIO_REVIEW_ONLY" }));
}

const originalEmit = http.Server.prototype.emit;
const shell = require("./review-shell.cjs");
http.Server.prototype.emit = function (event, ...args) {
  if (event === "upgrade" || event === "connect") {
    args[1].end("HTTP/1.1 403 Forbidden\r\nConnection: close\r\nContent-Length: 0\r\n\r\n");
    args[1].destroySoon();
    return true;
  }
  if (["request", "checkContinue", "checkExpectation"].includes(event)) {
    const [request, response] = args;
    response.setHeader(policy.header, policy.identity);
    if (deniedPath(request.url)) { refuseRequest(request, response); return true; }
    if (event === "request" && shell.serveShellScript(request, response)) return true;
    if (event === "request") {
      return shell.runShellRequest(request, () => Reflect.apply(originalEmit, this, [event, ...args]));
    }
  }
  return Reflect.apply(originalEmit, this, [event, ...args]);
};
