// Narrow native CSS/Range geometry observation; never pixel or legibility proof.
function box(rect) {
  const values = [rect.left, rect.top, rect.right, rect.bottom];
  if (!values.every(Number.isFinite)) throw new Error("nonfinite DOM geometry");
  return values;
}

function union(rects) {
  const nonempty = rects.filter((r) => r[2] > r[0] && r[3] > r[1]);
  if (!nonempty.length) return null;
  return [Math.min(...nonempty.map((r) => r[0])), Math.min(...nonempty.map((r) => r[1])),
    Math.max(...nonempty.map((r) => r[2])), Math.max(...nonempty.map((r) => r[3]))];
}

function fullCanvasClip(element, root, style) {
  if (![root, document.body, document.documentElement].includes(element)) return false;
  return style.overflowX === "hidden" && style.overflowY === "hidden" &&
    JSON.stringify(box(element.getBoundingClientRect())) === "[0,0,1920,1080]" &&
    element.clientWidth === 1920 && element.clientHeight === 1080 &&
    element.scrollWidth === 1920 && element.scrollHeight === 1080 &&
    element.scrollLeft === 0 && element.scrollTop === 0;
}

function paintIssues(element, root) {
  const issues = [];
  const style = getComputedStyle(element);
  const unsupported = ["filter", "backdropFilter", "clipPath", "maskImage", "textShadow", "boxShadow"];
  for (const name of unsupported) {
    if (style[name] && style[name] !== "none") issues.push(`unsupported-${name}`);
  }
  if (style.mixBlendMode !== "normal" || style.perspective !== "none") issues.push("unsupported-blending-or-perspective");
  if (style.outlineStyle !== "none" && parseFloat(style.outlineWidth) > 0) issues.push("unsupported-outline");
  if (style.textOverflow === "ellipsis" || !["none", "0", ""].includes(style.webkitLineClamp || "")) issues.push("unsupported-text-truncation");
  if ((style.overflowX !== "visible" || style.overflowY !== "visible") && !fullCanvasClip(element, root, style)) issues.push("unsupported-clipping");
  if ([document.body, document.documentElement].includes(element) && style.transform !== "none") issues.push("unsupported-outer-transform");
  if (style.clip !== "auto" || style.contain !== "none") issues.push("unsupported-clip-or-containment");
  if (parseFloat(style.webkitTextStrokeWidth || "0") !== 0) issues.push("unsupported-text-stroke");
  if (style.transform !== "none") {
    const m = new DOMMatrixReadOnly(style.transform);
    if (!m.is2D || m.b !== 0 || m.c !== 0 || m.a < 0 || m.d < 0) issues.push("unsupported-transform");
  }
  for (const pseudo of ["::before", "::after"]) {
    const content = getComputedStyle(element, pseudo).content;
    // Even empty generated content can paint an unmeasured background/border.
    if (!["none", "normal"].includes(content)) issues.push("unsupported-generated-content");
  }
  return issues;
}

function inherited(element, root) {
  let opacity = 1;
  const issues = [];
  for (let node = element; node; node = node.parentElement) {
    const style = getComputedStyle(node);
    const value = Number(style.opacity);
    if (!Number.isFinite(value) || value < 0 || value > 1) throw new Error("invalid DOM opacity");
    opacity *= value;
    if (style.display === "none" || style.visibility !== "visible") opacity = 0;
    issues.push(...paintIssues(node, root));
  }
  return { opacity, issues: [...new Set(issues)].sort() };
}

function expectedRole(element) {
  const fixed = { "ag-eyebrow": "eyebrow", "ag-title": "title", "ag-underline": "title-accent" };
  if (fixed[element.id]) return fixed[element.id];
  const row = element.closest(".ag-row");
  if (!row || !/^[1-5]$/.test(row.dataset.slot || "")) return null;
  const kinds = [["ag-chip", "marker"], ["ag-title-row", "title"], ["ag-sub", "subtitle"]];
  const kind = kinds.find(([name]) => element.classList.contains(name));
  return kind ? `step-${row.dataset.slot}-${kind[1]}` : null;
}

function pipelineRole(element, root) {
  const fixed = { "npl-eyebrow": "eyebrow", "npl-explainer": "explainer", "npl-foot": "footnote" };
  if (fixed[element.id]) return fixed[element.id];
  const lines = Array.from(root.querySelectorAll("#npl-headline > .line"));
  if (lines.includes(element)) return `headline-line-${lines.indexOf(element) + 1}`;
  const nodes = Array.from(root.querySelectorAll("#npl-chain > .npl-native-cell > .npl-node"));
  if (nodes.includes(element)) return `node-${nodes.indexOf(element) + 1}`;
  const parent = element.parentElement, index = nodes.findIndex((node) => node.parentElement === parent);
  return element.classList.contains("npl-native-link") && index >= 0 && index < nodes.length - 1 ? `connector-${index + 1}` : null;
}

