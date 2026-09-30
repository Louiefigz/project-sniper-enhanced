/**
 * Prove that a mounted catalog composition's local edits cannot change frames outside its mount.
 *
 * Evidence for the rule (HyperFrames 0.8.31, the pinned render SDK): the producer compiler
 * inlines each sub-composition into its host in the root document, scopes every top-level
 * style rule with the host's `[data-composition-id]` selector except bare `*` and rules inside
 * `@keyframes`/`@font-face`, keeps other at-rules global, hoists head links and external
 * scripts, and wraps inline scripts with scoped query proxies (compiler/compositionScoping.js,
 * inlineSubCompositions.js). The runtime hides an inactive absolutely positioned host only with
 * inline `visibility: hidden` (hyperframe.runtime.iife.js), which a descendant `visibility`
 * declaration can override. A composition is therefore local only when its rules stay scoped,
 * its script is confined, nothing in the document can set visibility or counters, and its host
 * is a unique absolutely positioned mount. Global parts are hashed into every preview unit.
 */
import postcss, { type ChildNode, type Container, type Declaration, type Rule } from "postcss";
import { parseHTML } from "linkedom";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { fail } from "./native-composition-script-scope";
import { assertConfinedCompositionScript } from "./native-composition-script-validator";

export const COMPOSITION_ISOLATION_RULE = "hyperframes-0.8.31-scoped-composition-v2";
export type CompositionIsolation =
  | { status: "scoped"; rule: typeof COMPOSITION_ISOLATION_RULE; globalSha256: string }
  | { status: "global"; reason: string };
export interface CompositionHost { compositionId: string; style: string }
/** Document-wide facts: executable root ids and composition identities used anywhere else. */
export interface IsolationDocument { rootIds: Set<string>; foreignCompositionIds: Set<string> }

const FORBIDDEN_ELEMENTS = new Set(["iframe", "object", "embed", "video", "audio", "source", "track", "template",
  "meta", "base", "link", "animate", "set", "animatetransform", "animatemotion", "animatecolor", "foreignobject",
  "slot", "frame", "frameset", "portal", "noscript", "canvas", "svg", "defs", "use", "symbol",
  "input", "button", "textarea", "select", "option", "form", "details", "summary"]);
const CONTROLLING = /^(?:-[a-z]+-)?(?:visibility|content-visibility|all|counter-(?:reset|increment|set))$/iu;
const TIMING = /^data-(?:start|end|hidden|media-start|track-index|track-kind|composition-src|variable-values)$/iu;
const SHARED_SCRIPT = "assets/gsap.min.js";

function declarationAllowed(declaration: Declaration): void {
  if (declaration.important || CONTROLLING.test(declaration.prop) || declaration.prop.includes("\\")) fail(`declaration ${declaration.prop}`);
}

/** Only sibling combinators outside brackets/parentheses can escape the scoped host subtree. */
function selectorAllowed(selector: string): void {
  if (selector.trim() === "*" || /data-(?:composition|hf-|start|duration|end)|:host|::slotted/iu.test(selector)) {
    fail(`selector ${selector}`);
  }
  let depth = 0, quote = "";
  for (let index = 0; index < selector.length; index += 1) {
    const char = selector[index];
    if (char === "\\") { index += 1; continue; }
    if (quote) { if (char === quote) quote = ""; continue; }
    if (char === '"' || char === "'") quote = char;
    else if (char === "(" || char === "[") depth += 1;
    else if (char === ")" || char === "]") depth -= 1;
    else if (depth === 0 && (char === "+" || char === "~")) fail("sibling combinator can leave the host");
  }
}

function localBody(container: Container): void {
  container.each((child: ChildNode) => {
    if (child.type === "comment") return;
    if (child.type === "decl") return declarationAllowed(child);
    if (child.type === "rule") { child.selectors.forEach(selectorAllowed); return localBody(child); }
    if (child.type === "atrule" && ["media", "supports"].includes(child.name.toLowerCase()) && child.nodes) {
      return localBody(child);
    }
    fail(`nested ${child.type}`);
  });
}

/** Parse one style body with the compiler's CSS parser (postcss); refuses what it cannot parse. */
export function parseCss(text: string): Container {
  try {
    return postcss.parse(text);
  } catch {
    fail("style does not parse with the compiler's CSS parser");
  }
}

/** Split one style body into global parts and proven-scoped local rules. */
export function styleParts(text: string): { global: string[]; localError?: string } {
  const global: string[] = [];
  let localError: string | undefined;
  for (const node of parseCss(text).nodes ?? []) {
    if (node.type === "comment") continue;
    const unscoped = node.type === "atrule" || (node.type === "rule" && (node as Rule).selectors.some(row => row.trim() === "*"));
    if (unscoped) {
      global.push(node.toString());
      continue;
    }
    try {
      if (node.type !== "rule") fail(`top-level ${node.type}`);
      node.selectors.forEach(selectorAllowed);
      localBody(node);
    } catch (error) {
      localError ??= error instanceof Error ? error.message : String(error);
    }
  }
  return { global, localError };
}

/** Root styles and scripts decide whether any hidden host can be made visible again. */
export function rootVisibilitySafe(styles: string[], scripts: string[]): boolean {
  try {
    for (const text of styles) {
      let safe = true;
      parseCss(text).walkDecls(row => { if (CONTROLLING.test(row.prop) || row.prop.includes("\\")) safe = false; });
      if (!safe) return false;
    }
  } catch {
    return false;
  }
  return scripts.every(text => !/visibility|counter-/iu.test(text));
}

