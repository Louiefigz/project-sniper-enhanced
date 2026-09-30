/** Static declared-reveal rule (P2-02); synthetic compositions copied from the toolkit numbers pattern. */
import assert from "node:assert/strict";
import { test } from "node:test";
import { NativeCheckError } from "../native-check-error";
import { assertNativeRevealDeclarations, declaredReveals, nativeMountFacts } from "../native-reveal-declarations";
import type { NativeShortProjectInput } from "../native-short-project";

const ID = "sn-numbers-t";
const FILE = "compositions/numbers-t.html";
const VARIABLES = [{ id: "firstAt", type: "number", label: "firstAt", default: 0 },
  { id: "laterAt", type: "number", label: "laterAt", default: 6 }, { id: "unit", type: "string", label: "unit", default: "" }];
const BASE = `#${ID}{position:absolute;inset:0}#${ID} .panel,#${ID} .stat,#${ID} .arrow{transform:translate(0px,0px)}`
  + `#${ID} .arrow{font-size:58px}@keyframes pulse{0%{opacity:1}50%{opacity:.4}}`;
const HIDE = `#${ID} .panel,#${ID} .later,#${ID} .arrow{opacity:0}`;
/** The numbers panel; `declare` false gives the saved run-1 shape, which declares nothing. */
function panel(declare = true): string {
  const reveal = (cue: string) => (declare ? ` data-hf-reveal="${cue}"` : "");
  return `<div data-hf-id="hf-panel" class="panel"${reveal("firstAt")}><div data-hf-id="hf-row" class="row">`
    + `<div data-hf-id="hf-first" class="stat first"></div><span data-hf-id="hf-arrow" class="arrow"${reveal("laterAt")}>→</span>`
    + `<div data-hf-id="hf-later" class="stat later"${reveal("laterAt")}></div></div></div>`;
}
const PANEL = panel();
const TIMELINE = `var root=document.getElementById("${ID}"),tl=gsap.timeline({paused:true});`
  + `tl.fromTo(root.querySelector(".panel"),{opacity:0},{opacity:1,duration:.3,immediateRender:false},0);window.__timelines["${ID}"]=tl;`;

/** A catalog composition in the toolkit adaptation shape (variables entity-encoded on <html>, content in <template>). */
function composition(style: string, body: string): string {
  const variables = JSON.stringify(VARIABLES).replaceAll('"', "&quot;");
  return `<!doctype html><html lang="en" data-composition-id="${ID}" data-composition-variables="${variables}">`
    + `<head><meta charset="UTF-8"><title>${ID}</title></head><body><template><style>${style}</style>`
    + `<div data-hf-id="hf-root" id="${ID}" data-composition-id="${ID}" data-width="1080" data-height="1920" data-duration="12">`
    + `${body}</div><script src="assets/gsap.min.js"></script><script>${TIMELINE}</script></template></body></html>`;
}

/** The authored mount markup of run-1 Q1's numbers graphic, with chosen variable values. */
function mount(values: Record<string, unknown>, extra = ""): string {
  return `<div class="clip" id="${ID}" data-composition-id="${ID}" data-composition-src="${FILE}" `
    + `data-variable-values='${JSON.stringify(values)}' data-start="24.833333333333332" data-duration="11.4" `
    + `data-track-index="3" style="position:absolute;inset:0;width:1080px;height:1920px"${extra}></div>`;
}

/** Only the fields the declared-reveal rule reads; the rest of a project input is irrelevant here. */
function project(markup: string): NativeShortProjectInput {
  return { canvas: { frameRate: "30/1" }, extension: { markup, css: "", motion: "" } } as unknown as NativeShortProjectInput;
}

function refuses(run: () => unknown, code: string, text: string): void {
  assert.throws(run, (error: unknown) => error instanceof NativeCheckError && error.code === code
    && error.message.startsWith(`[${code}] ${text}`));
}

/** The whole rule refuses declared element `hfId` (cue `cue`) of a composition built from `style` and `body`. */
function refusesVisible(style: string, body: string, hfId: string, cue: string): void {
  refuses(() => assertNativeRevealDeclarations(project(mount({})), { [FILE]: composition(style, body) }),
    "reveal-not-statically-hidden", `Premature reveal risk: ${FILE} element ${hfId} declares data-hf-reveal=${cue} but `);
}

