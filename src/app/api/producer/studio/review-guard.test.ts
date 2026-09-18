import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import type http from "node:http";
import path from "node:path";
import { test } from "node:test";
import { runStudioCommand } from "./process";
import { probeStudio } from "./session";
import policy from "./review-policy.json";

const GUARD = path.join(process.cwd(), "src/app/api/producer/studio/review-only.cjs");
const RECORD = { pid: 1234, port: 3991, startedAt: "2026-09-06T12:00:00Z" };

test("server guard rejects deliverable routes before any application handler runs", async () => {
  const denied = ["/api/projects/studio/render", "/api/projects/studio/renders",
    "/api/projects/studio/renders/file/output.mp4", "/api/render/job/download",
    "/api/render/job/progress", "/render", "/render/stream", "/export", "/exports",
    "/api/projects/studio/%72ender", "/api/projects/studio/%2572ender",
    "/api%2fprojects%2fstudio%2frender", "/api/projects/studio/RENDER",
    "/api/projects/studio/render?format=mp4", "/api/projects/studio/render;ignored",
    "/api/projects/studio%5crender", "/api/projects/studio/export.mp4", "/bad%ZZ"];
  const allowed = ["/__hyperframes_config", "/api/events", "/api/projects/studio/preview",
    "/api/projects/studio/files?path=index.html", "/assets/index.js", "/api/projects/studio/storyboard"];
  const code = `const http=require('node:http');require(${JSON.stringify(GUARD)});
let hits=0;const server=http.createServer(()=>{hits++});
const rows=${JSON.stringify([...denied, ...allowed])}.map(url=>{
 const row={url,status:200,headers:{}}; const before=hits;
 const req={url,method:'POST',resume(){}};
 const res={setHeader(k,v){row.headers[k]=v},writeHead(s,h){row.status=s;Object.assign(row.headers,h)},end(b){row.body=b}};
 server.emit('request',req,res); row.handled=hits>before; return row;
});process.stdout.write(JSON.stringify(rows));`;
  const rows = JSON.parse(await runStudioCommand(process.execPath, ["-e", code]));
  for (const row of rows) {
    const blocked = denied.includes(row.url);
    assert.equal(row.status, blocked ? 403 : 200, row.url);
    assert.equal(row.handled, !blocked, row.url);
    assert.equal(row.headers[policy.header], policy.identity);
    if (blocked) assert.equal(JSON.parse(row.body).code, "SNIPER_STUDIO_REVIEW_ONLY");
  }
});

test("upgrades and CONNECT never reach a new upstream transport", async () => {
  const code = `const http=require('node:http');require(${JSON.stringify(GUARD)});
const server=http.createServer();let hits=0,destroyed=0;let replies=[];
server.on('upgrade',()=>hits++);server.on('connect',()=>hits++);
for(const event of ['upgrade','connect']) server.emit(event,{url:'/'},
 {end:v=>replies.push(v),destroySoon:()=>destroyed++});
process.stdout.write(JSON.stringify({hits,replies,destroyed}));`;
  const result = JSON.parse(await runStudioCommand(process.execPath, ["-e", code]));
  assert.equal(result.hits, 0);
  assert.equal(result.replies.length, 2);
  assert.equal(result.destroyed, 2);
  assert.ok(result.replies.every((reply: string) => reply.startsWith("HTTP/1.1 403")));
});

test("Expect requests cannot bypass the render denial", async () => {
  const code = `const http=require('node:http');require(${JSON.stringify(GUARD)});
const s=http.createServer();let hits=0,replies=0;
for(const name of ['checkContinue','checkExpectation']) {
 s.on(name,()=>hits++);s.emit(name,{url:'/api/projects/studio/render',resume(){}},
 {setHeader(){},writeHead(status){if(status===403)replies++},end(){}});
}process.stdout.write(JSON.stringify({hits,replies}));`;
  assert.deepEqual(JSON.parse(await runStudioCommand(process.execPath, ["-e", code])), { hits: 0, replies: 2 });
});

test("changed CLI bytes fail closed pending an endpoint re-audit", async () => {
  const code = `const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const filename=${JSON.stringify(GUARD)};const source=fs.readFileSync(filename,'utf8');
let error='';try{vm.runInNewContext(source,{__dirname:path.dirname(filename),
 require:name=>name==='node:fs'?{readFileSync:()=>Buffer.from('changed')}:
 name==='./review-policy.json'?${JSON.stringify(policy)}:require(name)})}catch(e){error=e.message}
process.stdout.write(error);`;
  assert.match(await runStudioCommand(process.execPath, ["-e", code]), /requires the audited HyperFrames/);
});

function identityGet(marker?: string): typeof http.get {
  return ((_options: unknown, callback: (response: unknown) => void) => {
    const request = new EventEmitter();
    const response = Object.assign(new EventEmitter(), {
      statusCode: 200, headers: marker ? { [policy.header]: marker } : {}, resume() {},
    });
    queueMicrotask(() => {
      callback(response);
      response.emit("data", JSON.stringify({ isHyperframes: true, projectDir: "/fixture/producer/studio" }));
      response.emit("end");
    });
    return request;
  }) as typeof http.get;
}

test("readiness refuses absent or wrong guard identity even when upstream identity is valid", async () => {
  assert.equal(await probeStudio(RECORD, identityGet()), null);
  assert.equal(await probeStudio(RECORD, identityGet("review-only-v0")), null);
  assert.deepEqual(await probeStudio(RECORD, identityGet(policy.identity)), {
    isHyperframes: true, projectDir: "/fixture/producer/studio",
  });
});
