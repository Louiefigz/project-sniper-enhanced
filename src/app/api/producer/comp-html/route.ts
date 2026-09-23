import { createHash } from "node:crypto";
import { VISUAL_SOURCE_POLICY } from "@/lib/producer/visual-source-policy";
import { NextRequest } from "next/server";
import fs from "fs";
import path from "path";
import { COMPS_CATALOG } from "@/lib/producer/comps-catalog";
import { dlog } from "@/lib/debug";
import { seekShim } from "./preview-shim";
import { MOTION_DIR, inlineRuntimeAssets, servePreviewImage, serveRuntime } from "./preview-assets";
import { buildMediaMap, PreviewMediaError } from "./preview-media";
import { mediaShim } from "./preview-media-shim";

export const dynamic = "force-dynamic";

// INSTANT GRAPHICS PREVIEW source: serve one motion comp's HTML with the
// graphic's spec injected the same way graphics_render.py does for the real
// render (--variables → window.__hyperframes.getVariables()), so a sandboxed
// iframe can play the comp live over the video pane with NO re-render.
//
// Parity with scripts/producer/graphics/graphics_render.py:
//   - kind → templates/motion/compositions/<kind>.html, WHITELISTED against
//     the ELEMENTS catalog (never a generic file-read primitive);
//   - spec  → injected as the getVariables() payload (comps merge it over
//     their inline defaults exactly like a CLI render);
//   - duration → the root data-duration attribute is rewritten (same regex
//     contract as _set_root_duration: the tag carrying data-composition-id).
// Extra, preview-only plumbing: the fixed local runtime/CSS allowlist is
// safely inlined. Opaque srcdoc origins cannot fetch local API resources;
// neither the global local-request policy nor the sandbox is relaxed.
// Source files/variables are unchanged. Only declared local icon/image resources
// are embedded, with a frame-local exact URL adapter for img.src and SVG XHR.
// An injected message listener
// (preview-shim.ts) seeks every registered window.__timelines timeline
// ({type:"hf-seek", t}) and measures the comp's painted-content bbox for the
// drag-to-place preview ({type:"hf-measure", ts} → "hf-content-origin").

const COMPOSITIONS_DIR = path.join(MOTION_DIR, "compositions");
const KNOWN_KINDS = new Set(COMPS_CATALOG.map((c) => c.kind));

// Mirrors graphics_render._ROOT_TAG_RE / _DURATION_RE: rewrite ONLY the
// composition root's data-duration; child clips keep their ="60" sentinels.
const ROOT_TAG_RE = /<[^>]*data-composition-id="[^"]*"[^>]*>/;

function buildPreviewHtml(kind: string, spec: Record<string, unknown>, duration: number | null): string {
  const compPath = path.join(COMPOSITIONS_DIR, `${kind}.html`);
  let html = fs.readFileSync(compPath, "utf-8");
  const authority = VISUAL_SOURCE_POLICY.integrated[kind as keyof typeof VISUAL_SOURCE_POLICY.integrated];
  if (!authority || createHash("sha256").update(html).digest("hex") !== authority.sha256) {
    throw new Error("Catalog source changed; preview cannot relabel a replacement template");
  }
  const media = mediaShim(buildMediaMap(html, kind, spec));

  if (duration !== null) {
    html = html.replace(ROOT_TAG_RE, (tag) => tag.replace(/data-duration="[^"]*"/, `data-duration="${duration}"`));
  }
  html = inlineRuntimeAssets(html);
  // Variables + seek listener must be defined BEFORE the comp's own script runs.
  return html.replace(/<head[^>]*>/, (m) => `${m}\n${seekShim(spec)}${media}`);
}

export async function GET(req: NextRequest) {
  const q = req.nextUrl.searchParams;
  const runtime = q.get("runtime");
  if (runtime !== null) return serveRuntime(runtime, q.get("sha"));
  const icon = q.get("icon");
  if (icon) return servePreviewImage("icons", icon);
  const asset = q.get("asset");
  if (asset) return servePreviewImage("assets", asset);

  const kind = q.get("kind") || "";
  if (!KNOWN_KINDS.has(kind)) {
    return json({ error: `unknown comp kind '${kind}' — not in the ELEMENTS catalog` }, 400);
  }
  let spec: Record<string, unknown> = {};
  const rawSpec = q.get("spec");
  if (rawSpec) {
    try {
      const parsed = JSON.parse(rawSpec) as unknown;
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("spec must be a JSON object");
      spec = parsed as Record<string, unknown>;
    } catch (e) {
      return json({ error: `invalid spec: ${(e as Error).message}` }, 400);
    }
  }
  const rawDur = q.get("duration");
  const duration = rawDur !== null ? Number(rawDur) : null;
  if (duration !== null && !(Number.isFinite(duration) && duration > 0)) {
    return json({ error: `invalid duration '${rawDur}'` }, 400);
  }

  try {
    const html = buildPreviewHtml(kind, spec, duration);
    dlog("producer:comp-html", "served", { kind, bytes: html.length });
    return new Response(html, {
      headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" },
    });
  } catch (e) {
    return json({ error: (e as Error).message }, e instanceof PreviewMediaError ? 422 : 500);
  }
}

function json(obj: unknown, status: number): Response {
  return new Response(JSON.stringify(obj), { status, headers: { "Content-Type": "application/json" } });
}