test("resolves a variable cue from the mount's data-variable-values, then the declared default", () => {
  const [facts] = nativeMountFacts(mount({ laterAt: 7.5, exit: 0.3 }));
  assert.deepEqual(facts, { id: ID, compositionId: ID, file: FILE, start: 24.833333333333332, duration: 11.4,
    variables: { laterAt: 7.5, exit: 0.3 } });
  const note = `<p data-hf-id="hf-note" style="opacity:0" data-hf-reveal="2.5">Later</p>`;
  const rows = declaredReveals(composition(BASE + HIDE, PANEL + note), facts, 30);
  assert.deepEqual(rows.map(row => [row.hfId, row.cue, row.cueSeconds, row.cueLocalFrame]), [
    ["hf-panel", "firstAt", 0, 0], ["hf-arrow", "laterAt", 7.5, 225], ["hf-later", "laterAt", 7.5, 225], ["hf-note", "2.5", 2.5, 75]]);
  assert.ok(rows.every(row => row.mountId === ID && row.file === FILE));
  assert.throws(() => nativeMountFacts(mount({}).replace('data-start="24.833333333333332" ', "")), /Catalog mount sn-numbers-t lacks explicit timing/u);
});

test("refuses a declared reveal hidden only by a timeline set at 0", () => {
  // run-1 Q1: no CSS hide for the panel; only the timeline's fromTo at the cue hides it, too late for frame 0.
  const files = { [FILE]: composition(BASE, PANEL) };
  refuses(() => assertNativeRevealDeclarations(project(mount({ firstAt: 2.7 })), files), "reveal-not-statically-hidden",
    `Premature reveal risk: ${FILE} element hf-panel declares data-hf-reveal=firstAt but is visible before scripts run; `
    + "hide it in its CSS rule or inline style");
});

test("accepts inline opacity:0, and a grouped CSS rule for every member", () => {
  const inline = `<p data-hf-id="hf-note" style="position:absolute;opacity:0" data-hf-reveal="2.5">Later</p>`
    + `<p data-hf-id="hf-aside" style="visibility:hidden" data-hf-reveal="laterAt">Aside</p>`;
  const files = { [FILE]: composition(BASE + HIDE, PANEL + inline) };
  const rows = assertNativeRevealDeclarations(project(mount({ firstAt: 2.7, laterAt: 7.5 })), files);
  assert.deepEqual(rows.map(row => row.hfId), ["hf-panel", "hf-arrow", "hf-later", "hf-note", "hf-aside"]);
  // Each member of the group is matched on its own: the later stat matches only the second selector.
  const reordered = { [FILE]: composition(BASE + `#${ID} .arrow,#${ID} .later,#${ID} .panel{opacity:0%}`, PANEL) };
  assert.equal(assertNativeRevealDeclarations(project(mount({})), reordered).length, 3);
});

test("refuses a later CSS rule that re-shows the element", () => {
  const later = { [FILE]: composition(BASE + HIDE + `#${ID} .row .arrow{opacity:.85}`, PANEL) };
  refuses(() => assertNativeRevealDeclarations(project(mount({})), later), "reveal-not-statically-hidden",
    `Premature reveal risk: ${FILE} element hf-arrow declares data-hf-reveal=laterAt but is visible before scripts run`);
  const note = `<p data-hf-id="hf-note" class="note" style="opacity:0" data-hf-reveal="2.5">Later</p>`;
  const important = { [FILE]: composition(BASE + HIDE + `#${ID} .note{opacity:1 !important}`, PANEL + note) };
  refuses(() => assertNativeRevealDeclarations(project(mount({})), important), "reveal-not-statically-hidden",
    `Premature reveal risk: ${FILE} element hf-note declares data-hf-reveal=2.5 but is visible before scripts run`);
  const inlineNote = (style: string) => `<p data-hf-id="hf-note" class="note" style="${style}" data-hf-reveal="2.5">x</p>`;
  // An @media rule can re-show the element but never proves it hidden.
  refusesVisible(BASE + HIDE + `@media (min-width:1px){#${ID} .arrow{opacity:1}}`, PANEL, "hf-arrow", "laterAt");
  refusesVisible(BASE + `#${ID} .panel,#${ID} .later{opacity:0}@media (min-width:1px){#${ID} .arrow{opacity:0}}`, PANEL,
    "hf-arrow", "laterAt");
  // A normal inline opacity overrides a zero rule.
  refusesVisible(BASE + HIDE + `#${ID} .note{opacity:0}`, PANEL + inlineNote("opacity:1"), "hf-note", "2.5");
  // A selector linkedom cannot evaluate is refused by name; there is no string fallback.
  refuses(() => assertNativeRevealDeclarations(project(mount({})), { [FILE]: composition(BASE + HIDE
    + `#${ID} .panel::before{opacity:1}`, PANEL) }), "reveal-not-statically-hidden", `Premature reveal risk: ${FILE} `
    + `element hf-panel declares data-hf-reveal=firstAt but selector '#${ID} .panel::before' cannot be evaluated`);
  // A repeated data-hf-id cannot hide a visible twin.
  refusesVisible(BASE + HIDE, PANEL + `<i data-hf-id="hf-arrow" class="twin" data-hf-reveal="laterAt">→</i>`, "hf-arrow", "laterAt");
  // Inline visibility:hidden proves nothing when a child sets itself visible or a sheet can win with !important.
  const aside = (inner: string) => `<p data-hf-id="hf-aside" style="visibility:hidden" data-hf-reveal="2.5">${inner}</p>`;
  refusesVisible(BASE + HIDE, PANEL + aside(`<b style="visibility:visible">shown</b>`), "hf-aside", "2.5");
  refusesVisible(BASE + HIDE + `#${ID} p{visibility:visible !important}`, PANEL + aside(""), "hf-aside", "2.5");
  // `all` resets visibility too (X77 dm1), inline or in a sheet; an unparsable descendant style proves nothing.
  refusesVisible(BASE + HIDE, PANEL + aside(`<b style="all:initial">shown</b>`), "hf-aside", "2.5");
  refusesVisible(BASE + HIDE + `#${ID} .kid{all:initial}`, PANEL + aside(`<b class="kid">shown</b>`), "hf-aside", "2.5");
  refusesVisible(BASE + HIDE, PANEL + aside(`<b style="a:b}x{c:d">shown</b>`), "hf-aside", "2.5");
  refusesVisible(BASE + HIDE, PANEL + `<p data-hf-id="hf-aside" style="visibility:hidden;all:initial" data-hf-reveal="2.5">x</p>`,
    "hf-aside", "2.5");
});

