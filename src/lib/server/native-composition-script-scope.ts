/**
 * Static confinement check for cooperative catalog composition scripts.
 *
 * HyperFrames 0.8.31 inlines a sub-composition into the root document and wraps
 * its inline script with scoped `document`, `gsap`, `window` and `__hyperframes`
 * proxies (core compiler/compositionScoping.js). The proxies filter query results
 * to the composition host subtree, but `window.document`, `document.body`, parent
 * traversal, prototype access and string tween targets still reach global state.
 * This checker admits only a closed subset in which every DOM reference is the
 * host (usable solely as a query receiver), one of its descendants, or a newly
 * created detached element. It is a conservative proof for authored scripts, not
 * a sandbox against deliberately obfuscated code: anything unrecognised fails.
 */
export interface AstNode { type: string; [key: string]: unknown }
type Kind = "root" | "element" | "timeline" | "data" | "function" | "value" | "unknown" | "dynamic";
type Origin = "var" | "param" | "function";

const DENIED_MEMBERS = new Set(["parentElement", "parentNode", "closest", "ownerDocument", "getRootNode",
  "offsetParent", "previousElementSibling", "nextElementSibling", "previousSibling", "nextSibling", "innerHTML",
  "outerHTML", "insertAdjacentHTML", "insertAdjacentElement", "insertAdjacentText", "attachShadow", "shadowRoot",
  "animate", "getAnimations", "before", "after", "replaceWith", "cssText", "visibility", "autoAlpha", "counterReset",
  "counterIncrement", "counterSet", "dataset", "setAttributeNS", "setAttributeNode", "toggleAttribute",
  "removeAttribute", "attributes", "adoptedStyleSheets", "styleSheets", "sheet", "insertRule", "prototype",
  "__proto__", "constructor", "defineProperty", "defineProperties", "setPrototypeOf", "getPrototypeOf",
  "contentDocument", "contentWindow", "defaultView", "body", "head", "documentElement", "fonts", "cookie",
  "location", "globalTimeline", "registerPlugin", "defaults", "config", "ticker", "exportRoot", "all", "write",
  "writeln", "open", "execCommand", "elementFromPoint", "elementsFromPoint", "evaluate", "importNode",
  "adoptNode", "assignedSlot", "slot", "id", "setHTMLUnsafe", "outerText", "innerText"]);
const DENIED_KEYS = new Set(["visibility", "autoAlpha", "cssText", "__proto__", "counterReset", "counterIncrement", "counterSet"]);
const DENIED_ATTRIBUTES = /^(?:style|visibility|id|href|xlink:href|src|begin|end|on.*|data-.*)$/iu;
const DENIED_PROPERTIES = /^(?:visibility|all|counter-.*)$/iu;
const QUERY_METHODS = new Set(["querySelector", "querySelectorAll", "getElementsByClassName", "getElementsByTagName"]);
const TWEEN_METHODS = new Set(["to", "from", "fromTo", "set", "staggerTo", "staggerFrom", "staggerFromTo"]);
const CALLABLE_GLOBALS = new Set(["Number", "String", "Boolean", "parseFloat", "parseInt", "isFinite", "isNaN"]);
const VALUE_GLOBALS = new Set(["undefined", "NaN", "Infinity"]);
const MEMBER_GLOBALS: Record<string, Set<string>> = {
  Math: new Set(["abs", "acos", "asin", "atan", "atan2", "ceil", "cos", "exp", "floor", "hypot", "log", "log10",
    "log2", "max", "min", "pow", "round", "sign", "sin", "sqrt", "tan", "trunc", "PI", "E", "SQRT2", "LN2", "LN10"]),
  Number: new Set(["isFinite", "isInteger", "isNaN", "parseFloat", "parseInt", "EPSILON", "MAX_SAFE_INTEGER"]),
  Array: new Set(["isArray"]), Object: new Set(["keys", "values", "entries"]), JSON: new Set(["parse", "stringify"]),
};
const SPECIAL = new Set(["document", "window", "gsap", "__hyperframes", ...Object.keys(MEMBER_GLOBALS),
  ...CALLABLE_GLOBALS, ...VALUE_GLOBALS]);
const HTML_TAGS = new Set(["div", "span", "p", "small", "strong", "em", "b", "i", "u", "br", "sup", "sub",
  "ul", "ol", "li", "h1", "h2", "h3", "h4", "h5", "h6"]);
const SVG_TAGS = new Set(["g", "path", "rect", "circle", "ellipse", "line", "polyline", "polygon", "text",
  "tspan", "defs", "linearGradient", "radialGradient", "stop", "clipPath", "mask", "svg"]);

export function fail(message: string): never {
  throw new Error(`composition is not provably isolated: ${message}`);
}

export function astNode(value: unknown): AstNode {
  if (!value || typeof value !== "object" || typeof (value as AstNode).type !== "string") fail("malformed syntax tree");
  return value as AstNode;
}

function astNodes(value: unknown): AstNode[] {
  return Array.isArray(value) ? value.filter(row => row !== null).map(astNode) : [];
}

function staticName(member: AstNode): string | undefined {
  const property = astNode(member.property);
  if (!member.computed && property.type === "Identifier") return property.name as string;
  if (member.computed && property.type === "Literal" && ["string", "number"].includes(typeof property.value)) {
    return String(property.value);
  }
  return undefined;
}

