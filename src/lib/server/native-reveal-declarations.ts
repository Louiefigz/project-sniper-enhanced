/**
 * Static declared-reveal rule for mounted catalog compositions (MASTER-PLAN M-067, P2-EARLY-CHECKS P2-02).
 *
 * A composition element that appears later declares `data-hf-reveal="<cue>"`: the id of a numeric composition
 * variable, or decimal seconds. At plan build each cue is resolved for its mount (the mount's
 * `data-variable-values`, then the variable's declared default), and the element must be hidden before any
 * script runs. A GSAP `fromTo(..., {immediateRender:false}, cue)` does not hide it before its tween starts, so
 * the mount's first frame would show it. Markup is parsed with linkedom and CSS with postcss, never matched as
 * text. This check is static; the runtime reveal probe (P2-03) observes the dynamic behaviour.
 */
import { parseHTML } from "linkedom";
import type { AtRule, Container, Declaration, Node as CssNode, Rule } from "postcss";
import { NativeCheckError } from "./native-check-error";
import { parseCss } from "./native-composition-isolation";
import type { NativeShortProjectInput } from "./native-short-project";

/** The attribute that declares a later reveal on a composition element. */
export const REVEAL_ATTRIBUTE = "data-hf-reveal";

/** One catalog mount of the authored scene markup (the attribute contract of `catalogMounts`). */
export interface NativeMountFacts {
  id: string; compositionId: string; file: string; start: number; duration: number; variables: Record<string, unknown>;
}

/** One declared reveal resolved for its mount; `cueLocalFrame` counts frames from the mount's first frame. */
export interface NativeRevealDeclaration {
  mountId: string; file: string; hfId: string; cue: string; cueSeconds: number; cueLocalFrame: number;
}

interface CompositionDocuments { file: Document; content?: Document }
interface CompositionVariable { type: unknown; value: unknown }
interface RevealContext { mount: NativeMountFacts; variables: Map<string, CompositionVariable>; rate: number }
interface OpacityRule { zero: boolean; important: boolean; conditional: boolean }
interface InlineState { parsed: boolean; visibilityHidden: boolean; opacity?: { zero: boolean; important: boolean } }

/** Decimal seconds literal (syntax only, as `native-review-regions.ts`). */
const DECIMAL = /^(?:0|[1-9]\d*)(?:\.\d+)?$/u;
/** A CSS <number> or <percentage> token (syntax only); anything else cannot be proven zero. */
const CSS_NUMBER = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?%?$/iu;

/** The runtime's frame snap for a clip bound, floor(seconds * rate + 1e-9) (`mountFrames`). */
function snapFrame(seconds: number, rate: number): number {
  return Math.floor(seconds * rate + 1e-9);
}

function jsonValue(text: string, message: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    throw new Error(message);
  }
}

function seconds(element: Element, name: string): number {
  const text = element.getAttribute(name);
  return text === null || !text.trim() ? Number.NaN : Number(text);
}

function mountFacts(element: Element): NativeMountFacts {
  const id = element.getAttribute("id") ?? "", compositionId = element.getAttribute("data-composition-id") ?? "";
  if (!id || !compositionId) {
    throw new Error(`Catalog mount ${id || element.getAttribute("data-composition-src")} lacks a stable id or data-composition-id`);
  }
  const start = seconds(element, "data-start"), duration = seconds(element, "data-duration");
  if (!Number.isFinite(start) || start < 0 || !Number.isFinite(duration) || duration <= 0) {
    throw new Error(`Catalog mount ${id} lacks explicit timing`);
  }
  const text = element.getAttribute("data-variable-values"), message = `Catalog mount ${id} has malformed data-variable-values`;
  const variables = text === null ? {} : jsonValue(text, message);
  if (!variables || typeof variables !== "object" || Array.isArray(variables)) throw new Error(message);
  return { id, compositionId, file: element.getAttribute("data-composition-src") ?? "", start, duration,
    variables: variables as Record<string, unknown> };
}

/** Every catalog mount (`data-composition-src`) in `extension.markup`, parsed with linkedom; strict for every mount. */
export function nativeMountFacts(markup: string): NativeMountFacts[] {
  const document = parseHTML(markup).document as unknown as Document;
  return Array.from(document.querySelectorAll("[data-composition-src]")).map(mountFacts);
}

function compositionDocuments(html: string): CompositionDocuments {
  const file = parseHTML(html).document as unknown as Document, template = file.querySelector("template");
  return { file, content: template ? parseHTML(template.innerHTML).document as unknown as Document : undefined };
}

function declaredElements(documents: CompositionDocuments): Element[] {
  return Array.from(documents.content?.querySelectorAll(`[${REVEAL_ATTRIBUTE}]`) ?? []);
}

