/** Match selected assets to executable elements; semantic visibility still needs review. */
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { nativePacingVisualWindows, type PacingVisualWindow } from "./native-short-pacing-observations";
import { assetUseText } from "./native-short-asset-use-origins";
import type { NativeAssetOriginReceipt, NativeAssetUseDecision, NativeAssetUseInput, NativeAssetUseSelection } from "./native-short-asset-use-types";

function attribute(tag: string, name: string): string | undefined {
  return new RegExp(`\\s${name}="([^"]*)"`, "u").exec(tag)?.[1];
}

type MediaTag = { tag: string; kind: string; id: string; file: string };

function mediaTags(html: string): MediaTag[] {
  return [...html.matchAll(/<(img|video|image|source|object|embed)\b[^>]*>/giu)].map(match => {
    const tag = match[0], kind = match[1].toLowerCase(), id = attribute(tag, "id"), file = attribute(tag, kind === "image" ? "href" : "src");
    if (!["img", "video", "image"].includes(kind) || !id || !file || /\s(?:srcset|poster)\s*=/iu.test(tag)) {
      throw new Error("Inserted media requires one explicit local source, identity and timed element");
    }
    return { tag, kind, id, file };
  });
}

function region(selection: NativeAssetUseSelection, receipt: NativeAssetOriginReceipt): void {
  const rect = selection.essentialRegion, { width, height } = receipt.record.media;
  if (!Array.isArray(rect) || rect.length !== 4 || rect.some(value => !Number.isFinite(value) || value < 0)
      || !rect[2] || !rect[3] || !width || !height || rect[0] + rect[2] > width || rect[1] + rect[3] > height) {
    throw new Error("Asset essential region must fit its recorded source pixel dimensions");
  }
  assetUseText(selection.essentialContent);
}

function sourceRange(selection: NativeAssetUseSelection, receipt: NativeAssetOriginReceipt, input: NativeAssetUseInput): void {
  const range = selection.sourceRange;
  if (!receipt.record.mime.startsWith("video/")) {
    if (range || selection.audio !== "none") throw new Error("Still image use cannot claim source video timing or audio");
    return;
  }
  const rate = typeof range?.frameRate === "string" ? range.frameRate.split("/").map(Number) : [], sourceFps = rate[0] / rate[1];
  const [num, den] = input.canvas.frameRate.split("/").map(Number), fps = num / den;
  if (!range || range.frameRate !== receipt.acquisition.sourceFrameRate || !/^\d+\/\d+$/u.test(range.frameRate) || !Number.isFinite(sourceFps) || sourceFps < 1 || sourceFps > 240
      || ![range.startSeconds, range.endSeconds].every(Number.isFinite) || range.startSeconds < 0
      || range.endSeconds <= range.startSeconds || !receipt.record.media.durationFrames
      || range.endSeconds * sourceFps > receipt.record.media.durationFrames + .00001
      || Math.abs((range.endSeconds - range.startSeconds) * fps - (selection.endFrame - selection.startFrame)) > .00001
      || selection.audio !== "muted") throw new Error("Native inserted video requires a bounded speed-1 muted source range; audible quotes need a supported handoff");
}

function attribution(selection: NativeAssetUseSelection, receipt: NativeAssetOriginReceipt): void {
  const rights = receipt.record.rights;
  if (rights.attributionRequired && (!selection.attribution || selection.attribution.text !== rights.attribution)) {
    throw new Error("Asset use lost its required source attribution");
  }
  if (selection.attribution) {
    assetUseText(selection.attribution.text); assetUseText(selection.attribution.placement);
  }
}

function selectedMedia(input: NativeAssetUseInput, decision: NativeAssetUseDecision, context: {
  media: Map<string, MediaTag>; windows: Map<string, PacingVisualWindow>; origins: Map<string, NativeAssetOriginReceipt>;
}): void {
  const selection = decision.selection!, receipt = context.origins.get(selection.assetFile);
  const media = context.media.get(selection.targetId), window = context.windows.get(selection.targetId);
  if (!receipt || !media || media.file !== selection.assetFile || !window
      || window.startFrame !== selection.startFrame || window.endFrame !== selection.endFrame) {
    throw new Error("Selected asset differs from its executable source, target or output window");
  }
  const video = receipt.record.mime.startsWith("video/");
  const videoKind = ["video", "web", "creator-excerpt"].includes(selection.kind);
  if (video !== videoKind || (video ? media.kind !== "video" : !["img", "image"].includes(media.kind))
      || (selection.kind === "web") !== (receipt.acquisition.kind === "public-web-capture")) {
    throw new Error("Selected asset kind differs from its immutable origin or media element");
  }
  if (selection.sourceIdentity !== receipt.record.provenance.source) throw new Error("Selected asset lost its recorded source identity");
  region(selection, receipt); sourceRange(selection, receipt, input); attribution(selection, receipt);
  if (video && /\sdata-playback-(?:start|rate)(?:\s|=|>)/iu.test(media.tag)) {
    throw new Error("Native speed-1 inserts cannot override source timing with playback aliases");
  }
  if (video && (!/\smuted(?:\s|>)/u.test(media.tag)
      || Number(attribute(media.tag, "data-media-start")) !== selection.sourceRange!.startSeconds)) {
    throw new Error("Executable inserted video differs from the muted source range");
  }
}

