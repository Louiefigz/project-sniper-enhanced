import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import vm from "node:vm";
import { test } from "node:test";
import { runStudioCommand } from "./process";

const require = createRequire(import.meta.url);
const runtime = require("./review-shell-runtime.cjs") as {
  BUNDLE: string; FONT_PATH: string;
  transformStudioBundle: (value: Buffer) => Buffer;
  localFontStyles: (value: Buffer) => Buffer;
};
const root = path.join(process.cwd(), "templates/motion");
const bundlePath = path.join(root, "node_modules/hyperframes/dist/studio", runtime.BUNDLE);
const original = readFileSync(bundlePath), transformed = runtime.transformStudioBundle(original).toString();

function functionText(source: string, begin: string, end: string): string {
  const start = source.indexOf(begin), stop = source.indexOf(end, start);
  assert.ok(start >= 0 && stop > start);
  return source.slice(start, stop);
}

test("only exact audited shell bytes transform, with no vendor or project-file write", () => {
  assert.deepEqual(readFileSync(bundlePath), original);
  assert.throws(() => runtime.transformStudioBundle(Buffer.from(original.toString() + "\n")), /exact audited/);
  assert.throws(() => runtime.transformStudioBundle(Buffer.from(transformed)), /exact audited/);
  assert.ok(transformed.includes("function uFe({value:t,disabled:e,importedFonts:n,onImportFonts:r,onCommit:i}){e=true;"));
  assert.equal(transformed.includes('fetch("/api/fonts/google")'), false, "disabled field must not cause hidden server egress");
});

test("ordinary timelines request no plugin; actual motion-path vars remain a loud unsupported state", () => {
  const context = vm.createContext({});
  vm.runInContext(functionText(transformed, "function _we(", "function Iwe("), context);
  let created = 0;
  const frame = { contentWindow: { __timelines: { card: { getChildren: () => [{ vars: { x: 20, opacity: 1 } }] } } },
    contentDocument: { createElement: () => { created++; throw new Error("no network plugin allowed"); } } };
  context.frame = frame;
  assert.doesNotThrow(() => vm.runInContext("_we(frame)", context));
  assert.equal(created, 0);
  frame.contentWindow.__timelines.card.getChildren = () => [{ vars: { motionPath: [] } }] as never;
  assert.throws(() => vm.runInContext("_we(frame)", context), /not qualified offline/);
  assert.equal(created, 0);
});

test("the separate native soft-reload loader also rejects motion paths before requesting a plugin", () => {
  const context = vm.createContext({});
  const begin = transformed.indexOf("function Lwe(");
  const prefixEnd = transformed.indexOf("var d,m;", begin);
  assert.ok(prefixEnd > begin);
  vm.runInContext(transformed.slice(begin, prefixEnd) + 'return "test-ordinary";}', context);
  assert.equal(vm.runInContext('Lwe(null,"gsap.to(el,{x:20})")', context), "test-ordinary");
  assert.throws(() => vm.runInContext('Lwe(null,"gsap.to(el,{motionPath:{path:[]}})")', context), /not qualified offline/);
});

test("font previews use exact source font faces only; CSS loader never substitutes an external family", () => {
  const tokens = readFileSync(path.join(root, "tokens.css"));
  const css = runtime.localFontStyles(tokens).toString();
  assert.equal(css, tokens.toString().match(/@font-face\s*\{[^}]*\}/gu)!.join("\n"));
  assert.equal((css.match(/@font-face/gu) ?? []).length, 4);
  assert.equal(/https?:|:root|\.clip/u.test(css), false);
  assert.throws(() => runtime.localFontStyles(Buffer.from(tokens.toString() + "\n")), /re-audit/);
  const document = { createElement: () => { throw new Error("must not request Google CSS"); } };
  vm.runInNewContext(functionText(transformed, "function vZ(", "function ev(") + ';vZ("Inter");vZ("Unknown");', { document });
});

