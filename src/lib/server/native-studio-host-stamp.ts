/**
 * Give an authored native file the Studio selection ids it lacks, without re-serializing it.
 *
 * Studio's own stamping re-serializes the whole document; this inserts ` data-hf-id="…"` right
 * after each eligible start tag's name and leaves every other byte unchanged, so authors stamp a
 * catalog adaptation or markup fragment once, before it is hashed into the plan. Eligibility is the
 * walk in native-studio-host-ids.ts, whose checker must find nothing missing in the result.
 */
import { parseDocument } from "htmlparser2";
import type { ChildNode, Element } from "domhandler";
import { missingStudioHostIds } from "./native-studio-host-ids";

const EXCLUDED_TAGS = new Set(["script", "style", "template", "meta", "link", "noscript", "base"]);

function elements(nodes: ChildNode[]): Element[] {
  return nodes.filter((node): node is Element => node.type === "tag" || node.type === "script" || node.type === "style");
}

function compositionTemplate(element: Element): boolean {
  return "data-composition-id" in element.attribs
    || elements(element.children).some((child) => "data-composition-id" in child.attribs);
}

function eligible(root: ChildNode[], shell: boolean): Element[] {
  const found: Element[] = [];
  const walk = (nodes: ChildNode[], inBody: boolean): void => {
    for (const element of elements(nodes)) {
      const name = element.name.toLowerCase(), body = inBody || name === "body";
      if (name === "template" && body && !compositionTemplate(element)) continue;
      if (inBody && !EXCLUDED_TAGS.has(name)) found.push(element);
      walk(element.children, body);
    }
  };
  walk(root, !shell);
  return found;
}

function mint(element: Element, index: number, assigned: Set<string>): string {
  const own = element.attribs.id && /^[A-Za-z][\w-]{0,80}$/u.test(element.attribs.id) ? `hf-${element.attribs.id}` : "";
  let id = own && !assigned.has(own) ? own : `hf-${element.name.toLowerCase()}-${index}`;
  for (let suffix = 1; assigned.has(id); suffix += 1) id = `hf-${element.name.toLowerCase()}-${index}-${suffix}`;
  assigned.add(id);
  return id;
}

/** The same file with an id on every element Studio would stamp; unchanged when none is missing. */
export function stampStudioHostIds(html: string): string {
  const shell = /<!doctype|<html[\s>]/iu.test(html);
  const document = parseDocument(html, { withStartIndices: true, recognizeSelfClosing: false });
  const candidates = eligible(document.children, shell);
  const assigned = new Set(candidates.map((element) => element.attribs["data-hf-id"]).filter(Boolean));
  const inserts = candidates.filter((element) => !element.attribs["data-hf-id"]).map((element, index) => {
    if (element.startIndex === null || html[element.startIndex] !== "<") throw new Error("Studio id stamping lost a start tag");
    return { at: element.startIndex + 1 + element.name.length, text: ` data-hf-id="${mint(element, index, assigned)}"` };
  });
  let stamped = html;
  for (const insert of inserts.reverse()) stamped = stamped.slice(0, insert.at) + insert.text + stamped.slice(insert.at);
  const missing = missingStudioHostIds(stamped);
  if (missing.length) throw new Error(`Studio id stamping left elements without ids: ${missing.slice(0, 8).join(", ")}`);
  return stamped;
}
