// The script injected into every served comp (see route.ts): variables +
// two message handlers.
//
//   hf-seek    — drive every registered window.__timelines timeline from the
//                player's timeupdate (the original shim).
//   hf-measure — probe the comp's PAINTED-CONTENT union bbox at the requested
//                (settled) times and reply {type:"hf-content-origin", …}. The
//                render compositor pins the comp's measured CONTENT top-left
//                at entry.placement (graphics_stage._explicit_offset →
//                graphics_anchors._content_bbox), so the preview needs the
//                same origin to translate by (placement − origin) — this is
//                the layout twin of the render's nonzero-alpha probe, taken
//                at the same late fractions of the clip (0.72/0.85/0.95).
//
// Layout rects exclude soft drop-shadows that the alpha probe includes, so
// the preview origin can sit a shadow-margin inside the render's — the render
// stays the truth; this closes the content-origin error, not the shadow one.

const SHIM_BODY = String.raw`
(function () {
  var previewFailure = null;
  var previewToken = null;
  function reportHealth() {
    if (!previewToken) return;
    var count = Object.keys(window.__timelines || {}).length;
    if (!previewFailure && !count && document.readyState === "loading") return;
    parent.postMessage({ type: "hf-preview-health", token: previewToken, ready: !previewFailure && count > 0,
      error: previewFailure || (count ? null : "No animation timeline registered.") }, "*");
  }
  window.addEventListener("error", function (event) {
    var target = event.target;
    var source = target && (target.src || target.href);
    previewFailure = String(event.message || (source ? "Preview asset failed: " + source : "Preview script failed.")).slice(0, 400);
    reportHealth();
  }, true);
  window.addEventListener("unhandledrejection", function (event) {
    previewFailure = String(event.reason && event.reason.message || "Preview initialization failed.").slice(0, 400);
    reportHealth();
  });
  var SVG_SHAPES = { path: 1, rect: 1, circle: 1, ellipse: 1, line: 1, polyline: 1, polygon: 1, text: 1, tspan: 1, image: 1, use: 1 };
  function seekAll(t) {
    var tls = window.__timelines || {};
    for (var k in tls) { try { tls[k].pause().seek(Math.max(0, Number(t) || 0), true); } catch (err) {} }
  }
  function hidden(cs) {
    return cs.display === "none" || cs.visibility === "hidden" || parseFloat(cs.opacity) === 0;
  }
  function painted(el, cs, tag) {
    if (tag === "img" || tag === "video" || tag === "canvas") return true;
    if (cs.backgroundImage !== "none") return true;
    var bg = cs.backgroundColor;
    if (bg && bg !== "transparent" && bg.indexOf("rgba(0, 0, 0, 0)") !== 0) return true;
    if (cs.boxShadow && cs.boxShadow !== "none") return true;
    if (parseFloat(cs.borderTopWidth) > 0 || parseFloat(cs.borderRightWidth) > 0 ||
        parseFloat(cs.borderBottomWidth) > 0 || parseFloat(cs.borderLeftWidth) > 0) return true;
    for (var n = el.firstChild; n; n = n.nextSibling) {
      if (n.nodeType === 3 && /\S/.test(n.nodeValue)) return true;
    }
    return false;
  }
  function svgPainted(cs, tag) {
    if (tag === "image" || tag === "use" || tag === "text" || tag === "tspan") return true;
    return cs.fill !== "none" || cs.stroke !== "none";
  }
  // Union bbox (canvas px) of everything painting pixels RIGHT NOW, clamped to
  // the canvas. SVG containers are skipped (their shapes carry the paint) so a
  // full-canvas <svg> wrapper cannot inflate the union to the whole frame.
  function measureUnion(box) {
    var W = window.innerWidth, H = window.innerHeight;
    var all = document.body ? document.body.getElementsByTagName("*") : [];
    for (var i = 0; i < all.length; i++) {
      var el = all[i];
      var tag = (el.tagName || "").toLowerCase();
      if (tag === "script" || tag === "style" || tag === "link") continue;
      var isSvg = typeof SVGElement !== "undefined" && el instanceof SVGElement;
      if (isSvg && !SVG_SHAPES[tag]) continue;
      var cs = getComputedStyle(el);
      if (hidden(cs)) continue;
      if (isSvg ? !svgPainted(cs, tag) : !painted(el, cs, tag)) continue;
      var r;
      try { r = el.getBoundingClientRect(); } catch (err) { continue; }
      var x0 = Math.max(0, r.left), y0 = Math.max(0, r.top);
      var x1 = Math.min(W, r.right), y1 = Math.min(H, r.bottom);
      if (!(x1 > x0 && y1 > y0)) continue;
      box = box ? [Math.min(box[0], x0), Math.min(box[1], y0), Math.max(box[2], x1), Math.max(box[3], y1)]
                : [x0, y0, x1, y1];
    }
    return box;
  }
  window.addEventListener("message", function (e) {
    if (e.source !== parent) return;
    var d = e && e.data;
    if (!d) return;
    if (d.type === "hf-preview-status") {
      if (typeof d.token !== "string" || !d.token || d.token.length > 128) return;
      previewToken = d.token;
      reportHealth(); return;
    }
    if (d.type === "hf-seek") { seekAll(d.t); return; }
    if (d.type !== "hf-measure" || !Array.isArray(d.ts)) return;
    // SYNCHRONOUS probe loop: hyperframes comps run as PAUSED deterministic
    // timelines and may stub requestAnimationFrame (verified: rAF callbacks
    // never fire in-comp), so no frame waits — a GSAP seek applies styles
    // synchronously and getBoundingClientRect forces layout.
    var box = null;
    for (var i = 0; i < d.ts.length; i++) {
      seekAll(d.ts[i]);
      box = measureUnion(box);
    }
    parent.postMessage(
      box ? { type: "hf-content-origin", nonce: d.nonce, x0: box[0], y0: box[1], x1: box[2], y1: box[3] }
          : { type: "hf-content-origin", nonce: d.nonce, empty: true },
      "*");
  });
})();
`;

/** Variables + seek/measure listeners, injected before the comp's own script. */
export function seekShim(spec: Record<string, unknown>): string {
  // <-escape so a spec value containing "</script>" can't break out.
  const specJson = JSON.stringify(spec).replace(/</g, "\\u003c");
  return [
    "<script>",
    `window.__hyperframes = { getVariables: function () { return ${specJson}; } };`,
    SHIM_BODY.trim(),
    "</script>",
  ].join("\n");
}