test("reserved GET/HEAD runtime paths and query/encoded aliases serve the same corrected bytes", async () => {
  const shell = path.join(process.cwd(), "src/app/api/producer/studio/review-shell.cjs");
  const code = `const shell=require(${JSON.stringify(shell)}),crypto=require('node:crypto');
const rows=[];for(const [method,url] of ${JSON.stringify([
    ["GET", `/${runtime.BUNDLE}`], ["HEAD", `/${runtime.BUNDLE}`], ["GET", runtime.FONT_PATH],
    ["GET", `/${runtime.BUNDLE}?changed=1`], ["POST", runtime.FONT_PATH], ["GET", "/api/projects/studio/preview"],
    ["GET", `/${runtime.BUNDLE.replace("assets/", "%61ssets/")}?v=1`],
    ["GET", `/${runtime.BUNDLE.replace("assets/", "%2561ssets/")}`],
    ["GET", `/${runtime.BUNDLE.replace("assets/", "assets/unused/../")}`],
  ])}){const row={method,url,headers:{}};row.served=shell.serveShellScript({method,url},
{writeHead(status,headers){row.status=status;row.headers=headers},end(body){row.bytes=body?.length??0;
row.hash=body?crypto.createHash('sha256').update(body).digest('hex'):null}});rows.push(row)}console.log(JSON.stringify(rows));`;
  const rows = JSON.parse(await runStudioCommand(process.execPath, ["-e", code]));
  assert.deepEqual(rows.map((row: { served: boolean }) => row.served), [true, true, true, true, false, false, true, true, true]);
  assert.equal(rows[0].bytes, Buffer.byteLength(transformed));
  assert.equal(rows[0].headers["Content-Length"], rows[0].bytes);
  assert.equal(rows[1].bytes, 0); assert.equal(rows[1].headers["Content-Length"], rows[0].bytes);
  assert.equal(rows[2].headers["Content-Type"], "text/css; charset=utf-8");
  for (const index of [3, 6, 7, 8]) assert.equal(rows[index].hash, rows[0].hash, "alias cannot return uncorrected bytes");
});

test("actual loopback HTTP cannot return the original bundle through query or encoded aliases", async () => {
  const guard = path.join(process.cwd(), "src/app/api/producer/studio/review-only.cjs");
  const aliases = [`/${runtime.BUNDLE}`, `/${runtime.BUNDLE}?v=1`,
    `/${runtime.BUNDLE.replace("assets/", "%61ssets/")}`, `/${runtime.BUNDLE.replace("assets/", "%2561ssets/")}`];
  const code = `const http=require('node:http'),crypto=require('node:crypto');require(${JSON.stringify(guard)});
let upstream=0;const server=http.createServer((req,res)=>{upstream++;res.end('UPSTREAM')});
const fetch=(port,url)=>new Promise((resolve,reject)=>{const request=http.get({host:'127.0.0.1',port,path:url},response=>{
const hash=crypto.createHash('sha256');response.on('data',data=>hash.update(data));response.on('error',reject);
response.on('end',()=>resolve({status:response.statusCode,hash:hash.digest('hex'),headers:response.headers}))});
request.on('error',reject);request.setTimeout(5000,()=>request.destroy(new Error('test request deadline')))});
server.listen(0,'127.0.0.1',async()=>{try{const port=server.address().port,rows=[];
for(const url of ${JSON.stringify(aliases)})rows.push(await fetch(port,url));
const other=await fetch(port,'/api/projects/studio/preview');console.log(JSON.stringify({rows,other,upstream}));
}catch(error){console.error(error);process.exitCode=1}finally{server.close()}});`;
  const result = JSON.parse(await runStudioCommand(process.execPath, ["-e", code]));
  const { createHash } = await import("node:crypto");
  const expected = createHash("sha256").update(transformed).digest("hex");
  for (const row of result.rows) {
    assert.equal(row.status, 200); assert.equal(row.hash, expected);
    assert.equal(row.headers["x-sniper-studio-policy"], "review-only-v4");
  }
  assert.equal(result.upstream, 1, "only the unrelated request may reach the upstream handler");
});
