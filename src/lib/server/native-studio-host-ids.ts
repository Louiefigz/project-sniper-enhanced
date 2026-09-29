/**
 * Studio selection ids must already be in a native Short's authored files.
 *
 * Evidence (HyperFrames 0.8.31, the pinned Studio runtime, native-render-sdk.mjs): when the preview
 * route serves a project it calls `persistHfIdsIfNeeded` on the main HTML, and every previewed
 * sub-composition goes through `stampFileHfIds`. Both run `ensureHfIds`, which gives each element
 * without `data-hf-id` a minted id, and if any id was added they write the DOM-serialized file back
 * over the project file. That rewrite also normalizes the doctype, attribute quoting and entities.
 * Opening the required Studio hand-off would then change a built Short after its MP4 was delivered,
 * so the delivery no longer re-verifies and a promotion or export of that project is refused.
 * The walk below mirrors `ensureHfIds`: element descendants of <body>, entering only composition
 * templates, and every element except the excluded tags needs an id.
 */
import { parseHTML } from "linkedom";

const EXCLUDED_TAGS = new Set(["script", "style", "template", "meta", "link", "noscript", "base"]);
const REPORTED = 8;

function childElements(parent: Element): Element[] {
  const direct = Array.from(parent.children);
  if (direct.length || parent.tagName.toLowerCase() !== "template") return direct;
  const content = (parent as HTMLTemplateElement).content;
  return content?.children.length ? Array.from(content.children) : direct;
}

function compositionTemplate(element: Element): boolean {
  return element.getAttribute("data-composition-id") !== null
    || childElements(element).some((child) => child.getAttribute("data-composition-id") !== null);
}

function describe(element: Element): string {
  const id = element.getAttribute("id"), className = element.getAttribute("class");
  return element.tagName.toLowerCase() + (id ? `#${id}` : className ? `.${className.trim().split(/\s+/u)[0]}` : "");
}

/** Elements Studio would stamp (and so rewrite the file for), in document order. */
export function missingStudioHostIds(html: string): string[] {
  const shell = /<!doctype|<html[\s>]/iu.test(html);
  const { document } = parseHTML(shell ? html : `<!DOCTYPE html><html><head></head><body>${html}</body></html>`);
  if (!document.body) return [];
  const missing: string[] = [];
  const walk = (parent: Element): void => {
    for (const child of childElements(parent)) {
      const template = child.tagName.toLowerCase() === "template";
      if (template && !compositionTemplate(child)) continue;
      if (!EXCLUDED_TAGS.has(child.tagName.toLowerCase()) && !child.getAttribute("data-hf-id")) missing.push(describe(child));
      walk(child);
    }
  };
  walk(document.body);
  return missing;
}

/** Refuse a new build whose index or mounted compositions Studio would rewrite when opened. */
export function assertStudioHostIds(files: Record<string, string>): void {
  const missing = Object.entries(files).filter(([file]) => file === "index.html" || /^compositions\/.+\.html?$/u.test(file))
    .flatMap(([file, html]) => missingStudioHostIds(html).map((element) => `${file} ${element}`));
  if (!missing.length) return;
  const more = missing.length > REPORTED ? ` and ${missing.length - REPORTED} more` : "";
  throw new Error("Studio would rewrite this project when it is opened for review: give each authored element a unique "
    + `data-hf-id (missing on ${missing.slice(0, REPORTED).join(", ")}${more})`);
}
