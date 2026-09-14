/** Shared native authoring primitives for source-bound visual qualification. */
import { aspectK } from "@/lib/producer/crop-geometry";
import { assertNativeCaptionGroups, nativeCaptionGroupEnd, type NativeCaptionGroups } from "./guided-native-captions";
import type { ProposalWordOccurrence } from "./guided-proposal-speech";
import { renderNativeTitleCard, type NativeTitleCard } from "./native-title-card";
import { assertNativeCaptionPresentation, nativeCaptionDisplayMap, type NativeCaptionDisplayCorrection } from "./native-caption-display";

export type NativeBox = [number, number, number, number];
export interface NativeWindow { startFrame: number; endFrame: number }
export interface NativePictureView extends NativeWindow { crop: NativeBox; box: NativeBox }
export interface NativeTypeStyle {
  size: number; weight: 400 | 700; color: string; background: string;
  align: "left" | "center"; padding: number; radius: number; lineHeight: number;
}
export interface NativeTextCue extends NativeWindow {
  id: string; text: string; box: NativeBox; style: NativeTypeStyle; role: "hook" | "label" | "explanation";
}
export interface NativeCaptionView extends NativeWindow {
  box: NativeBox; style: NativeTypeStyle; activeColor?: string; strokeColor?: string;
}
export interface NativeShapeCue extends NativeWindow {
  id: string; box: NativeBox; fill: string; border: string; borderWidth: number; radius: number;
}
export interface NativeMotionCue {
  id: string; startFrame: number; durationFrames: number;
  from: { y: number; scale: number; opacity: number };
  to: { y: number; scale: number; opacity: number };
  ease: "power2.out" | "power4.out" | "back.out(1.8)";
}
export interface NativeCanvasInput {
  title: string; frameRate: string; totalFrames: number; background: string;
  sourceSize: { w: number; h: number }; sourceFile: string;
  cuts: Array<{ start: number; end: number; speed: number }>;
  segments: Array<{ startFrame: number; endFrameExclusive: number }>;
  occurrences: ProposalWordOccurrence[]; captionGroups: NativeCaptionGroups;
  captionCorrections?: NativeCaptionDisplayCorrection[];
  /** Existing source pixels own captions only when explicitly declared and visually reviewed. */
  captionMode?: "native" | "source-burned";
  pictureViews: NativePictureView[]; captionViews: NativeCaptionView[];
  text: NativeTextCue[]; shapes: NativeShapeCue[]; motion: NativeMotionCue[];
  titleCard?: NativeTitleCard;
}

const escape = (value: string) => value.replaceAll("&", "&amp;").replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#39;");
const identity = (id: string) => `id="${id}" data-hf-id="hf-${id}"`;
const geometry = ([x, y, width, height]: NativeBox) => `left:${x}px;top:${y}px;width:${width}px;height:${height}px;`;
function seconds(frame: number, frameRate: string): number {
  const [num, den] = frameRate.split("/").map(Number); return frame * den / num;
}
function timing(row: NativeWindow, input: NativeCanvasInput): string {
  return `data-start="${seconds(row.startFrame, input.frameRate)}" data-duration="${seconds(row.endFrame - row.startFrame, input.frameRate)}"`;
}

/**
 * Prevent an outgoing layer leaking onto its successor's first frame.
 * For video, target its containing element: the exact-frame renderer may
 * display a sibling image that does not inherit the video's own clip path.
 */
export function nativeVisualExit(id: string, endFrame: number, frameRate: string): string {
  if (!/^[a-z][a-z0-9-]{0,95}$/u.test(id) || !Number.isSafeInteger(endFrame) || endFrame < 1
      || !/^\d+\/\d+$/u.test(frameRate) || !Number.isFinite(seconds(1, frameRate))
      || seconds(1, frameRate) <= 0) throw new Error("Invalid native visual exit");
  // Rewinding an implicit `none` becomes inset(0%) in GSAP. Initialize the same
  // mask forward and backward so rounded edges use identical rasterization.
  return `tl.set("#${id}",{clipPath:"inset(0%)"},0);tl.set("#${id}",{clipPath:"inset(100%)"},${seconds(endFrame, frameRate)});`;
}

