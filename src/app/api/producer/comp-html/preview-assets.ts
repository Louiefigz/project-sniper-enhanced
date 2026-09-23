import fs from "node:fs";
import path from "node:path";
import { createHash } from "node:crypto";

export const MOTION_DIR = path.join(process.cwd(), "templates", "motion");
const ROUTE = "/api/producer/comp-html";
const RUNTIMES: Record<string, { source: string; type: string }> = {
  gsap: { source: "/vendor/gsap/gsap.min.js", type: "text/javascript; charset=utf-8" },
  splitText: { source: "/vendor/gsap/SplitText.min.js", type: "text/javascript; charset=utf-8" },
  drawSvg: { source: "/vendor/gsap/DrawSVGPlugin.min.js", type: "text/javascript; charset=utf-8" },
  motionTokens: { source: "/motion-tokens.js", type: "text/javascript; charset=utf-8" },
  tokens: { source: "/tokens.css", type: "text/css; charset=utf-8" },
  modulePipeline: { source: "/module-pipeline.js", type: "text/javascript; charset=utf-8" },
  agendaCaptionLayout: { source: "/agenda-caption-layout.css", type: "text/css; charset=utf-8" },
};
const IMAGE_TYPES: Record<string, string> = {
  ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg", ".webp": "image/webp",
};

function digest(bytes: Buffer): string {
  return createHash("sha256").update(bytes).digest("hex");
}

/** A lexical relative selector under one fixed root, never a filesystem URL. */
export function readPreviewAsset(root: string, name: string, maxBytes = 4 * 1024 * 1024): Buffer {
  const parts = name.split("/");
  if (/[?#%\\\u0000-\u001f\u007f]/u.test(name)
      || parts.some((part) => !part || part === "." || part === "..")) {
    throw new Error("Forbidden preview asset path");
  }
  const file = path.join(root, ...parts);
  if (fs.realpathSync(root) !== root || fs.realpathSync(file) !== file) {
    throw new Error("Forbidden preview asset symlink or file type");
  }
  const expected = fs.statSync(file);
  if (!expected.isFile()) throw new Error("Forbidden preview asset file type");
  const fd = fs.openSync(file, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW);
  try {
    const before = fs.fstatSync(fd);
    if (before.ino !== expected.ino || before.dev !== expected.dev) throw new Error("Preview asset changed while opening");
    if (before.size > maxBytes) throw new Error("Preview asset exceeds the 4 MiB per-file limit");
    const bytes = Buffer.alloc(before.size);
    let offset = 0;
    while (offset < bytes.length) {
      const count = fs.readSync(fd, bytes, offset, bytes.length - offset, offset);
      if (!count) throw new Error("Preview asset changed while reading");
      offset += count;
    }
    const after = fs.fstatSync(fd);
    if (before.size !== after.size || before.mtimeMs !== after.mtimeMs || before.ctimeMs !== after.ctimeMs
        || fs.realpathSync(root) !== root || fs.realpathSync(file) !== file) throw new Error("Preview asset changed while reading");
    return bytes;
  } finally { fs.closeSync(fd); }
}

function assetResponse(bytes: Buffer, type: string, sha?: string | null): Response {
  const current = digest(bytes);
  if (sha && sha !== current) return Response.json({ error: "Preview asset changed; reload the preview" },
    { status: 409, headers: { "Cache-Control": "no-store" } });
  return new Response(new Uint8Array(bytes), { headers: {
    "Content-Type": type, "X-Content-Type-Options": "nosniff", ETag: `"${current}"`,
    "Cache-Control": sha ? "public, max-age=31536000, immutable" : "no-cache",
  } });
}

/** Only these five registered runtime files may be served as executable/CSS content. */
export function serveRuntime(key: string, sha: string | null): Response {
  const entry = Object.hasOwn(RUNTIMES, key) ? RUNTIMES[key] : null;
  if (!entry) return Response.json({ error: "Unknown preview runtime" }, { status: 404 });
  try { return assetResponse(readPreviewAsset(MOTION_DIR, entry.source.slice(1)), entry.type, sha); }
  catch { return Response.json({ error: "Preview runtime is missing or unsafe" }, { status: 404 }); }
}

/** Serve image selectors only within the existing motion icons/assets roots. */
export function servePreviewImage(group: "icons" | "assets", name: string): Response {
  const type = IMAGE_TYPES[path.extname(name).toLowerCase()];
  if (!type) return Response.json({ error: "Unsupported preview image type" }, { status: 404 });
  try { return assetResponse(readPreviewAsset(path.join(MOTION_DIR, group), name), type); }
  catch { return Response.json({ error: "Preview image is missing or unsafe" }, { status: 404 }); }
}

/** Cache keys bind exact local bytes; scripts stay external and in source order. */
export function rewriteRuntimeUrls(html: string): string {
  const sources = new Map(Object.entries(RUNTIMES).map(([key, entry]) => [entry.source, key]));
  return html.replace(/(<(?:script|link)\b[^>]*\b(?:src|href)=)(["'])([^"']+)\2/gu,
    (match, prefix: string, quote: string, source: string) => {
      const key = sources.get(source);
      if (!key) return match;
      const sha = digest(readPreviewAsset(MOTION_DIR, source.slice(1)));
      return `${prefix}${quote}${ROUTE}?runtime=${key}&amp;sha=${sha}${quote}`;
    });
}

/** Opaque sandbox frames cannot fetch local APIs (Origin/CORP restrictions).
 * Embed only the fixed public runtimes; escape closing tags for HTML parsing.
 * Transport bytes differ only in slash escaping, so retain the source digest.
 */
export function inlineRuntimeAssets(html: string): string {
  const sources = new Map(Object.entries(RUNTIMES).map(([key, entry]) => [entry.source, { key, ...entry }]));
  return html.replace(/<script\b[^>]*\bsrc=(["'])([^"']+)\1[^>]*>\s*<\/script>|<link\b[^>]*\bhref=(["'])([^"']+)\3[^>]*>/gu,
    (match: string, ...groups: string[]) => {
      const scriptSource = groups[1]; const styleSource = groups[3];
      const entry = sources.get(scriptSource || styleSource);
      if (!entry) return match;
      const bytes = readPreviewAsset(MOTION_DIR, entry.source.slice(1));
      const tag = scriptSource ? "script" : "style";
      const closing = new RegExp(`</${tag}`, "giu");
      const text = bytes.toString("utf8").replace(closing, (value) => value.replace("/", "\\/"));
      return `<${tag} data-sniper-runtime="${entry.key}" data-sniper-source-sha="${digest(bytes)}">${text}</${tag}>`;
    });
}