function compositionVariables(documents: CompositionDocuments, file: string): Map<string, CompositionVariable> {
  const selector = "[data-composition-variables]";
  const holder = documents.file.querySelector(selector) ?? documents.content?.querySelector(selector);
  const text = holder?.getAttribute("data-composition-variables"), message = `Composition ${file} has malformed data-composition-variables`;
  const rows = text === null || text === undefined ? [] : jsonValue(text, message);
  if (!Array.isArray(rows) || rows.some(row => !row || typeof row !== "object" || typeof row.id !== "string")) throw new Error(message);
  return new Map(rows.map(row => [row.id as string, { type: row.type, value: row.default }]));
}

function cueSeconds(cue: string, hfId: string, context: RevealContext): number {
  const variable = context.variables.get(cue), values = context.mount.variables;
  const value = variable?.type !== "number" ? undefined : Object.hasOwn(values, cue) ? values[cue] : variable.value;
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (!variable && DECIMAL.test(cue)) return Number(cue);
  throw new NativeCheckError("reveal-cue-invalid",
    `Declared reveal ${hfId} in ${context.mount.file}: cue '${cue}' is neither a numeric composition variable nor seconds`);
}

function revealDeclaration(element: Element, context: RevealContext): NativeRevealDeclaration {
  const { mount, rate } = context, hfId = element.getAttribute("data-hf-id") ?? "";
  if (!hfId) throw new NativeCheckError("reveal-cue-invalid", `Declared reveal in ${mount.file} needs a data-hf-id handle`);
  const cue = element.getAttribute(REVEAL_ATTRIBUTE) ?? "", at = cueSeconds(cue, hfId, context), cueLocalFrame = snapFrame(at, rate);
  // Outside means no active frame of the mount shows the cue: the runtime shows [first, endExclusive).
  if (at < 0 || cueLocalFrame >= snapFrame(mount.start + mount.duration, rate) - snapFrame(mount.start, rate)) {
    throw new NativeCheckError("reveal-cue-invalid",
      `Declared reveal ${hfId} in ${mount.file}: cue ${at}s lies outside mount ${mount.id} (0-${mount.duration}s)`);
  }
  return { mountId: mount.id, file: mount.file, hfId, cue, cueSeconds: at, cueLocalFrame };
}

/** Every `data-hf-reveal` element of the composition's template, with its cue resolved for `mount`. */
export function declaredReveals(html: string, mount: NativeMountFacts, rate: number): NativeRevealDeclaration[] {
  if (!Number.isFinite(rate) || rate <= 0) throw new Error("Declared reveals need a positive frame rate");
  const documents = compositionDocuments(html), elements = declaredElements(documents);
  if (!elements.length) return [];
  const context = { mount, variables: compositionVariables(documents, mount.file), rate };
  return elements.map(element => revealDeclaration(element, context));
}

function opacityZero(value: string): boolean {
  const text = value.trim();
  return CSS_NUMBER.test(text) && Number(text.endsWith("%") ? text.slice(0, -1) : text) === 0;
}

/** The winning declaration of one property inside one declaration block: the last `!important`, else the last. */
function winner(declarations: Declaration[], prop: string): Declaration | undefined {
  const rows = declarations.filter(row => row.prop.toLowerCase() === prop);
  return rows.filter(row => row.important).at(-1) ?? rows.at(-1);
}

/** The declarations of a style attribute; undefined when it does not stay one declaration block. */
function inlineDeclarations(element: Element): Declaration[] | undefined {
  const style = element.getAttribute("style");
  if (!style?.trim()) return [];
  const root = parseCss(`element{${style}}`), rule = root.nodes?.length === 1 ? root.first : undefined;
  if (rule?.type !== "rule" || (rule as Rule).nodes.some(node => node.type !== "decl")) return undefined;
  return (rule as Rule).nodes as Declaration[];
}

function inlineState(element: Element): InlineState {
  const declarations = inlineDeclarations(element);
  // A style attribute that does not stay one declaration block cannot be read as one: not provably hidden.
  if (!declarations) return { parsed: false, visibilityHidden: false };
  const opacity = winner(declarations, "opacity");
  return { parsed: true, visibilityHidden: winner(declarations, "visibility")?.value.trim().toLowerCase() === "hidden",
    opacity: opacity && { zero: opacityZero(opacity.value), important: Boolean(opacity.important) } };
}

/**
 * Inline `visibility:hidden` proves hidden only when no other `visibility` declaration can apply: none in the
 * file's sheets (a matching `!important` rule would win over the inline value) and none in a descendant's inline
 * style (a child set `visibility:visible` shows inside a hidden parent, and the runtime probe's walk cannot see it).
 */
function visibilityHolds(element: Element, sheets: Container[]): boolean {
  const declares = (rows: Declaration[] | undefined) => !rows || rows.some(row => row.prop.toLowerCase() === "visibility");
  let inSheets = false;
  sheets.forEach(sheet => sheet.walkDecls(row => { inSheets ||= row.prop.toLowerCase() === "visibility"; }));
  return !inSheets && !Array.from(element.querySelectorAll("[style]")).some(child => declares(inlineDeclarations(child)));
}

