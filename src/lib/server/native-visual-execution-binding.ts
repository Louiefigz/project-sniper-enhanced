/** Derive strict modality evidence from the actual native HTML and staged assets. */
import { createHash } from "node:crypto";
import { canonicalJson } from "./auto-edit-hash";

export interface NativeCatalogExecutionMount {
  file: string; mountId: string; catalogId: string; sourceSha256: string;
  implementationSha256: string;
}
interface FrameRange { startFrame: number; endFrameExclusive: number }
interface ElementBinding { elementId: string; outputRange: FrameRange }
export type NativeVisualExecutionBinding =
  | { kind: "catalog"; mounts: NativeCatalogExecutionMount[] }
  | ({ kind: "media"; sourceRecordId: string; assetFile: string;
    sourceSha256: string; sourceRange: FrameRange; elementSha256: string } & ElementBinding)
  | ({ kind: "text"; visibleText: string; contentSha256: string } & ElementBinding)
  | ({ kind: "transition"; mechanism: string; configurationSha256: string } & ElementBinding)
  | { kind: "custom-native"; visibleIds: string[]; implementationSha256: string;
    outputRange: FrameRange }
  | ({ kind: "presenter"; assetFile: string; sourceSha256: string;
    sourceRange: FrameRange; elementSha256: string } & ElementBinding)
  | { kind: "omit" };

interface Candidate {
  modality: string;
  source?: { recordId?: string; sourceSha256?: string; sha256?: string;
    range?: FrameRange } | null;
}
interface Asset { file: string; sha256: string }
export interface NativeExecutionBindingContext {
  binding: unknown; candidate: Candidate; visibleIds: string[]; html: string;
  assets: Asset[]; timing: FrameRange; fps: number;
  catalogBindings: NativeCatalogExecutionMount[];
}
interface Element { opening: string; markup: string; tagName: string }

function sha256(value: string): string {
  return createHash("sha256").update(value).digest("hex");
}

function exact(value: unknown, keys: string[], label: string): Record<string, unknown> {
  if (!value || typeof value !== "object") throw new Error(`${label} must be an object`);
  const actual = Object.keys(value).sort().join("\0");
  if (actual !== [...keys].sort().join("\0")) {
    throw new Error(`${label} has unknown or missing fields`);
  }
  return value as Record<string, unknown>;
}

function attribute(tag: string, name: string): string | undefined {
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/gu, "\\$&");
  const matches = [...tag.matchAll(new RegExp(`\\s${escaped}="([^"]*)"`, "gu"))];
  if (matches.length > 1) throw new Error(`native element duplicates ${name}`);
  return matches[0]?.[1];
}

function element(html: string, id: string): Element {
  const tags = [...html.matchAll(/<([A-Za-z][A-Za-z0-9-]*)\b[^>]*>/gu)]
    .filter((match) => attribute(match[0], "id") === id);
  if (tags.length !== 1) throw new Error("native execution element is absent or duplicated");
  const opening = tags[0][0], tagName = tags[0][1], start = tags[0].index!;
  const close = `</${tagName}>`, end = html.indexOf(close, start + opening.length);
  const markup = end < 0 ? opening : html.slice(start, end + close.length);
  return { opening, markup, tagName };
}

function frameRange(item: Element, fps: number, media = false): FrameRange {
  const start = Number(attribute(item.opening, media ? "data-media-start" : "data-start") ?? "0");
  const duration = Number(attribute(item.opening, "data-duration"));
  if (![start, duration].every(Number.isFinite) || start < 0 || duration <= 0) {
    throw new Error("native execution element lacks an exact static range");
  }
  const first = start * fps, last = (start + duration) * fps;
  if (![first, last].every(Number.isSafeInteger)) {
    throw new Error("native execution element range is not frame-exact");
  }
  return { startFrame: first, endFrameExclusive: last };
}

function one(context: NativeExecutionBindingContext): Element {
  if (context.visibleIds.length !== 1) {
    throw new Error("native modality requires one exact executable element");
  }
  const item = element(context.html, context.visibleIds[0]);
  if (canonicalJson(frameRange(item, context.fps)) !== canonicalJson(context.timing)) {
    throw new Error("native execution element timing differs from its opportunity");
  }
  return item;
}

function textContent(markup: string): string {
  return markup.replace(/<[^>]+>/gu, " ")
    .replaceAll("&amp;", "&").replaceAll("&lt;", "<").replaceAll("&gt;", ">")
    .replaceAll("&quot;", '"').replaceAll("&#39;", "'").replace(/\s+/gu, " ").trim();
}

