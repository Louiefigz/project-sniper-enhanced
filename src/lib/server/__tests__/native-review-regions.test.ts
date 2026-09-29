/** TEST-only synthetic compositions: mount/interval/isolation contracts, never pixel or editorial proof. */
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { canonicalJson, fileSha256 } from "../auto-edit-hash";
import { deriveNativeReviewRegions, mountFrames } from "../native-review-regions";
import { readNativeShortProject, writeNativeShortProject, type NativeShortProjectInput } from "../native-short-project";
import { nativeShortFixture, refreshNativePacingFixture } from "./_native-short-project-fixture";
import { VISUAL_SOURCE_POLICY } from "@/lib/producer/visual-source-policy";
import { stampStudioHostIds } from "../native-studio-host-stamp";

const SCRIPT = `(function(){"use strict";var root=document.getElementById("ID");var vars=window.__hyperframes.getVariables();
var label=root.querySelector(".label");label.textContent=String(vars.label==null?"Before":vars.label);
var tl=gsap.timeline({paused:true,defaults:{force3D:false}});
tl.fromTo(label,{opacity:0},{opacity:1,duration:.3,immediateRender:false},0);window.__timelines["ID"]=tl;})();`;
const CSS = "@font-face{font-family:Inter;src:url(\"assets/Inter-Bold.ttf\")}#ID .label{position:absolute;top:400px;font-size:40px;color:#fff}";

function composition(id: string, options: { css?: string; script?: string; markup?: string } = {}): string {
  return `<!doctype html><html data-composition-id="${id}"><head><title>TEST</title></head><body><template>
<style>${(options.css ?? CSS).replaceAll("ID", id)}</style>
<div id="${id}" data-composition-id="${id}" data-width="1080" data-height="1920" data-duration="2">${options.markup ?? "<p class=\"label\">Before</p>"}</div>
<script src="assets/gsap.min.js"></script><script>${(options.script ?? SCRIPT).replaceAll("ID", id)}</script>
</template></body></html>`;
}

function host(id: string, start: string, duration: string, style = "position:absolute;inset:0"): string {
  return `<div id="${id}" class="clip" data-composition-id="${id}" data-composition-src="compositions/${id}.html" `
    + `data-start="${start}" data-duration="${duration}" data-width="1080" data-height="1920" style="${style}"></div>`;
}

function page(markup: string, css = "*{box-sizing:border-box}", script = "const tl=gsap.timeline({paused:true});"): string {
  return `<!doctype html><html><head><style>${css}</style></head><body><div id="native-canvas" data-composition-id="native-canvas" `
    + `data-duration="10">${markup}<p id="caption-0-0" class="clip text caption" data-start="0" data-duration="1">Word</p></div>`
    + `<script src="assets/gsap.min.js"></script><script>${script}</script></body></html>`;
}

const CANVAS = { frameRate: "30/1", totalFrames: 300 };
function derive(markup: string, files: Record<string, string>, css?: string, script?: string) {
  return deriveNativeReviewRegions(page(markup, css, script), files, CANVAS);
}
function pair(overrides: Record<string, string> = {}) {
  return { "compositions/card-a.html": composition("card-a"), "compositions/card-b.html": composition("card-b"), ...overrides };
}
const TWO = host("card-a", "0", "2") + host("card-b", "4", "2");

test("frame vectors match the pinned runtime render-seek rule shared with Python", () => {
  const file = path.join(process.cwd(), "scripts/producer/tests/fixtures/native_review_region_frames.json");
  for (const row of JSON.parse(readFileSync(file, "utf8")).vectors) {
    assert.deepEqual(mountFrames({ "data-start": row.start, "data-duration": row.duration }, row.rate) ?? null, row.frames, row.start);
  }
});

test("scoped compositions map exactly and a local style edit keeps the global digest", () => {
  const before = derive(TWO, pair())!;
  assert.deepEqual(before.units.map(row => [row.id, row.startFrame, row.endFrame, row.isolation.status]),
    [["card-a", 0, 60, "scoped"], ["card-b", 120, 180, "scoped"]]);
  const local = derive(TWO, pair({ "compositions/card-b.html": composition("card-b", { css: CSS.replace("40px", "48px") }) }))!;
  assert.deepEqual(local.units.map(row => row.isolation), before.units.map(row => row.isolation));
  const shared = derive(TWO, pair({ "compositions/card-b.html": composition("card-b", { css: `${CSS}@keyframes pop{to{opacity:1}}` }) }))!;
  assert.equal(shared.units[0].isolation.status, "scoped");
  assert.notDeepEqual(shared.units[1].isolation, before.units[1].isolation);
});

