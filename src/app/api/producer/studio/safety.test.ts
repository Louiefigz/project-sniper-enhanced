import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { NextRequest } from "next/server";
import { assertStudioPaths, studioProducerDir, verifyStudioMedia } from "./paths";
import { GET, POST } from "./route";
import { inspectStudio, runStudioCommand } from "./process";
import { loopbackListener, readStudioRecord } from "./session";
import { StudioError } from "./model";

function fixture() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "sniper-studio-api-"));
  const project = path.join(root, "project");
  const dir = path.join(project, "producer");
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(project, "project.json"), "{}");
  return { root, dir, close: () => fs.rmSync(root, { recursive: true, force: true }) };
}

function request(body: unknown, overrides: Record<string, string> = {}) {
  return new NextRequest("http://127.0.0.1:3101/api/producer/studio", {
    method: "POST", headers: { host: "127.0.0.1:3101", origin: "http://127.0.0.1:3101",
      "content-type": "application/json", "sec-fetch-site": "same-origin", ...overrides },
    body: JSON.stringify(body),
  });
}

test("traversal and invalid project are rejected before subprocesses", async () => {
  assert.throws(() => studioProducerDir("/tmp/a/../producer"), /canonical/);
  assert.throws(() => studioProducerDir("relative"), /absolute/);
  const response = await POST(request({ dir: "/definitely-missing-studio-project" }));
  assert.equal(response.status, 400);
});

test("shared canonical workspace validation accepts only an actual producer directory", () => {
  const f = fixture(); const old = process.env.SNIPER_WORKSPACE_ROOT;
  process.env.SNIPER_WORKSPACE_ROOT = f.root;
  try {
    assert.equal(studioProducerDir(f.dir), fs.realpathSync(f.dir));
    assert.throws(() => studioProducerDir(f.root), /canonical producer/);
  } finally {
    if (old === undefined) delete process.env.SNIPER_WORKSPACE_ROOT;
    else process.env.SNIPER_WORKSPACE_ROOT = old;
    f.close();
  }
});

test("cross-origin and wrong content-type requests fail closed", async () => {
  assert.equal((await POST(request({ dir: "/unused" }, { origin: "https://evil.example" }))).status, 403);
  assert.equal((await POST(request({ dir: "/unused" }, { "content-type": "text/plain" }))).status, 415);
  const req = new NextRequest("http://evil.example/api/producer/studio?dir=/unused", {
    headers: { host: "evil.example" },
  });
  assert.equal((await GET(req)).status, 403);
});

test("force, sync and render parameters are never accepted", async () => {
  for (const key of ["force", "sync", "assemble", "action"]) {
    assert.equal((await POST(request({ dir: "/unused", [key]: true }))).status, 400);
  }
});

test("symlink projection or source inputs are refused without modification", () => {
  const f = fixture();
  try {
    fs.symlinkSync(f.root, path.join(f.dir, "studio"));
    assert.throws(() => assertStudioPaths(f.dir), /symlinks/);
    assert.ok(fs.lstatSync(path.join(f.dir, "studio")).isSymbolicLink());
  } finally { f.close(); }
});

test("manifest traversal and foreign base bindings are refused", () => {
  const f = fixture(); const studio = path.join(f.dir, "studio");
  fs.mkdirSync(studio);
  try {
    fs.writeFileSync(path.join(studio, "studio.manifest.json"), JSON.stringify({
      files: { "../outside": "digest" }, media: { target: path.join(f.dir, "base_final.mp4"), rel: "assets/base.mp4" },
    }));
    assert.throws(() => assertStudioPaths(f.dir), /tracked paths/);
    fs.writeFileSync(path.join(studio, "studio.manifest.json"), JSON.stringify({
      files: {}, media: { target: "/foreign/base.mp4", rel: "assets/base.mp4" },
    }));
    assert.throws(() => assertStudioPaths(f.dir), /does not bind/);
  } finally { f.close(); }
});

test("same-sized but different staged media fails exact verification", async () => {
  const f = fixture(); const studio = path.join(f.dir, "studio");
  fs.mkdirSync(path.join(studio, "assets"), { recursive: true });
  try {
    fs.writeFileSync(path.join(f.dir, "base_final.mp4"), "aaaa");
    fs.writeFileSync(path.join(studio, "assets/base.mp4"), "bbbb");
    fs.writeFileSync(path.join(studio, "studio.manifest.json"), JSON.stringify({
      files: {}, media: { target: path.join(f.dir, "base_final.mp4"), rel: "assets/base.mp4" },
    }));
    await assert.rejects(verifyStudioMedia(f.dir), /differs/);
  } finally { f.close(); }
});

