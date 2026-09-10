/** Declarative dependency admission using SDK path semantics, never fetching assets. */
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
// Resolve these existing parser dependencies from their owning SDK package.
const parserRequire = createRequire(require.resolve("@hyperframes/parsers/package.json"));
const { parseHTML } = parserRequire("linkedom");
const { default: postcss } = await import("postcss");
const { CSS_URL_RE, rewriteAssetPath } = await import("@hyperframes/parsers/asset-paths");
const { isUnresolvedAssetPlaceholder, resolveExistingLocalAsset } = await import("@hyperframes/parsers/asset-resolution");

function elements(root, selector) {
  const result = [...root.querySelectorAll(selector)];
  for (const template of root.querySelectorAll("template")) {
    if (template.content) result.push(...elements(template.content, selector));
  }
  return result;
}

function finding(file, reference, code, message) {
  return { file, reference, code, severity: "error", message };
}

function resolveReference(request, context, raw) {
  const value = raw.trim();
  if (!context.mount && (!value || value.startsWith("#") || /^data:/i.test(value))) return null;
  if (isUnresolvedAssetPlaceholder(value)) return finding(context.file, value,
    "native_unresolved_dependency", "Resolve the declared asset before export.");
  if (/^(?:[a-z][a-z0-9+.-]*:|\/\/)/i.test(value)) return finding(context.file, value,
    "native_nonlocal_dependency", "Use an admitted local asset; this preflight never downloads or fetches.");
  if (context.mount && !/\.html$/i.test(value)) return finding(context.file, value || "(empty mount)",
    "native_unsupported_dependency", "This staged preflight requires composition mounts to reference .html files.");
  let relative = value;
  if (context.mount) relative = value;
  else if (context.css && !value.startsWith("/")) relative = path.posix.join(path.posix.dirname(context.file), value);
  else if (context.file !== "index.html") relative = rewriteAssetPath(context.file, value,
    candidate => Boolean(request.files[candidate]));
  const asset = resolveExistingLocalAsset(request.project, relative);
  if (!asset) return finding(context.file, value, "native_missing_dependency", "Declared local dependency is missing.");
  const name = path.relative(request.project, asset.resolved).split(path.sep).join("/");
  if (!Object.hasOwn(request.files, name)) return finding(context.file, value,
    "native_unbound_dependency", "Dependency is outside the bounded project snapshot.");
  return null;
}

function cssReferences(text) {
  const result = [];
  const css = postcss.parse(text);
  const urls = value => [...value.matchAll(new RegExp(CSS_URL_RE.source, "gi"))].map(match => ({ raw: match[2] }));
  css.walkDecls(declaration => {
    result.push(...urls(declaration.value));
    if (/(?:-webkit-)?image-set\s*\(/i.test(declaration.value)) result.push({
      raw: declaration.value, unsupported: "CSS image-set requires runtime/dependency review." });
  });
  css.walkAtRules(/^import$/i, rule => {
    const url = urls(rule.params);
    if (url.length) result.push(...url);
    else {
      const quoted = rule.params.match(/^\s*(["'])(.*?)\1/);
      if (quoted) result.push({ raw: quoted[2] });
    }
  });
  return result;
}

function htmlReferences(text) {
  const document = parseHTML(text).document;
  const result = [];
  for (const element of elements(document, "script[src],video[src],audio[src],img[src],source[src],video[poster],link[href],image,use")) {
    const stylesheet = element.localName === "link";
    if (stylesheet && !/\bstylesheet\b/i.test(element.getAttribute("rel") ?? "")) continue;
    result.push(...["src", "href", "xlink:href", "poster"]
      .map(attribute => element.getAttribute(attribute)).filter(Boolean).map(raw => ({ raw })));
  }
  for (const element of elements(document, "[data-composition-src]")) result.push({
    raw: element.getAttribute("data-composition-src"), mount: true });
  for (const element of elements(document, "[srcset]")) result.push({
    raw: element.getAttribute("srcset") || "(empty srcset)",
    unsupported: "Responsive srcset needs explicit dependency review; use one admitted src for this preflight." });
  for (const style of elements(document, "style")) result.push(...cssReferences(style.textContent));
  for (const element of elements(document, "[style]")) result.push(...cssReferences(element.getAttribute("style")));
  return result;
}

export function dependencyFindings(request) {
  const findings = [];
  for (const [file, row] of Object.entries(request.files)) {
    if (row.mediaMetadataOnly || !/\.(?:html?|css|svg)$/i.test(file)) continue;
    const text = fs.readFileSync(path.join(request.project, file), "utf8");
    const css = /\.css$/i.test(file);
    for (const reference of css ? cssReferences(text) : htmlReferences(text)) {
      const { raw, mount, unsupported } = reference;
      const result = unsupported ? finding(file, raw, "native_unsupported_dependency", unsupported)
        : resolveReference(request, { file, css, mount }, raw);
      if (result) findings.push(result);
    }
  }
  return [...new Map(findings.map(row => [JSON.stringify(row), row])).values()];
}

export function coverageFindings(request, results) {
  const checked = new Set(results.map(row => row.file));
  return Object.keys(request.files).filter(file => /\.html?$/i.test(file) && !checked.has(file))
    .map(file => finding(file, file, "native_unlinted_html",
      "SDK project lint did not cover this HTML. Use a supported staged layout; do not infer a pass."));
}