test("escaping or unproven composition mechanisms stay global", () => {
  const cases: Record<string, Record<string, string>> = {
    sibling: { css: `${CSS}#ID ~ .other{color:red}` },
    important: { css: `${CSS}#ID .label{color:red!important}` },
    visibility: { css: `${CSS}#ID .label{visibility:visible}` },
    compilerAttribute: { css: `${CSS}[data-composition-id="x"] .label{color:red}` },
    windowDocument: { script: "window.document.body.style.background='red';" },
    stringTween: { script: "var tl=gsap.timeline({paused:true});tl.to('.label',{x:1});window.__timelines['ID']=tl;" },
    hostTween: { script: "var root=document.getElementById('ID');var tl=gsap.timeline();tl.to(root,{x:1});" },
    foreignTimeline: { script: "var tl=gsap.timeline();window.__timelines['native-canvas']=tl;" },
    nestedMount: { markup: "<div data-composition-src=\"compositions/other.html\"></div>" },
    hoistedLink: { markup: "<link rel=\"stylesheet\" href=\"assets/x.css\">" },
    rootIdCollision: { markup: "<p id=\"caption-0-0\" class=\"label\">Before</p>" },
    handler: { markup: "<p class=\"label\" onclick=\"x()\">Before</p>" },
    timedChild: { markup: "<p class=\"label\" data-start=\"1\">Before</p>" },
  };
  for (const [name, options] of Object.entries(cases)) {
    const map = derive(TWO, pair({ "compositions/card-b.html": composition("card-b", options) }))!;
    assert.equal(map.units.find(row => row.id === "card-b")?.isolation.status, "global", name);
  }
  const relative = derive(host("card-a", "0", "2") + host("card-b", "4", "2", "position:relative"), pair())!;
  assert.equal(relative.units[1].isolation.status, "global");
  const duplicate = derive(TWO + "<div data-composition-id=\"card-b\"></div>", pair())!;
  assert.equal(duplicate.units[1].isolation.status, "global");
});

test("document visibility control anywhere blocks every scoped verdict", () => {
  const global = (map: ReturnType<typeof derive>) => map!.units.every(row => row.isolation.status === "global");
  assert.ok(global(derive(TWO, pair(), "*{box-sizing:border-box}.caption{visibility:visible}")));
  assert.ok(global(derive(TWO, pair(), undefined, "tl.set('#caption-0-0',{visibility:'visible'});")));
  const keyframes = composition("card-b", { css: `${CSS}@keyframes show{to{visibility:visible}}` });
  assert.ok(global(derive(TWO, pair({ "compositions/card-b.html": keyframes }))));
});

test("only unique, root-clock, frame-exact mounts inside the clock are mapped", () => {
  assert.equal(derive(`<section data-start="1">${host("card-a", "0", "2")}</section>`, pair()), undefined);
  assert.equal(derive(host("card-a", "0", "2") + host("card-a", "4", "2"), pair()), undefined);
  assert.equal(derive(host("card-a", "1e1", "2"), pair()), undefined);
  assert.equal(derive(host("card-a", "9", "2"), pair()), undefined);
  assert.equal(deriveNativeReviewRegions(page(TWO), pair(), { frameRate: "30000/1001", totalFrames: 300 }), undefined);
  assert.deepEqual(derive(host("card-a", "0", "2") + host("card-x", "4", "2"), pair())!.units.map(row => row.id), ["card-a"]);
});

function catalogProject(directory: string): NativeShortProjectInput {
  const input = nativeShortFixture(directory), policy = VISUAL_SOURCE_POLICY.integrated["count-up"];
  const source = path.join(directory, "card.html"), file = "compositions/card.html";
  writeFileSync(source, stampStudioHostIds(composition("card")));
  input.catalogFiles = [{ file, path: source, sha256: fileSha256(source)!, catalogId: "count-up", sourceSha256: policy.upstreamSha256 }];
  input.catalogTitle = { file, copy: input.canvas.titleCard!.copy };
  delete input.canvas.titleCard;
  input.extension = { markup: stampStudioHostIds(host("card", "0", "1").replace('class="clip"', 'class="clip" data-track-index="1"')), css: "", motion: "" };
  refreshNativePacingFixture(input);
  return input;
}

function rewriteManifestFile(directory: string, name: string, drop = false): void {
  const file = path.join(directory, "PROJECT-MANIFEST.json"), manifest = JSON.parse(readFileSync(file, "utf8"));
  manifest.files = drop ? manifest.files.filter((row: { file: string }) => row.file !== name)
    : manifest.files.map((row: { file: string }) => row.file === name ? { ...row, sha256: fileSha256(path.join(directory, name)) } : row);
  writeFileSync(file, canonicalJson(manifest));
}