function insideKeyframes(rule: Rule): boolean {
  for (let node: CssNode | undefined = rule.parent; node; node = node.parent) {
    if (node.type === "atrule" && (node as AtRule).name.toLowerCase().endsWith("keyframes")) return true;
  }
  return false;
}

function ruleMatches(element: Element, rule: Rule, declaration: NativeRevealDeclaration): boolean {
  return rule.selectors.some(selector => {
    try {
      return element.matches(selector);
    } catch (error) {
      throw new NativeCheckError("reveal-not-statically-hidden", `Premature reveal risk: ${declaration.file} element `
        + `${declaration.hfId} declares data-hf-reveal=${declaration.cue} but selector '${selector}' cannot be evaluated `
        + `(${error instanceof Error ? error.message : String(error)}); hide it in its CSS rule or inline style`);
    }
  });
}

/** Opacity declarations of every rule whose selector list has a member the element matches (grouped selectors count per member). */
function matchingOpacity(element: Element, sheets: Container[], declaration: NativeRevealDeclaration): OpacityRule[] {
  const rows: OpacityRule[] = [];
  for (const sheet of sheets) {
    sheet.walkRules(rule => {
      const opacity = rule.nodes.filter((node): node is Declaration => node.type === "decl" && node.prop.toLowerCase() === "opacity");
      if (!opacity.length || insideKeyframes(rule) || !ruleMatches(element, rule, declaration)) return;
      // A rule inside @media, @supports, @layer or another rule may not apply: it can re-show, never prove hidden.
      const conditional = rule.parent?.type !== "root";
      rows.push(...opacity.map(row => ({ zero: opacityZero(row.value), important: Boolean(row.important), conditional })));
    });
  }
  return rows;
}

/**
 * P2-02 rule with the cascade's precedence: inline `visibility:hidden` hides when nothing can override it
 * (`visibilityHolds`); a matching `!important` non-zero
 * opacity shows; an inline opacity decides unless an unconditional `!important` zero rule overrides a normal one;
 * otherwise at least one unconditional matching rule declares opacity 0 and every matching opacity declaration is 0.
 */
function staticallyHidden(element: Element, sheets: Container[], declaration: NativeRevealDeclaration): boolean {
  const inline = inlineState(element);
  if (!inline.parsed) return false;
  if (inline.visibilityHidden && visibilityHolds(element, sheets)) return true;
  const rules = matchingOpacity(element, sheets, declaration);
  if (rules.some(row => row.important && !row.zero)) return false;
  const firm = rules.filter(row => row.zero && !row.conditional);
  if (inline.opacity) return inline.opacity.zero || (!inline.opacity.important && firm.some(row => row.important));
  return firm.length > 0 && rules.every(row => row.zero);
}

/** Refuse any declared reveal that is visible before scripts run (inline style or the composition's CSS rules). */
export function assertStaticallyHidden(html: string, declarations: NativeRevealDeclaration[]): void {
  if (!declarations.length) return;
  const documents = compositionDocuments(html), elements = declaredElements(documents);
  const styles = [documents.file, documents.content].flatMap(document => Array.from(document?.querySelectorAll("style") ?? []));
  const sheets = styles.map(style => parseCss(style.textContent ?? ""));
  for (const declaration of declarations) {
    // Every element carrying the handle is checked, so a repeated data-hf-id cannot hide a visible twin.
    const handled = elements.filter(row => row.getAttribute("data-hf-id") === declaration.hfId);
    if (!handled.length) throw new Error(`Declared reveal ${declaration.hfId} is not an element of ${declaration.file}`);
    if (!handled.every(element => staticallyHidden(element, sheets, declaration))) {
      throw new NativeCheckError("reveal-not-statically-hidden", `Premature reveal risk: ${declaration.file} element `
        + `${declaration.hfId} declares data-hf-reveal=${declaration.cue} but is visible before scripts run; `
        + "hide it in its CSS rule or inline style");
    }
  }
}

/**
 * Resolve and statically check the declared reveals of every catalog mount; returns every declaration. Only a mount
 * whose staged file declares a reveal needs the strict mount facts (X72 M1), so legacy mounts of undeclared files
 * (for example without `data-composition-id`) still build and cold-read.
 */
export function assertNativeRevealDeclarations(input: NativeShortProjectInput, files: Record<string, string>): NativeRevealDeclaration[] {
  const [num, den] = input.canvas.frameRate.split("/").map(Number);
  const markup = parseHTML(input.extension?.markup ?? "").document as unknown as Document;
  return Array.from(markup.querySelectorAll("[data-composition-src]")).flatMap(element => {
    const file = element.getAttribute("data-composition-src") ?? "";
    if (!Object.hasOwn(files, file)) {
      throw new Error(`Catalog mount ${element.getAttribute("id") ?? ""} names ${file}, which is not a staged catalog file`);
    }
    if (!declaredElements(compositionDocuments(files[file])).length) return [];
    const declarations = declaredReveals(files[file], mountFacts(element), num / den);
    assertStaticallyHidden(files[file], declarations);
    return declarations;
  });
}
