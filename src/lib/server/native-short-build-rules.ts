/**
 * The native Short build's cheap structural rules (MASTER-PLAN M-068, P2-03; review X128 m2), moved out of
 * `native-short-project.ts` so assembly and the reveal probe's plan-JSON path apply the same rules with the same
 * text. The texts are the build's, unchanged. Nothing here reads footage: `assertNativeAssetRow` hashes only the
 * one asset it is given, and the others read strings.
 */
import { lstatSync, realpathSync } from "node:fs";
import path from "node:path";
import { fileSha256 } from "./auto-edit-hash";
import { nativeExtensionMount, type NativeCanvasInput } from "./native-short-composition";
import type { NativeSceneExtension } from "./native-short-project";
import type { NativeAssetBinding } from "./native-short-strategy";

/** The root timeline's opening statement; assembly appends the extension's motion right after it. */
const TIMELINE = "const tl=gsap.timeline({paused:true});";
/** Roles a bound asset may have. */
const ASSET_ROLES = ["source", "supporting-video", "image", "runtime", "reference"];

/**
 * Refuse a scene extension whose parts are not strings of at most 128 KiB, whose markup holds a script, frame or
 * audio element, or whose motion holds a script element.
 * @param extension the plan's scene extension
 */
export function assertNativeSceneExtension(extension: NativeSceneExtension): void {
  if (Object.values(extension).some((value) => typeof value !== "string" || value.length > 128 * 1024)
      || /<\/?(?:script|iframe|audio)\b/iu.test(extension.markup)
      || /<\/?script\b/iu.test(extension.motion)) throw new Error("Native scene extension contains an unsupported script, audio or frame element");
}

/**
 * Mount a scene extension into built canvas HTML exactly as assembly does: its CSS before `</head>`, its markup
 * before the caption mounting point, its motion at the start of the root timeline.
 * @param html `buildNativeCanvas` output
 * @param canvas the canvas that HTML was built from
 * @param extension the plan's scene extension
 * @returns the assembled HTML
 */
export function mountNativeSceneExtension(html: string, canvas: NativeCanvasInput, extension: NativeSceneExtension): string {
  // Never assume caption-0-0 exists: a suppressed opening has no first caption element.
  const caption = nativeExtensionMount(canvas);
  if (extension.markup && !html.includes(caption)) throw new Error("Native extension needs the shared caption mounting point");
  return html.replace("</head>", `${extension.css}</head>`)
    .replace(caption, extension.markup + caption)
    .replace(TIMELINE, TIMELINE + extension.motion);
}

/**
 * Every element id of assembled HTML, in order; refuses a duplicate id, and a remote or `references/` URL.
 * @param html assembled HTML
 * @returns the ids
 */
export function nativeProjectIds(html: string): string[] {
  const ids = [...html.matchAll(/\sid="([^"]+)"/gu)].map((match) => match[1]);
  if (new Set(ids).size !== ids.length) throw new Error("Native extension duplicates a shared element identity");
  if (/(?:src|href)=["'](?:https?:|\/\/|references\/)|url\(["']?(?:https?:|\/\/|references\/)/iu.test(html)) {
    throw new Error("Native project must use staged local assets; reference pixels cannot become production footage");
  }
  return ids;
}

/**
 * Refuse a staged catalog file that the assembled HTML does not mount.
 * @param html assembled HTML
 * @param files staged catalog files by project path (`nativeCatalogFiles`)
 */
export function assertCatalogFilesMounted(html: string, files: Record<string, string>): void {
  for (const file of Object.keys(files)) {
    if (!html.includes(`data-composition-src="${file}"`)) throw new Error("Catalog file must be mounted in the authored scene");
  }
}

/**
 * One bound asset by the build's rule: a safe `assets/` or `references/` name, a known role, and an absolute,
 * canonical (unlinked) regular file whose bytes hash to the binding.
 * @param asset the plan's binding
 */
export function assertNativeAssetRow(asset: NativeAssetBinding): void {
  if (!/^(assets|references)\/[a-zA-Z0-9][a-zA-Z0-9._-]{0,140}$/u.test(asset.file) || !ASSET_ROLES.includes(asset.role)
      || !path.isAbsolute(asset.path) || realpathSync(asset.path) !== asset.path
      || !lstatSync(asset.path).isFile() || !/^[a-f0-9]{64}$/u.test(asset.sha256)
      || fileSha256(asset.path) !== asset.sha256) throw new Error(`Native asset is missing, changed or not canonical: ${asset.file}`);
}
