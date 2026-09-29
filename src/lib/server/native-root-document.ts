/**
 * The native root document skeleton (MASTER-PLAN M-068, P2-EARLY-CHECKS P2-03).
 *
 * One HTML shell with two users: `buildNativeCanvas` fills it with footage, shapes, text, the title card and
 * captions; the runtime reveal probe fills it with the plan's catalog mounts only. Both therefore load the same
 * pinned GSAP, the same Inter face, the same canvas geometry and the same root timeline registration, byte for
 * byte (DRY). The skeleton is the text `native-short-composition.ts` emitted before this file existed.
 */

/** What a caller places into the shared skeleton; every string is already valid, escaped markup. */
export interface NativeRootDocumentParts {
  /** The `<title>` text, already HTML-escaped. */
  title: string;
  /** A validated CSS color for the page and the canvas. */
  background: string;
  /** `@font-face` rules placed after the always-loaded Inter Bold face. */
  fontFaces: string;
  /** Markup placed at the end of `<head>` (a scene extension's CSS). */
  head: string;
  /** The exact `num/den` frame clock. */
  frameRate: string;
  /** Output length in frames. */
  totalFrames: number;
  /** Markup inside `#native-canvas`. */
  content: string;
  /** Timeline statements placed after `const tl=gsap.timeline({paused:true});`. */
  timeline: string;
}

/**
 * Seconds of a frame index on the exact `num/den` clock.
 * @param frame frame index (or count)
 * @param frameRate `num/den` frames per second
 * @returns `frame * den / num`
 */
export function nativeFrameSeconds(frame: number, frameRate: string): number {
  const [num, den] = frameRate.split("/").map(Number); return frame * den / num;
}

/**
 * The root document with its parts in place; the caller validates every part before it gets here.
 * @param parts escaped markup, style and script text for the skeleton
 * @returns the complete `index.html` text
 */
export function nativeRootDocument(parts: NativeRootDocumentParts): string {
  const duration = nativeFrameSeconds(parts.totalFrames, parts.frameRate);
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><title>${parts.title}</title><script src="assets/gsap.min.js"></script>
<style>@font-face{font-family:Inter;src:url('assets/Inter-Bold.ttf');font-weight:700;font-display:block}${parts.fontFaces}
*{box-sizing:border-box}body{margin:0;background:${parts.background}}#native-canvas{position:relative;width:1080px;height:1920px;overflow:hidden;background:${parts.background};font-family:Inter}.crop{position:absolute;overflow:hidden}.shape,.text{position:absolute}.text{white-space:pre-line;overflow-wrap:normal}.caption{z-index:8}.hook{z-index:5}</style>${parts.head}</head>
<body><div id="native-canvas" data-hf-id="hf-native-canvas" data-composition-id="native-canvas" data-width="1080" data-height="1920" data-fps="${1 / nativeFrameSeconds(1, parts.frameRate)}" data-duration="${duration}">
${parts.content}</div><script>const tl=gsap.timeline({paused:true});${parts.timeline}
tl.to({}, {duration:${duration}}, 0);window.__timelines=window.__timelines||{};window.__timelines["native-canvas"]=tl;</script></body></html>\n`;
}