test("record cannot supply an arbitrary port or URL", () => {
  const f = fixture(); fs.mkdirSync(path.join(f.dir, "studio"));
  try {
    fs.writeFileSync(path.join(f.dir, "studio/.studio-server.json"), JSON.stringify({
      pid: 1, port: 80, url: "https://evil.example", startedAt: "2026-09-06T12:00:00Z",
    }));
    assert.throws(() => readStudioRecord(f.dir), /invalid/);
  } finally { f.close(); }
});

test("listener proof requests numeric hosts and ports instead of reverse-DNS localhost", async () => {
  const record = { pid: 123, port: 3992, startedAt: "2026-09-06T12:00:00Z" };
  let args: string[] = [];
  const ready = await loopbackListener(record, async (_command, commandArgs) => {
    args = commandArgs;
    return "p123\nn127.0.0.1:3992\n";
  });
  assert.equal(ready, true);
  assert.ok(args.includes("-nP"));
  assert.equal(await loopbackListener(record, async () => "p123\nn*:3992\n"), false);
});

test("bounded subprocess timeout reports 504", async () => {
  await assert.rejects(runStudioCommand(process.execPath, ["-e", "setTimeout(()=>{},10000)"], 100),
    (error: StudioError) => error.status === 504);
});

test("real Python inspection names missing inputs without generating files", async () => {
  const f = fixture();
  try {
    const result = await inspectStudio(f.dir);
    assert.match(result.blockers.join(" "), /edit plan/);
    assert.equal(fs.existsSync(path.join(f.dir, "studio")), false);
  } finally { f.close(); }
});

test("legacy missing or duplicate host IDs block without changing saved files", async () => {
  const f = fixture(); const studio = path.join(f.dir, "studio"); fs.mkdirSync(studio);
  const file = path.join(studio, "index.html");
  const sources = [
    '<body><div id="review-root"><video data-hf-id="hf-base"></video></div></body>',
    '<body><div data-hf-id="hf-duplicate"><video data-hf-id="hf-duplicate"></video></div></body>',
    '<div data-hf-id="hf-fragment"></div>',
    '<body><div data-hf-id=" "></div></body>',
  ];
  try {
    for (const source of sources) {
      fs.writeFileSync(file, source);
      const before = fs.statSync(file).mtimeMs;
      const result = await inspectStudio(f.dir);
      assert.match(result.blockers.join(" "), /missing or duplicate element IDs/);
      assert.equal(fs.readFileSync(file, "utf8"), source);
      assert.equal(fs.statSync(file).mtimeMs, before);
      assert.deepEqual(fs.readdirSync(studio), ["index.html"]);
    }
  } finally { f.close(); }
});

test("unique existing IDs are accepted without forcing new generator IDs", async () => {
  const f = fixture(); const studio = path.join(f.dir, "studio"); fs.mkdirSync(studio);
  const source = '<body><div data-hf-id="hf-ab12"><video data-hf-id="hf-cd34"></video>'
    + '<script>const valid=true;</script></div></body>';
  fs.writeFileSync(path.join(studio, "index.html"), source);
  try {
    const result = await inspectStudio(f.dir);
    assert.doesNotMatch(result.blockers.join(" "), /element IDs/);
    assert.equal(fs.readFileSync(path.join(studio, "index.html"), "utf8"), source);
  } finally { f.close(); }
});

test("startup guard forces loopback and refuses CLI port fallback without binding sockets", async () => {
  const guard = path.join(process.cwd(), "src/app/api/producer/studio/loopback-only.cjs");
  const code = `const net=require('node:net'); let calls=[];
net.Server.prototype.listen=function(...a){calls.push(a); return this;};
require(${JSON.stringify(guard)}); const s=net.createServer();
s.listen({port:3992,host:'0.0.0.0'}); s.listen(3992,'::');
let refused=false;try{s.listen(3993,'127.0.0.1')}catch{refused=true}
console.log(JSON.stringify({calls,refused}));`;
  const result = JSON.parse(await runStudioCommand(process.execPath, ["-e", code, "--", "--port", "3992"]));
  assert.equal(result.calls[0][0].host, "127.0.0.1");
  assert.equal(result.calls[1][1], "127.0.0.1");
  assert.equal(result.refused, true);
});
