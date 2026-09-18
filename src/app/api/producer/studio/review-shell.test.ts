import assert from "node:assert/strict";
import path from "node:path";
import { test } from "node:test";
import { runStudioCommand } from "./process";

const SHELL = path.join(process.cwd(), "src/app/api/producer/studio/review-shell.cjs");
const UI = path.join(process.cwd(), "src/app/api/producer/studio/review-shell-ui.js");
const INDEX = path.join(process.cwd(), "templates/motion/node_modules/hyperframes/dist/studio/index.html");

test("only GET / shell reads gain controls; preview docs, disk and response streams stay unchanged", async () => {
  const code = `const fs=require('node:fs'),http=require('node:http');
const filename=${JSON.stringify(INDEX)};const original=fs.readFileSync(filename,'utf8');
const write=http.ServerResponse.prototype.write,end=http.ServerResponse.prototype.end;
const shell=require(${JSON.stringify(SHELL)});
(async()=>{const esm=await import('node:fs');const read=()=>esm.readFileSync(filename,'utf8');
const injected=await shell.runShellRequest({method:'GET',url:'/'},async()=>{await Promise.resolve();return read()});
const preview=shell.runShellRequest({method:'GET',url:'/api/projects/studio/preview'},read);
const head=shell.runShellRequest({method:'HEAD',url:'/'},read);
const plain=fs.readFileSync(filename,'utf8');
console.log(JSON.stringify({injected,original,preview,head,plain,
 untouched:write===http.ServerResponse.prototype.write&&end===http.ServerResponse.prototype.end}));})();`;
  const result = JSON.parse(await runStudioCommand(process.execPath, ["-e", code]));
  assert.ok(result.injected.includes('<script src="/__sniper_studio_review_ui.js"></script>'));
  assert.equal(result.preview, result.original);
  assert.equal(result.head, result.original);
  assert.equal(result.plain, result.original);
  assert.equal(result.untouched, true);
});

test("audited controls disable while ordinary editing and playback actions remain usable", async () => {
  const code = `const fs=require('node:fs'),vm=require('node:vm');
class Button { constructor(text,classes='',label=''){this.textContent=text;this.tagName='BUTTON';this.disabled=false;this.style={};
this.attrs={'aria-label':label};this.classList={contains:v=>classes.split(' ').includes(v)};this.title='';}
hasAttribute(k){return Object.hasOwn(this.attrs,k)}getAttribute(k){return this.attrs[k]??null}
setAttribute(k,v){this.attrs[k]=v}closest(){return this}}
const buttons=[new Button('Export','bg-studio-accent'),new Button('Export','bg-panel-accent'),
new Button('','', 'Render index'),new Button('Play'),new Button('Undo'),new Button('Inspector'),
new Button('Export','unrelated'),new Button('Save','bg-panel-accent'),new Button('','', 'Set motion destination')];
const events={};let refresh;const document={documentElement:{},querySelectorAll:()=>buttons,
addEventListener:(name,fn)=>{events[name]=fn}};
vm.runInNewContext(fs.readFileSync(${JSON.stringify(UI)},'utf8'),{document,Element:Button,
MutationObserver:class {constructor(fn){refresh=fn}observe(){}}});
const prevented=buttons.map(button=>{let count=0;events.click({type:'click',target:button,
preventDefault(){count++},stopImmediatePropagation(){}});return count});
let keyboard=0;events.keydown({type:'keydown',key:'Enter',target:buttons[0],
preventDefault(){keyboard++},stopImmediatePropagation(){}});
buttons[0].disabled=false;refresh();
console.log(JSON.stringify({disabled:buttons.map(b=>b.disabled),styles:buttons.map(b=>b.style),
titles:buttons.map(b=>b.title),prevented,keyboard}));`;
  const result = JSON.parse(await runStudioCommand(process.execPath, ["-e", code]));
  assert.deepEqual(result.disabled, [true, true, true, false, false, false, false, false, true]);
  assert.deepEqual(result.prevented, [1, 1, 1, 0, 0, 0, 0, 0, 1]);
  assert.equal(result.keyboard, 1);
  assert.match(result.titles[0], /Render updated video in Sniper/u);
  assert.deepEqual(result.styles.slice(0, 3), Array(3).fill({ opacity: "0.45", cursor: "not-allowed" }));
  assert.deepEqual(result.styles.slice(3, 8), Array(5).fill({}));
  assert.match(result.titles[8], /motion-path editing is not qualified offline/);
});

test("UI script route serves only its exact path without rewriting unrelated responses", async () => {
  const code = `const shell=require(${JSON.stringify(SHELL)});let status=0,headers={},body='';
const response={writeHead(s,h){status=s;headers=h},end(b){body=b?.toString()||''}};
const served=shell.serveShellScript({method:'GET',url:'/__sniper_studio_review_ui.js'},response);
const no=shell.serveShellScript({method:'GET',url:'/api/projects/studio/preview'},response);
console.log(JSON.stringify({served,no,status,headers,body}));`;
  const result = JSON.parse(await runStudioCommand(process.execPath, ["-e", code]));
  assert.equal(result.served, true); assert.equal(result.no, false);
  assert.equal(result.status, 200);
  assert.equal(result.headers["Content-Type"], "text/javascript; charset=utf-8");
  assert.equal(Number(result.headers["Content-Length"]), Buffer.byteLength(result.body));
});
