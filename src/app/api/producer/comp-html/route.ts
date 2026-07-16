import { NextRequest } from "next/server";
import fs from "fs";
import path from "path";
import { COMPS_CATALOG } from "@/lib/producer/comps-catalog";
import { dlog } from "@/lib/debug";
import { seekShim } from "./preview-shim";

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
// Extra, preview-only plumbing: tokens.css is INLINED (srcdoc iframes resolve
// "/tokens.css" against the app origin → 404) and "/icons/…" references are
// rewritten to this route's ?icon= file server. An injected message listener
// (preview-shim.ts) seeks every registered window.__timelines timeline
// ({type:"hf-seek", t}) and measures the comp's painted-content bbox for the
// drag-to-place preview ({type:"hf-measure", ts} → "hf-content-origin").

const MOTION_DIR = path.join(process.cwd(), "templates", "motion");
const COMPOSITIONS_DIR = path.join(MOTION_DIR, "compositions");
const ICONS_DIR = path.join(MOTION_DIR, "icons");
const KNOWN_KINDS = new Set(COMPS_CATALOG.map((c) => c.kind));

const ICON_TYPES: Record<string, string> = {
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".webp": "image/webp",
};

// Mirrors graphics_render._ROOT_TAG_RE / _DURATION_RE: rewrite ONLY the
// composition root's data-duration; child clips keep their ="60" sentinels.
const ROOT_TAG_RE = /<[^>]*data-composition-id="[^"]*"[^>]*>/;

function buildPreviewHtml(kind: string, spec: Record<string, unknown>, duration: number | null): string {
  const compPath = path.join(COMPOSITIONS_DIR, `${kind}.html`);
  let html = fs.readFileSync(compPath, "utf-8");

  if (duration !== null) {
    html = html.replace(ROOT_TAG_RE, (tag) => tag.replace(/data-duration="[^"]*"/, `data-duration="${duration}"`));
  }
  // Inline the brand tokens (the comps <link href="/tokens.css">).
  const tokens = fs.readFileSync(path.join(MOTION_DIR, "tokens.css"), "utf-8");
  html = html.replace(/<link[^>]*href="\/tokens\.css"[^>]*\/?>/, `<style>${tokens}</style>`);
  // Route icon fetches (static src= AND the comps' runtime "/icons/"+file
  // string concat) through this route's ?icon= file server.
  html = html.split('"/icons/').join('"/api/producer/comp-html?icon=');
  // Variables + seek listener must be defined BEFORE the comp's own script runs.
  return html.replace(/<head[^>]*>/, (m) => `${m}\n${seekShim(spec)}`);
}

function serveIcon(name: string): Response {
  if (name !== path.basename(name)) return json({ error: "Forbidden icon path" }, 403);
  const type = ICON_TYPES[path.extname(name).toLowerCase()];
  const file = path.join(ICONS_DIR, name);
  if (!type || !fs.existsSync(file)) return json({ error: `unknown icon '${name}'` }, 404);
  return new Response(new Uint8Array(fs.readFileSync(file)), {
    headers: { "Content-Type": type, "Cache-Control": "public, max-age=3600" },
  });
}

export async function GET(req: NextRequest) {
  const q = req.nextUrl.searchParams;
  const icon = q.get("icon");
  if (icon) return serveIcon(icon);

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
    return json({ error: (e as Error).message }, 500);
  }
}

function json(obj: unknown, status: number): Response {
  return new Response(JSON.stringify(obj), { status, headers: { "Content-Type": "application/json" } });
}
