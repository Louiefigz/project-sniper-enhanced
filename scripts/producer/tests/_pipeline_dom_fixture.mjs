/** Small TEST DOM for authoring/timeline parity only; not native geometry or pixels. */
import { runInNewContext } from "node:vm";
import { readFileSync } from "node:fs";

const tokens = readFileSync(new URL("../../../templates/motion/motion-tokens.js", import.meta.url), "utf8");

class Element {
  constructor(id = "") {
    this.id = id; this.className = ""; this.children = []; this.dataset = {};
    this.removed = false; this.ownText = "";
    this.classList = { add: (name) => {
      this.className = [...new Set([...this.className.split(" ").filter(Boolean), name])].join(" ");
    } };
  }
  get textContent() { return this.ownText + this.children.map((child) => child.textContent).join(""); }
  set textContent(value) { this.ownText = String(value); this.children = []; }
  appendChild(child) { this.children.push(child); child.parentElement = this; return child; }
  remove() { this.removed = true; }
  querySelectorAll(selector) {
    if (selector !== ".line") throw new Error("TEST DOM only supports the declared line selector");
    return this.children.filter((child) => child.className.split(" ").includes("line"));
  }
}

function documentFixture() {
  const ids = ["root", "eyebrow", "eyebrow-text", "headline", "explainer", "chain", "foot", "foot-text"];
  const elements = Object.fromEntries(ids.map((name) => ["npl-" + name, new Element("npl-" + name)]));
  elements["npl-root"].dataset.duration = "9";
  return { elements, document: {
    getElementById: (id) => elements[id]?.removed ? null : elements[id],
    createElement: () => new Element(),
  } };
}

function snapshot(element) {
  return { id: element.id, className: element.className, ownText: element.ownText,
    removed: element.removed, children: element.children.map(snapshot) };
}

function elementKey(element) {
  return element.id || element.className + ":" + element.textContent;
}

function descendants(element) {
  return [element, ...element.children.flatMap(descendants)];
}

export function runPipelineScript(source, variables) {
  const fixture = documentFixture(), trace = [];
  let paused;
  const timeline = { paused: () => paused, seek: (at) => trace.push(["seek", at]),
    fromTo: (element, _from, to, at) => trace.push([
      typeof element === "string" ? "blurRecede" : "textRamp",
      typeof element === "string" ? element : elementKey(element), at, to.duration]) };
  const window = { __hyperframes: { getVariables: () => variables } };
  runInNewContext(tokens, { window }, { timeout: 1000 });
  runInNewContext(source, { window, document: fixture.document,
    gsap: { timeline: (options) => { paused = options.paused; trace.push(["timeline", options.paused]); return timeline; } } }, { timeout: 1000 });
  if (window.__timelines["nateherk-pipeline"] !== timeline) throw new Error("TEST timeline was not registered");
  return { trace, snapshot: Object.fromEntries(Object.entries(fixture.elements).map(([id, element]) => [id, snapshot(element)])),
    layout: fixture.elements["npl-root"].dataset.sniperLayout,
    roles: Object.values(fixture.elements).flatMap(descendants)
      .filter((element) => !element.removed && element.dataset.sniperProtectedRole)
      .map((element) => ({ id: element.dataset.sniperProtectedRole, text: element.textContent })) };
}