/** Keep the supported CSS subset literal; encoded resource names evade text matching. */
function assertLiteralStyles(html: string): void {
  const blocks = [...html.matchAll(/<style\b[^>]*>([\s\S]*?)<\/style>/giu)].map(row => row[1]);
  const attributes = [...html.matchAll(/\sstyle\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))/giu)]
    .map(row => row[1] ?? row[2] ?? row[3]);
  if (blocks.some(css => /\\/u.test(css)) || attributes.some(css => /[\\&]/u.test(css))) {
    throw new Error("Native CSS requires literal style syntax without CSS escapes or HTML entities");
  }
  if (/<link\b/iu.test(html) || blocks.concat(attributes).some(css => /@import\b/iu.test(css.replace(/\/\*[\s\S]*?\*\//gu, "")))) {
    throw new Error("Native CSS cannot import or link additional stylesheets");
  }
}

/** Only the shared font can load through CSS; runtime role never admits visual backgrounds. */
function assertCssSources(input: NativeAssetUseInput, html: string): void {
  assertLiteralStyles(html);
  const font = input.assets.find(asset => asset.file === "assets/Inter-Bold.ttf" && asset.role === "runtime");
  const withoutFontSources = html.replace(/<style\b[^>]*>([\s\S]*?)<\/style>/giu, style => {
    const css = style.replace(/\/\*[\s\S]*?\*\//gu, "");
    return css.replace(/@font-face\s*\{([^{}]*)\}/giu, rule => rule.replace(/((?:\{|;)\s*src\s*:)([^;{}]*)/giu,
      (declaration: string, prefix: string, value: string) => prefix + value.replace(/url\(\s*["']?([^\s"')]+)["']?\s*\)/giu,
        (url: string, file: string) => {
          if (!font || file !== font.file) throw new Error("CSS font source must be the actual shared font resource");
          return "";
        })));
  });
  if (/url\s*\(/iu.test(withoutFontSources)) throw new Error("Asset use requires explicit timed media elements instead of CSS image sources");
}

/** Every image/video branch participates; untimed CSS/poster assets cannot bypass decisions. */
export function assertNativeAssetUseMedia(input: NativeAssetUseInput, html: string, origins: Map<string, NativeAssetOriginReceipt>): void {
  const selected = input.strategy.assetUse!.decisions.filter(row => row.decision === "insert");
  const tags = mediaTags(html), ids = selected.map(row => row.selection!.targetId);
  if (new Set(ids).size !== ids.length) throw new Error("One media target has multiple contradictory use decisions");
  const primaryIds = new Set(input.canvas.segments.flatMap((segment, i) => input.canvas.pictureViews
    .flatMap((view, j) => Math.max(segment.startFrame, view.startFrame) < Math.min(segment.endFrameExclusive, view.endFrame)
      ? [`source-${i}-${j}`] : [])));
  for (const media of tags) {
    const primary = media.file === input.canvas.sourceFile && primaryIds.has(media.id);
    if (!primary && !ids.includes(media.id)) throw new Error(`Displayed asset ${media.id} lacks a speech-bound use decision`);
  }
  assertCssSources(input, html);
  if (/image-set\s*\(/iu.test(html)) throw new Error("Asset use cannot bypass timed targets with CSS image sets");
  const media = new Map(tags.map(row => [row.id, row])), windows = new Map(nativePacingVisualWindows(input, html).map(row => [row.id, row]));
  selected.forEach(decision => selectedMedia(input, decision, { media, windows, origins }));
  for (const shot of input.strategy.supportingSearch.candidates.filter(row => row.selected)) {
    const use = selected.find(row => row.selection!.targetId === shot.visibleId)?.selection;
    if (!use || canonicalJsonSha256([use.assetFile, use.startFrame, use.endFrame, use.sourceRange?.startSeconds, use.sourceRange?.endSeconds])
        !== canonicalJsonSha256([shot.assetFile, shot.startFrame, shot.endFrame, shot.sourceStart, shot.sourceEnd])) {
      throw new Error("Supporting shot and shared asset-use decision disagree");
    }
  }
}
