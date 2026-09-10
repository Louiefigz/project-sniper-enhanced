import path from "node:path";
import { createHash } from "node:crypto";
import { MOTION_DIR, readPreviewAsset } from "./preview-assets";

type DeclaredField = { id: string; type: string; default?: unknown };
export type EmbeddedMedia = { data: string; sha: string; bytes: number };
export type MediaMap = Record<string, EmbeddedMedia>;
const IMAGE_FIELDS: Record<string, string[]> = {
  "ui-focus-zoom": ["image"], "avatar-bio-card": ["avatarSrc"], "blur-tease": ["image"],
  "angela-receipt-cell": ["media1", "media2", "media3", "media4", "media5", "media6"],
};
const MAX_TOTAL_BYTES = 8 * 1024 * 1024;
const SVG_TAGS = new Set(["svg", "g", "path", "title", "desc", "defs", "lineargradient",
  "radialgradient", "stop", "clippath", "mask", "circle", "rect", "line", "ellipse",
  "polygon", "polyline", "use"]);

export class PreviewMediaError extends Error {}

/** Parse only the trusted source declaration, never arbitrary spec keys. */
function declaredFields(html: string): DeclaredField[] {
  const raw = html.match(/data-composition-variables=(["'])([\s\S]*?)\1/u)?.[2];
  if (!raw) throw new PreviewMediaError("Preview template has no variable declaration");
  const fields = JSON.parse(raw) as DeclaredField[];
  if (!Array.isArray(fields) || fields.some((field) => !field || typeof field.id !== "string")) {
    throw new PreviewMediaError("Preview template has an invalid variable declaration");
  }
  if (new Set(fields.map((field) => field.id)).size !== fields.length) {
    throw new PreviewMediaError("Preview template has duplicate variable declarations");
  }
  return fields;
}

function assertSafeSvgAttributes(tag: string): void {
  const body = tag.replace(/^<\/?[\w:-]+/u, "").replace(/\/?\s*>$/u, "");
  const attributes = /\s+([\w:.-]+)\s*=\s*(["'])([^"']*)\2/gu;
  if (body.replace(attributes, "").trim()) throw new PreviewMediaError("Preview icon has malformed SVG attributes");
  for (const match of body.matchAll(attributes)) {
    const name = match[1].toLowerCase().split(":").at(-1)!;
    if (/^on/u.test(name) || ["style", "src", "base"].includes(name)) {
      throw new PreviewMediaError("Preview icon contains an unsafe SVG attribute");
    }
  }
}

/** Conservative icon subset: no code, HTML, styles, entities, or external references. */
export function assertSafeSvg(bytes: Buffer): void {
  const svg = bytes.toString("utf8");
  if (!/^\s*<svg\b/iu.test(svg) || /<!|<\?|\son[a-z]+\s*=|\s(?:style|src)\s*=/iu.test(svg)) {
    throw new PreviewMediaError("Preview icon is not a safe standalone SVG");
  }
  if ([...svg.matchAll(/<\/?([\w:-]+)/gu)].some((match) => !SVG_TAGS.has(match[1].toLowerCase()))) {
    throw new PreviewMediaError("Preview icon contains unsupported SVG elements");
  }
  for (const tag of svg.matchAll(/<[^>]*>/gu)) assertSafeSvgAttributes(tag[0]);
  const refs = [...svg.matchAll(/(?:\b(?:xlink:)?href\s*=\s*["']([^"']*)["']|url\s*\(([^)]*)\))/giu)];
  if (refs.some((match) => !/^#[\w.-]+$/u.test((match[1] ?? match[2]).replace(/^["']|["']$/gu, "")))) {
    throw new PreviewMediaError("Preview icon contains an external or unsafe reference");
  }
}

/** Match the existing renderer's PNG/JPEG/WebP signature check. */
export function imageType(name: string, bytes: Buffer): string {
  const ext = path.extname(name).toLowerCase();
  if (ext === ".png" && bytes.subarray(0, 8).equals(Buffer.from("89504e470d0a1a0a", "hex"))) return "image/png";
  if ([".jpg", ".jpeg"].includes(ext) && bytes.subarray(0, 3).equals(Buffer.from("ffd8ff", "hex"))) return "image/jpeg";
  if (ext === ".webp" && bytes.toString("ascii", 0, 4) === "RIFF" && bytes.toString("ascii", 8, 12) === "WEBP") return "image/webp";
  throw new PreviewMediaError("Preview media must be a real PNG, JPEG, or WebP; video and media SVG previews are unsupported");
}

/** Reject alias collisions instead of silently overwriting a resolved resource. */
export function addMediaAliases(map: MediaMap, aliases: string[], media: EmbeddedMedia): void {
  for (const alias of aliases) {
    if (Object.hasOwn(map, alias) && map[alias].sha !== media.sha) {
      throw new PreviewMediaError(`Preview asset alias collision: ${alias}`);
    }
  }
  const unique = new Map([...Object.values(map), media].map((entry) => [entry.sha, entry.bytes]));
  if ([...unique.values()].reduce((sum, size) => sum + size, 0) > MAX_TOTAL_BYTES) {
    throw new PreviewMediaError("Preview assets exceed the 8 MiB combined limit");
  }
  for (const alias of aliases) map[alias] = media;
}

function selector(value: unknown, field: string): string {
  if (typeof value !== "string" || value !== value.trim()) {
    throw new PreviewMediaError(`Preview spec.${field} must be a trimmed local asset selector`);
  }
  return value;
}

function iconResource(raw: string): { name: string; aliases: string[] } {
  if (raw.startsWith("/")) throw new PreviewMediaError("Preview icon selector must be relative to motion/icons");
  const name = path.basename(raw).includes(".") ? raw : `${raw}.svg`;
  if (path.extname(name) !== ".svg") throw new PreviewMediaError("Preview icons must use .svg");
  // whiteboard-map preserves bare names; other icon templates append .svg.
  return { name, aliases: [`/icons/${name}`, `/icons/${raw}`] };
}

function imageResource(raw: string): { name: string; aliases: string[] } {
  if (!/^\/?assets\//u.test(raw)) throw new PreviewMediaError("Preview images must be local motion/assets PNG, JPEG, or WebP; videos are unsupported");
  const name = raw.replace(/^\/?assets\//u, "");
  if (![".png", ".jpg", ".jpeg", ".webp"].includes(path.extname(name).toLowerCase())) {
    throw new PreviewMediaError("Preview media SVG and video are unsupported; use a local PNG, JPEG, or WebP");
  }
  return { name, aliases: [`/assets/${name}`, `assets/${name}`] };
}

function addSelected(map: MediaMap, raw: string, icon: boolean): void {
  const group = icon ? "icons" : "assets";
  const { name, aliases } = icon ? iconResource(raw) : imageResource(raw);
  const bytes = readPreviewAsset(path.join(MOTION_DIR, group), name);
  if (icon) assertSafeSvg(bytes);
  const type = icon ? "image/svg+xml" : imageType(name, bytes);
  const sha = createHash("sha256").update(bytes).digest("hex");
  addMediaAliases(map, aliases, { data: `data:${type};base64,${bytes.toString("base64")}`, sha, bytes: bytes.length });
}

function addPreviewSample(map: MediaMap, html: string, spec: Record<string, unknown>): void {
  if (String(spec.icon ?? "").trim() || String(spec.label ?? "").trim()) return;
  // This is the only audited asset-bearing inner SAMPLE fallback, not a new catalog.
  if (!html.includes('const SAMPLE = { icon: "youtube", label: "Subscribe" };')) {
    throw new PreviewMediaError("stroke-draw-badge preview sample changed; requalify embedded assets");
  }
  addSelected(map, "youtube", true);
}

/** Build an exact per-preview resource map without changing selectors or source. */
export function buildMediaMap(html: string, kind: string, spec: Record<string, unknown>): MediaMap {
  const map: MediaMap = Object.create(null) as MediaMap;
  for (const field of declaredFields(html)) {
    const icon = field.type === "string" && /^(?:icon\d*|iconFile)$/u.test(field.id);
    const image = field.type === "string" && IMAGE_FIELDS[kind]?.includes(field.id);
    if (!icon && !image) continue;
    const raw = selector(Object.hasOwn(spec, field.id) ? spec[field.id] : field.default, field.id);
    if (!raw) continue;
    try { addSelected(map, raw, icon); }
    catch (error) { throw new PreviewMediaError(`Preview spec.${field.id}: ${(error as Error).message}`); }
  }
  if (kind === "stroke-draw-badge") addPreviewSample(map, html, spec);
  return map;
}
