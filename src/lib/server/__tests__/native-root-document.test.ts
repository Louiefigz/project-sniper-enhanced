/**
 * `nativeRootDocument` (M-068, X120; review X128 m8) is byte-identical to the skeleton `buildNativeCanvas` emitted
 * before the factoring. The oracle below is that skeleton, copied verbatim from `native-short-composition.ts` at
 * blob 27389168 (the template literal and its `seconds` helper), so a change to the clock arithmetic or the text
 * fails here. Pure strings only.
 */
import assert from "node:assert/strict";
import { test } from "node:test";
import { nativeFrameSeconds, nativeRootDocument, type NativeRootDocumentParts } from "../native-root-document";

/** The pre-factoring `seconds` (native-short-composition.ts at 27389168). */
function seconds(frame: number, frameRate: string): number {
  const [num, den] = frameRate.split("/").map(Number); return frame * den / num;
}

/** The pre-factoring skeleton, with the parts `buildNativeCanvas` placed in it (27389168, lines 269-275). */
function previousSkeleton(parts: NativeRootDocumentParts): string {
  const duration = seconds(parts.totalFrames, parts.frameRate);
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><title>${parts.title}</title><script src="assets/gsap.min.js"></script>
<style>@font-face{font-family:Inter;src:url('assets/Inter-Bold.ttf');font-weight:700;font-display:block}${parts.fontFaces}
*{box-sizing:border-box}body{margin:0;background:${parts.background}}#native-canvas{position:relative;width:1080px;height:1920px;overflow:hidden;background:${parts.background};font-family:Inter}.crop{position:absolute;overflow:hidden}.shape,.text{position:absolute}.text{white-space:pre-line;overflow-wrap:normal}.caption{z-index:8}.hook{z-index:5}</style>${parts.head}</head>
<body><div id="native-canvas" data-hf-id="hf-native-canvas" data-composition-id="native-canvas" data-width="1080" data-height="1920" data-fps="${1 / seconds(1, parts.frameRate)}" data-duration="${duration}">
${parts.content}</div><script>const tl=gsap.timeline({paused:true});${parts.timeline}
tl.to({}, {duration:${duration}}, 0);window.__timelines=window.__timelines||{};window.__timelines["native-canvas"]=tl;</script></body></html>\n`;
}

const RATES = ["25/1", "30/1", "24/1", "60/1", "24000/1001", "30000/1001", "60000/1001", "7/3", "30/2"];
const LENGTHS = [1, 7, 50, 1447, 5399, 18000];

test("nativeRootDocument equals the previous skeleton at every clock, NTSC and 7/3 included", () => {
  const parts = { title: "TEST &lt;root&gt; $&amp; `x`", background: "#0B0E12", head: "", content: '<div id="x"></div>',
    fontFaces: "@font-face{font-family:Inter;src:url('assets/Inter-Regular.ttf');font-weight:400;font-display:block}",
    timeline: 'tl.set("#x",{opacity:1},0);\n\n' };
  for (const frameRate of RATES) {
    for (const totalFrames of LENGTHS) {
      const row = { ...parts, frameRate, totalFrames };
      assert.equal(nativeRootDocument(row), previousSkeleton(row), `${frameRate} × ${totalFrames}`);
    }
  }
});

test("nativeFrameSeconds is the previous frame clock, frame by frame", () => {
  for (const frameRate of RATES) {
    for (let frame = 0; frame < 3000; frame += 1) assert.equal(nativeFrameSeconds(frame, frameRate), seconds(frame, frameRate));
  }
});

test("the probe's parts (empty timeline, extension CSS in the head) keep every other byte", () => {
  const row = { title: "Native reveal probe", background: "transparent", fontFaces: "", head: "<style>#m{z-index:4}</style>",
    frameRate: "30000/1001", totalFrames: 1447, content: '<div id="m" data-composition-src="compositions/m.html"></div>', timeline: "" };
  assert.equal(nativeRootDocument(row), previousSkeleton(row));
  assert.ok(nativeRootDocument(row).includes("</style><style>#m{z-index:4}</style></head>"));
});