function textAllowed(text: unknown): void {
  if (typeof text === "string" && /visibility|autoAlpha|counter-/iu.test(text)) fail("a string reaches visibility or counters");
}

/** Declared names and conservative value kinds, computed before validation. */
class Scope {
  origins = new Map<string, Origin>();
  values = new Map<string, AstNode[]>();
  kinds = new Map<string, Kind>();

  declare(name: string, origin: Origin, value?: AstNode): void {
    if (SPECIAL.has(name)) fail(`declares the global name ${name}`);
    const prior = this.origins.get(name);
    this.origins.set(name, prior && prior !== origin ? "param" : origin);
    if (value) this.assign(name, value);
  }

  assign(name: string, value: AstNode): void {
    this.values.set(name, [...(this.values.get(name) ?? []), value]);
  }

  kindOf(expression: AstNode): Kind {
    if (expression.type === "Identifier") return this.kinds.get(expression.name as string) ?? "value";
    if (["ArrayExpression", "ObjectExpression"].includes(expression.type)) return "data";
    if (["FunctionExpression", "ArrowFunctionExpression"].includes(expression.type)) return "function";
    if (expression.type === "MemberExpression") return staticName(expression) === undefined ? "dynamic" : "value";
    if (expression.type !== "CallExpression") return "value";
    const callee = astNode(expression.callee), name = callee.type === "MemberExpression" ? staticName(callee) : undefined;
    if (callee.type !== "MemberExpression" || !name) return "value";
    const receiver = astNode(callee.object);
    if (receiver.type === "Identifier" && receiver.name === "document") {
      if (["getElementById", "querySelector", "querySelectorAll"].includes(name)) return "root";  // Validator admits only own-id lookups.
      return ["createElement", "createElementNS", "createTextNode"].includes(name) ? "element" : "value";
    }
    if (receiver.type === "Identifier" && receiver.name === "gsap" && name === "timeline") return "timeline";
    if (name === "getVariables") return "data";
    return QUERY_METHODS.has(name) && ["root", "element"].includes(this.kindOf(receiver)) ? "element" : "value";
  }

  /** Iterate to a fixed point: aliases inherit, and conflicting assignments degrade, a kind. */
  resolve(): void {
    for (const [name, origin] of this.origins) {
      this.kinds.set(name, origin === "param" ? "unknown" : origin === "function" ? "function" : "value");
    }
    for (let round = 0; round < 16; round += 1) {
      let changed = false;
      for (const [name, rows] of this.values) {
        if (this.origins.get(name) !== "var") continue;
        const kinds = new Set(rows.map(row => this.kindOf(row)));
        const kind: Kind = kinds.size === 1 ? [...kinds][0] : "value";
        if (kind !== this.kinds.get(name)) { this.kinds.set(name, kind); changed = true; }
      }
      if (!changed) break;
    }
    for (const [name, rows] of this.values) {
      if (this.kinds.get(name) === "root" && rows.length !== 1) fail(`host reference ${name} is reassigned`);
      if (this.origins.get(name) === "function" && rows.length) fail(`function ${name} is reassigned`);
    }
  }
}

function declarePattern(scope: Scope, pattern: AstNode, origin: Origin, value?: AstNode): void {
  if (pattern.type === "Identifier") return scope.declare(pattern.name as string, origin, value);
  if (pattern.type === "AssignmentPattern") return declarePattern(scope, astNode(pattern.left), origin);
  if (pattern.type === "RestElement") return declarePattern(scope, astNode(pattern.argument), "param");
  if (pattern.type === "ArrayPattern") return astNodes(pattern.elements).forEach(row => declarePattern(scope, row, "param"));
  if (pattern.type !== "ObjectPattern") fail(`unsupported binding ${pattern.type}`);
  for (const property of astNodes(pattern.properties)) {
    declarePattern(scope, astNode(property.type === "RestElement" ? property.argument : property.value), "param");
  }
}

/** Generic structural walk used only to collect declarations and identifier assignments. */
function collect(scope: Scope, value: AstNode): void {
  if (value.type === "VariableDeclarator") declarePattern(scope, astNode(value.id), "var", value.init ? astNode(value.init) : undefined);
  if (value.type === "FunctionDeclaration") scope.declare(astNode(value.id).name as string, "function");
  if (["FunctionDeclaration", "FunctionExpression", "ArrowFunctionExpression"].includes(value.type)) {
    astNodes(value.params).forEach(param => declarePattern(scope, param, "param"));
  }
  if (value.type === "CatchClause" && value.param) declarePattern(scope, astNode(value.param), "param");
  if (value.type === "AssignmentExpression" && astNode(value.left).type === "Identifier") {
    scope.assign(astNode(value.left).name as string, astNode(value.right));
  }
  for (const [key, child] of Object.entries(value)) {
    if (key === "type") continue;
    if (Array.isArray(child)) child.filter(row => row && typeof row === "object" && "type" in row).forEach(row => collect(scope, astNode(row)));
    else if (child && typeof child === "object" && "type" in child) collect(scope, astNode(child));
  }
}

export { DENIED_MEMBERS, DENIED_KEYS, DENIED_ATTRIBUTES, DENIED_PROPERTIES, QUERY_METHODS, TWEEN_METHODS,
  CALLABLE_GLOBALS, VALUE_GLOBALS, MEMBER_GLOBALS, HTML_TAGS, SVG_TAGS, Scope, astNodes, staticName, textAllowed, collect };
export type { Kind };