test("refuses a cue outside the mount and a declaration without data-hf-id", () => {
  const [facts] = nativeMountFacts(mount({ laterAt: 11.4 }));
  const html = (body: string) => composition(BASE + HIDE, body);
  refuses(() => declaredReveals(html(`<p data-hf-id="hf-note" data-hf-reveal="12">x</p>`), facts, 30), "reveal-cue-invalid",
    `Declared reveal hf-note in ${FILE}: cue 12s lies outside mount ${ID} (0-11.4s)`);
  refuses(() => declaredReveals(html(PANEL), facts, 30), "reveal-cue-invalid",
    `Declared reveal hf-arrow in ${FILE}: cue 11.4s lies outside mount ${ID} (0-11.4s)`);
  refuses(() => declaredReveals(html(`<p class="note" data-hf-reveal="2">x</p>`), facts, 30), "reveal-cue-invalid",
    `Declared reveal in ${FILE} needs a data-hf-id handle`);
  for (const cue of ["soon", "unit", "-1"]) {
    refuses(() => declaredReveals(html(`<p data-hf-id="hf-note" data-hf-reveal="${cue}">x</p>`), facts, 30), "reveal-cue-invalid",
      `Declared reveal hf-note in ${FILE}: cue '${cue}' is neither a numeric composition variable nor seconds`);
  }
  // A mount of a file that declares a reveal needs its ids and explicit timing, and is refused by name (X72 M1).
  const files = { [FILE]: composition(BASE + HIDE, PANEL) };
  assert.throws(() => assertNativeRevealDeclarations(project(mount({}).replace(`data-composition-id="${ID}" `, "")), files),
    /^Error: Catalog mount sn-numbers-t lacks a stable id or data-composition-id$/u);
  assert.throws(() => assertNativeRevealDeclarations(project(mount({}).replace('data-duration="11.4" ', "")), files),
    /^Error: Catalog mount sn-numbers-t lacks explicit timing$/u);
});

test("ignores compositions without declarations", () => {
  // The saved run-1 shape: an unhidden panel but no data-hf-reveal, next to a title mount; plus CSS no parser reads.
  const title = `<div class="clip" id="sn-title-t" data-composition-id="sn-title-t" data-composition-src="compositions/title-t.html" `
    + `data-start="0" data-duration="4.8"></div>`;
  const files = { [FILE]: composition(BASE, panel(false)),
    "compositions/title-t.html": composition("#t{color:", "<p data-hf-id=\"hf-t\">Title</p>") };
  assert.deepEqual(assertNativeRevealDeclarations(project(title + mount({ firstAt: 2.7 })), files), []);
  // Legacy mounts of undeclared files keep building and cold-reading without ids or timing (X72 M1), e.g. the
  // native-catalog-files.test.ts fixture mount, which has no data-composition-id.
  const legacy = `<div id="catalog-counter" class="clip" data-composition-src="compositions/counter.html" data-start="0" `
    + `data-duration="1" data-track-index="1"></div><div class="clip" data-composition-src="compositions/bare.html"></div>`;
  const undeclared = { "compositions/counter.html": composition(BASE, panel(false)), "compositions/bare.html": composition(BASE, "") };
  assert.deepEqual(assertNativeRevealDeclarations(project(legacy), undeclared), []);
  assert.deepEqual(assertNativeRevealDeclarations(project(""), {}), []);
  assert.throws(() => assertNativeRevealDeclarations(project(mount({})), {}), /names compositions\/numbers-t\.html, which is not a staged catalog file/u);
  assert.throws(() => assertNativeRevealDeclarations(project('<div data-composition-src="compositions/gone.html"></div>'), {}),
    /^Error: Catalog mount without an id names compositions\/gone\.html, which is not a staged catalog file$/u);
});