test("writer derives REVIEW-REGIONS.json and the cold reader round-trips and rejects edits", () => {
  const directory = realpathSync(mkdtempSync(path.join(os.tmpdir(), "sniper-review-regions-")));
  try {
    const input = catalogProject(directory);
    const built = writeNativeShortProject(input, path.join(directory, "project"));
    assert.ok(built.manifest.files.some((row: { file: string }) => row.file === "REVIEW-REGIONS.json"));
    const regions = JSON.parse(readFileSync(path.join(built.directory, "REVIEW-REGIONS.json"), "utf8"));
    assert.deepEqual(regions.units.map((row: { id: string; startFrame: number; endFrame: number; isolation: { status: string } }) =>
      [row.id, row.startFrame, row.endFrame, row.isolation.status]), [["card", 0, 25, "scoped"]]);
    assert.deepEqual(readNativeShortProject(built.directory), input);
    const file = path.join(built.directory, "REVIEW-REGIONS.json");
    writeFileSync(file, canonicalJson({ ...regions, units: [{ ...regions.units[0], endFrame: 24 }] }));
    rewriteManifestFile(built.directory, "REVIEW-REGIONS.json");
    assert.throws(() => readNativeShortProject(built.directory), /review region map differs/);
    rewriteManifestFile(built.directory, "REVIEW-REGIONS.json", true);
    assert.throws(() => readNativeShortProject(built.directory), /omits or duplicates/);
    const authored = { ...input, reviewRegions: regions } as NativeShortProjectInput;
    assert.throws(() => writeNativeShortProject(authored, path.join(directory, "authored")), /derived from the executable mounts/);
  } finally { rmSync(directory, { recursive: true, force: true }); }
});

test("retained catalog-adaptation script patterns are provably confined; escapes are not", async () => {
  const { assertConfinedCompositionScript } = await import("../native-composition-script-validator");
  const allowed = [
    `(function(){"use strict";var root=document.getElementById("card");var vars=window.__hyperframes.getVariables();
     function num(key,fallback){return Number(vars[key]==null?fallback:vars[key]);}
     var tl=gsap.timeline({paused:true,defaults:{force3D:false}});var names=["a","b"];
     names.forEach(function(name,i){var leaf=root.querySelector(".leaf-"+i),path=root.querySelector(".path-"+i);
       var length=path.getTotalLength();path.style.strokeDasharray=String(length);leaf.textContent=name;
       tl.fromTo(path,{strokeDashoffset:length},{strokeDashoffset:0,duration:.35,immediateRender:false},num("cue"+i,1));});
     tl.fromTo(root.querySelector(".lockup"),{scale:.96},{scale:1,duration:.2},0);window.__timelines["card"]=tl;})();`,
    `(function(){var root=document.getElementById("card"),NS="http://www.w3.org/2000/svg",svg=root.querySelector("svg");
     var tl=gsap.timeline({paused:true});var nodes=[{"x":1,"label":"A"}];
     function node(item,i){var g=document.createElementNS(NS,"g"),p=document.createElementNS(NS,"path");
       g.setAttribute("transform","translate("+item.x+" 0)");p.setAttribute("d","M0 0 L"+Math.sin(i)+" 1");g.appendChild(p);
       svg.appendChild(g);var label=document.createElement("div");label.className="label";label.textContent=nodes[i].label;
       tl.set(p,{opacity:0},0);tl.fromTo([label,p],{opacity:0},{opacity:1},0.1);}
     nodes.forEach(node);window.__timelines["card"]=tl;})();`,
    `(function(){var root=document.getElementById("card");function set(selector,value){var element=root.querySelector(selector),next=[];
     for(var i=0;i<value.length;i++){var span=document.createElement("span");span.textContent=value.charAt(i);next.push(span);}
     element.replaceChildren.apply(element,next);}set(".n","42");
     var parts="a-b".split(/(\\S+-\\S+)/g);var h=root.querySelector(".h");h.replaceChildren();
     parts.forEach(function(part){var n=part.includes("-")?document.createElement("span"):document.createTextNode(part);h.appendChild(n);});})();`,
  ];
  for (const source of allowed) assert.doesNotThrow(() => assertConfinedCompositionScript(source, ["card"]));
  const escapes = ["var root=document.getElementById('card');root.parentNode.style.opacity=0;",
    "var tl=gsap.timeline();gsap.globalTimeline.add(tl);", "var x=Date.now();", "setTimeout(function(){},1);",
    "var vars=window.__hyperframes.getVariables();var k='constructor';vars[k].assign({}, {});",
    "var el=document.getElementById('card').querySelector('.a');el.setAttribute('style','color:red');",
    "var el=document.getElementById('card').querySelector('.a');el.style.setProperty('visibility','visible');",
    "new Function('return this')();", "var s=document.createElement('style');",
    "var other=document.getElementById('native-canvas');other.querySelector('.caption').textContent='x';",
    "var id='card';var root=document.getElementById(id);root.querySelector('.a').textContent='x';",
    "var tl=gsap.timeline();tl.set(document.querySelector('.a').querySelector('.b'),{x:1});"];
  for (const source of escapes) assert.throws(() => assertConfinedCompositionScript(source, ["card"]), /not provably isolated/, source);
});