function exits(input: NativeCanvasInput): string {
  const result = [...input.text, ...input.shapes].map((row) => nativeVisualExit(row.id, row.endFrame, input.frameRate));
  if (input.titleCard) result.push(nativeVisualExit("native-title-card", input.titleCard.endFrame, input.frameRate));
  input.segments.forEach((segment, index) => input.pictureViews.forEach((view, number) => {
    const end = Math.min(segment.endFrameExclusive, view.endFrame);
    if (end > Math.max(segment.startFrame, view.startFrame)) result.push(nativeVisualExit(`source-crop-${index}-${number}`, end, input.frameRate));
  }));
  input.captionGroups.forEach((group, index) => input.captionViews.forEach((view, number) => {
    const end = captionEnd(input, index, view);
    if (end > Math.max(input.occurrences[group[0]][3], view.startFrame)) result.push(nativeVisualExit(`caption-${index}-${number}`, end, input.frameRate));
  }));
  return result.join("\n");
}

/** Rounded word bounds may overlap; the next phrase owns its first visible frame. */
function captionEnd(input: NativeCanvasInput, index: number, view: NativeCaptionView): number {
  return Math.min(nativeCaptionGroupEnd(input, index), view.endFrame);
}
function color(value: string): void {
  if (!/^#[0-9a-f]{6}$/iu.test(value) && value !== "transparent") throw new Error("Native color must be exact hex or transparent");
}
function box(value: NativeBox, size: { w: number; h: number }): void {
  if (value.length !== 4 || value.some((x) => !Number.isFinite(x) || x < 0)
      || !value[2] || !value[3] || value[0] + value[2] > size.w + .01 || value[1] + value[3] > size.h + .01) throw new Error("Native rectangle escapes its actual canvas/source");
}
function window(row: NativeWindow, input: NativeCanvasInput): void {
  if (!Number.isSafeInteger(row.startFrame) || !Number.isSafeInteger(row.endFrame)
      || row.startFrame < 0 || row.endFrame <= row.startFrame || row.endFrame > input.totalFrames) throw new Error("Native clip has invalid frame bounds");
}
function typography(style: NativeTypeStyle): string {
  color(style.color); color(style.background);
  if (![400, 700].includes(style.weight) || !["left", "center"].includes(style.align)
      || style.size < 24 || style.size > 180 || style.lineHeight < 1 || style.lineHeight > 1.6
      || ![style.size, style.padding, style.radius, style.lineHeight].every(Number.isFinite)
      || style.padding < 0 || style.padding > 60 || style.radius < 0 || style.radius > 80) throw new Error("Native type values exceed their supported bounds");
  return `font:${style.weight} ${style.size}px/${style.lineHeight} Inter;color:${style.color};background:${style.background};text-align:${style.align};padding:${style.padding}px;border-radius:${style.radius}px;`;
}

function validate(input: NativeCanvasInput): void {
  assertNativeCaptionGroups(input.captionGroups, input);
  assertNativeCaptionPresentation(input);
  if (!/^\d+\/\d+$/u.test(input.frameRate) || !Number.isFinite(seconds(1, input.frameRate))
      || seconds(1, input.frameRate) <= 0 || !Number.isSafeInteger(input.totalFrames) || input.totalFrames < 1 || input.totalFrames > 60000) throw new Error("Invalid native frame clock");
  if (!/^assets\/[a-f0-9]{64}\.mp4$/u.test(input.sourceFile)) throw new Error("Native source needs a content-addressed local asset");
  color(input.background);
  if (![input.sourceSize.w, input.sourceSize.h].every((x) => Number.isFinite(x) && x >= 1 && x <= 16384)
      || input.pictureViews.length > 128 || input.captionViews.length > 128 || input.motion.length > 128) throw new Error("Native source/visual inventory exceeds its bounds");
  const cues = [...input.text, ...input.shapes], ids = cues.map((row) => row.id);
  if (cues.length > 128 || new Set(ids).size !== ids.length || ids.some((id) => !/^[a-z][a-z0-9-]{0,63}$/u.test(id)
      || /^(native-|source-|dialogue-|caption-|word-)/u.test(id))) throw new Error("Native visual IDs collide or exceed bounds");
  for (const row of [...cues, ...input.captionViews, ...input.pictureViews]) {
    window(row, input); box(row.box, { w: 1080, h: 1920 });
  }
  if (input.cuts.length !== input.segments.length) throw new Error("Native cuts and frame partitions differ");
  input.occurrences.forEach((word, index) => {
    const segment = input.segments[word[1]];
    if (word.length !== 7 || word[0] !== index || !segment || ![word[1], word[2], word[3], word[4]].every(Number.isSafeInteger)
        || word[2] < 0 || word[3] < segment.startFrame || word[4] > segment.endFrameExclusive || word[4] <= word[3]
        || word[6] !== 0 || typeof word[5] !== "string" || !word[5].trim() || word[5].length > 200) {
      throw new Error("Native word occurrence is malformed, clipped or outside its source cut");
    }
  });
  let next = 0;
  for (const segment of input.segments) {
    if (segment.startFrame !== next) throw new Error("Native source partitions are reordered or incomplete");
    next = segment.endFrameExclusive;
  }
  for (const view of input.pictureViews) {
    box(view.crop, input.sourceSize);
    const ratio = (view.crop[2] / input.sourceSize.w) / (view.crop[3] / input.sourceSize.h);
    if (Math.abs(ratio - aspectK({ w: view.box[2], h: view.box[3] }, input.sourceSize)) > .00001) throw new Error("Native crop would stretch or contain the presenter");
  }
  for (const motion of input.motion) {
    const target = cues.find((cue) => cue.id === motion.id);
    if (!target || !Number.isSafeInteger(motion.startFrame) || !Number.isSafeInteger(motion.durationFrames) || motion.durationFrames < 1
        || motion.startFrame < target.startFrame || motion.startFrame + motion.durationFrames > target.endFrame
        || !["power2.out", "power4.out", "back.out(1.8)"].includes(motion.ease)) throw new Error("Native motion lacks a valid visible target/window");
    for (const pose of [motion.from, motion.to]) {
      if (![pose.y, pose.scale, pose.opacity].every(Number.isFinite) || Math.abs(pose.y) > 1920
          || pose.scale < .1 || pose.scale > 2 || pose.opacity < 0 || pose.opacity > 1) throw new Error("Native pose exceeds finite bounds");
    }
  }
}

function footage(input: NativeCanvasInput): string {
  return input.segments.map((segment, index) => {
    const cut = input.cuts[index], span = { startFrame: segment.startFrame, endFrame: segment.endFrameExclusive };
    window(span, input);
    if (cut.speed !== 1 || ![cut.start, cut.end].every(Number.isFinite) || cut.start < 0 || cut.end <= cut.start
        || Math.abs(seconds(span.endFrame - span.startFrame, input.frameRate) - (cut.end - cut.start)) > seconds(1, input.frameRate)) throw new Error("Native source cut must preserve a valid speed-1 interval");
    const audio = `<audio ${identity(`dialogue-${index}`)} class="clip" src="${input.sourceFile}" ${timing(span, input)} data-media-start="${cut.start}" data-track-index="10" data-volume="1"></audio>`;
    const video = input.pictureViews.map((view, number) => {
      const startFrame = Math.max(span.startFrame, view.startFrame), endFrame = Math.min(span.endFrame, view.endFrame);
      if (endFrame <= startFrame) return "";
      const [x, y, width] = view.crop, scale = view.box[2] / width;
      return `<div ${identity(`source-crop-${index}-${number}`)} class="crop" style="${geometry(view.box)}">`
        + `<video ${identity(`source-${index}-${number}`)} class="clip" src="${input.sourceFile}" ${timing({ startFrame, endFrame }, input)} data-media-start="${cut.start + seconds(startFrame - span.startFrame, input.frameRate)}" data-track-index="0" muted playsinline style="position:absolute;left:${-x * scale}px;top:${-y * scale}px;width:${input.sourceSize.w * scale}px;height:${input.sourceSize.h * scale}px;max-width:none"></video></div>`;
    }).join("");
    return audio + video;
  }).join("\n");
}

function captions(input: NativeCanvasInput): string {
  const display = nativeCaptionDisplayMap(input);
  if (input.captionMode === "source-burned") return "<!--native-source-caption-mount-->";
  return input.captionGroups.flatMap((group, index) => input.captionViews.map((view, number) => {
    if (view.activeColor) color(view.activeColor);
    if (view.strokeColor) color(view.strokeColor);
    const words = group.map((id) => input.occurrences[id]);
    const startFrame = Math.max(words[0][3], view.startFrame), endFrame = captionEnd(input, index, view);
    if (endFrame <= startFrame) return "";
    return `<div ${identity(`caption-${index}-${number}`)} class="clip text caption" ${timing({ startFrame, endFrame }, input)} data-track-index="8" style="${geometry(view.box)}${typography(view.style)}">`
      + words.map((word) => `<span ${identity(`word-${word[0]}-${number}`)} data-occurrence-id="${word[0]}" data-word-start-frame="${word[3]}" data-word-end-frame="${word[4]}"`
        + ` style="${view.strokeColor ? `-webkit-text-stroke:4px ${view.strokeColor};paint-order:stroke fill;` : ""}">${escape(display.get(word[0]) ?? word[5])}</span>`).join(" ") + "</div>";
  })).join("\n");
}

/** Center the speech lane independently of the title; choose its vertical position from the shot. */
export function centeredNativeCaptionView(input: NativeWindow & { top: number }): NativeCaptionView {
  return { startFrame: input.startFrame, endFrame: input.endFrame,
    box: [90, input.top, 900, 160], activeColor: "#ffe44d", strokeColor: "#111111",
    style: { size: 70, weight: 700, color: "#ffffff", background: "transparent",
      align: "center", padding: 8, radius: 0, lineHeight: 1.15 } };
}

function captionHighlights(input: NativeCanvasInput): string {
  return input.captionViews.flatMap((view, number) => {
    if (!view.activeColor) return [];
    return input.occurrences.flatMap((word) => {
      const start = Math.max(word[3], view.startFrame), end = Math.min(word[4], view.endFrame);
      if (end <= start) return [];
      const target = `#word-${word[0]}-${number}`;
      return [`tl.fromTo("${target}",{color:"${view.style.color}"},{color:"${view.activeColor}",duration:0,immediateRender:false},${seconds(start, input.frameRate)});`,
        `tl.set("${target}",{color:"${view.style.color}"},${seconds(end, input.frameRate)});`];
    });
  }).join("\n");
}

function motionPose(pose: NativeMotionCue["from"]): string {
  return JSON.stringify({ y: pose.y, scale: pose.scale, opacity: pose.opacity });
}

/** Build actual editable pixels from explicit geometry; author/critic/source binding belongs to the caller. */
export function buildNativeCanvas(input: NativeCanvasInput): string {
  validate(input);
  if (input.titleCard && input.text.some((row) => row.role === "hook")) throw new Error("Backed title replaces the old hook layer; do not stack both");
  const titleCard = input.titleCard ? renderNativeTitleCard(input.titleCard, input) : "";
  const regularFont = [...input.text, ...input.captionViews].some((row) => row.style.weight === 400)
    ? "@font-face{font-family:Inter;src:url('assets/Inter-Regular.ttf');font-weight:400;font-display:block}" : "";
  if (input.text.some((row) => typeof row.text !== "string" || !row.text.trim() || row.text.length > 1000
      || !["hook", "label", "explanation"].includes(row.role))) throw new Error("Native text cue is invalid");
  const shapes = input.shapes.map((row) => {
    color(row.fill); color(row.border);
    if (!Number.isFinite(row.borderWidth) || row.borderWidth < 0 || row.borderWidth > 12
        || !Number.isFinite(row.radius) || row.radius < 0 || row.radius > 1000) throw new Error("Native shape style is invalid");
    return `<div ${identity(row.id)} class="clip shape" ${timing(row, input)} data-track-index="2" style="${geometry(row.box)}background:${row.fill};border:${row.borderWidth}px solid ${row.border};border-radius:${row.radius}px"></div>`;
  }).join("\n");
  const text = input.text.map((row) => `<div ${identity(row.id)} class="clip text ${row.role}" ${timing(row, input)} data-track-index="3" style="${geometry(row.box)}${typography(row.style)}">${escape(row.text)}</div>`).join("\n");
  const motion = input.motion.map((row) => `tl.fromTo("#${row.id}",${motionPose(row.from)},{...${motionPose(row.to)},duration:${seconds(row.durationFrames, input.frameRate)},ease:${JSON.stringify(row.ease)},immediateRender:false},${seconds(row.startFrame, input.frameRate)});`).join("\n");
  const duration = seconds(input.totalFrames, input.frameRate);
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><title>${escape(input.title)}</title><script src="assets/gsap.min.js"></script>
<style>@font-face{font-family:Inter;src:url('assets/Inter-Bold.ttf');font-weight:700;font-display:block}${regularFont}
*{box-sizing:border-box}body{margin:0;background:${input.background}}#native-canvas{position:relative;width:1080px;height:1920px;overflow:hidden;background:${input.background};font-family:Inter}.crop{position:absolute;overflow:hidden}.shape,.text{position:absolute}.text{white-space:pre-line;overflow-wrap:normal}.caption{z-index:8}.hook{z-index:5}</style></head>
<body><div ${identity("native-canvas")} data-composition-id="native-canvas" data-width="1080" data-height="1920" data-fps="${1 / seconds(1, input.frameRate)}" data-duration="${duration}">
${footage(input)}${shapes}${text}${titleCard}${captions(input)}</div><script>const tl=gsap.timeline({paused:true});${motion}\n${captionHighlights(input)}\n${exits(input)}
tl.to({}, {duration:${duration}}, 0);window.__timelines=window.__timelines||{};window.__timelines["native-canvas"]=tl;</script></body></html>\n`;
}