function roleInventory(root, pipeline) {
  const selector = pipeline ? "#npl-eyebrow,#npl-headline > .line,#npl-explainer,#npl-chain > .npl-native-cell > .npl-node,.npl-native-link,#npl-foot"
    : "#ag-eyebrow,#ag-title,#ag-underline,.ag-chip,.ag-title-row,.ag-sub";
  const expected = Array.from(root.querySelectorAll(selector));
  const supplied = Array.from(root.querySelectorAll("[data-sniper-protected-role]"));
  const roles = expected.map((element) => ({ element, id: pipeline ? pipelineRole(element, root) : expectedRole(element), text: element.textContent }));
  const [minimum, maximum] = pipeline ? [3, 16] : [4, 12];
  if (roles.length < minimum || roles.length > maximum || supplied.length !== roles.length) throw new Error("native role coverage is incomplete");
  if (new Set(roles.map((r) => r.id)).size !== roles.length) throw new Error("duplicate agenda role");
  for (const row of roles) {
    if (!row.id || row.element.dataset.sniperProtectedRole !== row.id || !supplied.includes(row.element)) throw new Error("agenda protected role differs from actual DOM");
    const nonlexical = pipeline ? row.id.startsWith("connector-") : row.id === "title-accent";
    if (row.text.length > 4096 || (!nonlexical && !row.text.trim())) throw new Error("native role text missing/unbounded");
  }
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    if (!node.textContent.trim()) continue;
    if (!roles.some((row) => row.element.contains(node))) throw new Error("unprotected actual DOM text");
  }
  return roles.sort((a, b) => a.id.localeCompare(b.id, "en"));
}

function roleGeometry(row, root) {
  const state = inherited(row.element, root);
  const range = document.createRange();
  range.selectNodeContents(row.element);
  const rectangles = [box(row.element.getBoundingClientRect()), ...Array.from(range.getClientRects(), box)];
  const bounds = state.opacity > 0 ? union(rectangles) : null;
  if (state.opacity > 0 && !bounds) state.issues.push("visible-role-has-no-bounds");
  if (row.element.scrollWidth > row.element.clientWidth + 1 || row.element.scrollHeight > row.element.clientHeight + 1) state.issues.push("role-layout-overflow");
  if (bounds && (bounds[0] < 0 || bounds[1] < 0 || bounds[2] > 1920 || bounds[3] > 1080)) state.issues.push("role-outside-canvas");
  return { id: row.id, text: row.text, bounds, opacity: state.opacity, issues: [...new Set(state.issues)].sort() };
}

function observeNative(pipeline) {
  const root = document.getElementById(pipeline ? "npl-root" : "ag-root");
  if (!root || root.dataset.compositionId !== (pipeline ? "module-pipeline" : "agenda-slide") || root.dataset.sniperLayout !== "caption-safe-upper-v1") throw new Error("unsupported native layout");
  if (root.parentElement !== document.body || document.body.parentElement !== document.documentElement || document.documentElement.parentElement !== null) throw new Error("unsupported outer DOM ancestry");
  const canvas = box(root.getBoundingClientRect());
  if (JSON.stringify(canvas) !== "[0,0,1920,1080]" || innerWidth !== 1920 || innerHeight !== 1080 || devicePixelRatio !== 1) throw new Error("unsupported native DOM canvas");
  if (document.fonts.status !== "loaded") throw new Error("agenda fonts are not loaded");
  if (root.querySelector("img,video,audio,canvas,svg,iframe,object,input,textarea")) throw new Error("unsupported painted DOM surface");
  if (document.getAnimations().length) throw new Error("unsupported CSS or WAAPI animation");
  const rows = Array.from(root.querySelectorAll(pipeline ? "#npl-chain > .npl-native-cell > .npl-node" : ".ag-row"));
  if (rows.length < (pipeline ? 2 : 1) || rows.length > (pipeline ? 6 : 3)) throw new Error("unsupported native row count");
  if (pipeline && (root.classList.contains("has-presenter") || root.querySelectorAll(".npl-native-link").length !== rows.length - 1)) throw new Error("unsupported pipeline presenter or connector coverage");
  const roles = roleInventory(root, pipeline);
  const issues = [];
  const nodes = Array.from(root.querySelectorAll("*"));
  if (nodes.length > 128) throw new Error("agenda DOM node ceiling exceeded");
  for (const node of [...nodes, root, document.body, document.documentElement]) issues.push(...paintIssues(node, root));
  return { roles: roles.map((row) => roleGeometry(row, root)), issues: [...new Set(issues)].sort() };
}

export function browserExpression(profile = "sealed-agenda-css-layout-v1") {
  if (!["sealed-agenda-css-layout-v1", "sealed-pipeline-css-layout-v1"].includes(profile)) throw new Error("unsupported browser layout profile");
  const helpers = [box, union, fullCanvasClip, paintIssues, inherited, expectedRole, pipelineRole, roleInventory, roleGeometry, observeNative];
  return `(() => {${helpers.map((fn) => fn.toString()).join("\n")}return observeNative(${profile === "sealed-pipeline-css-layout-v1"});})()`;
}