/** Relational root styling can observe hidden composition content and change other output pixels. */
export function rootStylesIsolated(styles: string[]): boolean {
  try {
    for (const text of styles) {
      let safe = true;
      parseCss(text).walkAtRules(rule => {
        if (!["font-face", "media", "supports", "keyframes", "-webkit-keyframes"].includes(rule.name.toLowerCase())) safe = false;
      });
      parseCss(text).walkRules(rule => {
        if (rule.selectors.some(selector => /[:+~\\]|\|\|/u.test(selector))) safe = false;
      });
      parseCss(text).walkDecls(row => {
        if (/url\(\s*["']?#/iu.test(row.value) || /var\(/iu.test(row.value)) safe = false;
      });
      if (!safe) return false;
    }
    return true;
  } catch {
    return false;
  }
}

function hostPositioned(style: string): boolean {
  let position = "";
  parseCss(`host{${style}}`).walkDecls("position", row => { position = row.value.trim().toLowerCase(); });
  return position === "absolute";
}

function markupAllowed(content: Document, innerRoot: Element, document: IsolationDocument): void {
  for (const element of Array.from(content.querySelectorAll("*"))) {
    const tag = element.tagName.toLowerCase();
    if (FORBIDDEN_ELEMENTS.has(tag)) fail(`element ${tag}`);
    for (const { name, value } of Array.from(element.attributes)) {
      const lower = name.toLowerCase();
      if (lower.startsWith("on") || ["visibility", "autofocus", "contenteditable"].includes(lower)
          || TIMING.test(lower)) fail(`attribute ${lower}`);
      if (lower === "data-composition-id" && element !== innerRoot) fail("nested composition root");
      if (lower === "data-duration" && element !== innerRoot) fail("nested timed element");
      if (lower === "id" && document.rootIds.has(value)) fail(`id ${value} collides with the root document`);
      if (lower === "style") parseCss(`element{${value}}`).walkDecls(declarationAllowed);
    }
  }
}

/** Every style and script in a composition file, including those outside its template. */
function fileSources(html: string): { styles: string[]; scripts: string[] } {
  const file = parseHTML(html).document, template = file.querySelector("template");
  const documents = [file, ...(template ? [parseHTML(template.innerHTML).document] : [])];
  const pick = (tag: string) => documents.flatMap(row => Array.from(row.querySelectorAll(tag)))
    .filter(element => tag === "style" || !element.getAttribute("src")).map(element => element.textContent ?? "");
  return { styles: pick("style"), scripts: pick("script") };
}

/**
 * True when a composition file could make any hidden host visible again or change counters.
 * Deliberately broader than its global parts: one such file blocks every scoped verdict.
 */
export function compositionControlsVisibility(html: string): boolean {
  try {
    const { styles, scripts } = fileSources(html);
    // SVG/HTML fragment resources can resolve across hidden hosts in the inlined document.
    // Neither CSS scoping nor absolute positioning confines that resource lookup.
    return !rootVisibilitySafe(styles, scripts) || /url\(\s*["']?#|(?:href|xlink:href)\s*=\s*["']#/iu.test(html);
  } catch {
    return true;
  }
}

/** Hoisted global styles remain shared inputs; outside scripts cannot be confined to a host. */
function outsideTemplateStyles(file: Document): string[] {
  const global: string[] = [];
  for (const element of Array.from(file.querySelectorAll("script, style"))) {
    if (element.closest("template")) continue;
    if (element.tagName.toLowerCase() === "style") global.push(element.textContent ?? "");
    else if (element.getAttribute("src") !== SHARED_SCRIPT) fail("unconfined script outside the composition template");
  }
  return global;
}

/** Analyze one composition mounted once under a known host; the caller applies document safety. */
export function analyzeComposition(html: string, host: CompositionHost, document: IsolationDocument): CompositionIsolation {
  try {
    const file = parseHTML(html).document, template = file.querySelector("template");
    if (!template || file.querySelectorAll("link").length) fail("composition needs one template and no hoisted links");
    const content = parseHTML(template.innerHTML).document as unknown as Document;
    const roots = Array.from(content.querySelectorAll("[data-composition-id]"));
    if (roots.length !== 1 || roots[0].getAttribute("data-composition-id") !== host.compositionId) {
      fail("composition root differs from its unique host identity");
    }
    if (!host.compositionId || document.foreignCompositionIds.has(host.compositionId) || !hostPositioned(host.style)) {
      fail("host is not a unique absolutely positioned mount");
    }
    const global = outsideTemplateStyles(file as unknown as Document), scripts: string[] = [];
    for (const style of Array.from(content.querySelectorAll("style"))) {
      const parts = styleParts(style.textContent ?? "");
      if (parts.localError) throw new Error(parts.localError);
      global.push(...parts.global);
    }
    if (!rootStylesIsolated(global)) fail("composition global styles can depend on another host's content");
    for (const script of Array.from(content.querySelectorAll("script"))) {
      const source = script.getAttribute("src");
      if (source !== null) { scripts.push(source); if (source !== SHARED_SCRIPT) fail(`external script ${source}`); continue; }
      assertConfinedCompositionScript(script.textContent ?? "", [host.compositionId, roots[0].getAttribute("id") ?? host.compositionId]);
    }
    markupAllowed(content, roots[0], document);
    const root = roots[0];
    const globalSha256 = canonicalJsonSha256({ rule: COMPOSITION_ISOLATION_RULE, global, scripts,
      root: ["data-width", "data-height", "data-duration", "data-timeline-locked"].map(name => root.getAttribute(name)) });
    return { status: "scoped", rule: COMPOSITION_ISOLATION_RULE, globalSha256 };
  } catch (error) {
    return { status: "global", reason: String(error instanceof Error ? error.message : error).slice(0, 300) };
  }
}