function textBinding(context: NativeExecutionBindingContext): NativeVisualExecutionBinding {
  const item = one(context), text = textContent(item.markup);
  if (!text || ["video", "audio"].includes(item.tagName)
      || attribute(item.opening, "data-composition-src")
      || attribute(item.opening, "data-transition-kind")) {
    throw new Error("native text binding does not name exact visible text");
  }
  return { kind: "text", elementId: context.visibleIds[0], outputRange: context.timing,
    visibleText: text, contentSha256: sha256(item.markup) };
}

function transitionBinding(context: NativeExecutionBindingContext): NativeVisualExecutionBinding {
  const item = one(context), mechanism = attribute(item.opening, "data-transition-kind");
  if (!mechanism) throw new Error("native transition binding lacks an executed mechanism");
  return { kind: "transition", elementId: context.visibleIds[0], outputRange: context.timing,
    mechanism, configurationSha256: sha256(item.markup) };
}

function mediaBinding(context: NativeExecutionBindingContext,
  presenter: boolean): NativeVisualExecutionBinding {
  const item = one(context), assetFile = attribute(item.opening, "src");
  if (item.tagName !== "video" || !assetFile) {
    throw new Error("native media binding must name one executed video element");
  }
  const asset = context.assets.find((row) => row.file === assetFile);
  if (!asset) throw new Error("native media binding names an unadmitted staged asset");
  const common = { elementId: context.visibleIds[0], assetFile, sourceSha256: asset.sha256,
    sourceRange: frameRange(item, context.fps, true), outputRange: context.timing,
    elementSha256: sha256(item.markup) };
  if (presenter) return { kind: "presenter", ...common };
  const source = context.candidate.source;
  const expectedSha = source?.sourceSha256 ?? source?.sha256;
  if (!source?.recordId || expectedSha !== asset.sha256
      || canonicalJson(source.range) !== canonicalJson(common.sourceRange)) {
    throw new Error("native media execution differs from its admitted candidate source");
  }
  return { kind: "media", sourceRecordId: source.recordId, ...common };
}

function customBinding(context: NativeExecutionBindingContext): NativeVisualExecutionBinding {
  if (!context.visibleIds.length) throw new Error("custom-native execution has no visible IDs");
  for (const id of context.visibleIds) {
    const item = element(context.html, id);
    if (canonicalJson(frameRange(item, context.fps)) !== canonicalJson(context.timing)) {
      throw new Error("custom-native element timing differs from its opportunity");
    }
  }
  return { kind: "custom-native", visibleIds: context.visibleIds,
    implementationSha256: sha256(context.html), outputRange: context.timing };
}

function catalogBinding(context: NativeExecutionBindingContext): NativeVisualExecutionBinding {
  const mountIds = context.catalogBindings.map(row => row.mountId);
  if (canonicalJson(mountIds) !== canonicalJson(context.visibleIds)) {
    throw new Error("native catalog binding does not own the exact mounted IDs");
  }
  for (const id of mountIds) {
    const item = element(context.html, id);
    if (canonicalJson(frameRange(item, context.fps)) !== canonicalJson(context.timing)) {
      throw new Error("native catalog mount timing differs from its opportunity");
    }
  }
  return { kind: "catalog", mounts: context.catalogBindings };
}

function expectedBinding(context: NativeExecutionBindingContext): NativeVisualExecutionBinding {
  const modality = context.candidate.modality;
  if (modality === "catalog") return catalogBinding(context);
  if (modality === "text") return textBinding(context);
  if (modality === "transition") return transitionBinding(context);
  if (modality === "custom-native") return customBinding(context);
  if (modality === "presenter") return mediaBinding(context, true);
  if (["source-footage", "supplied-broll", "external-media"].includes(modality)) {
    return mediaBinding(context, false);
  }
  if (modality === "omit") return { kind: "omit" };
  throw new Error("native execution modality is unsupported");
}

/** Require a closed binding equal to evidence derived from executable project bytes. */
export function assertNativeExecutionBinding(context: NativeExecutionBindingContext): void {
  const expected = expectedBinding(context);
  exact(context.binding, Object.keys(expected), "native modality execution binding");
  if (canonicalJson(context.binding) !== canonicalJson(expected)) {
    throw new Error(`native ${context.candidate.modality} binding differs from executable facts`);
  }
}
