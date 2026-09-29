/**
 * The runtime reveal probe's project (MASTER-PLAN M-068, P2-EARLY-CHECKS P2-03).
 *
 * Writes a new, graphics-only native project from a plan JSON or a built project: every catalog mount with its
 * exact markup (`data-start`, `data-duration`, `data-variable-values`, host style) and the scene extension's CSS,
 * inside the root skeleton the build emits (`nativeRootDocument`), with no footage, captions or title card. The
 * catalog compositions are staged through `nativeCatalogFiles` (the build's validation); the pinned GSAP and the
 * font files the root or a composition references are copied from the plan's bound assets. `REVEAL-PROBE.json`
 * names each mount's active root frames and its declared reveals for `studio/native_reveal_probe.mjs`, which seeks
 * the project in the pinned runtime. Nothing here renders, decodes or runs a browser.
 */
import { constants, copyFileSync, mkdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import path from "node:path";
import { canonicalJson, fileSha256 } from "./auto-edit-hash";
import type { NativeAssetBinding } from "./native-short-strategy";
import { nativeCatalogFiles } from "./native-catalog-files";
import { assertNativeRevealDeclarations, nativeMountFacts, type NativeMountFacts,
  type NativeRevealDeclaration } from "./native-reveal-declarations";
import { mountFrames } from "./native-review-regions";
import { nativeRootDocument } from "./native-root-document";
import { buildNativeCanvas } from "./native-short-composition";
import { readNativeShortProject, type NativeShortProjectInput } from "./native-short-project";

/** One probed catalog mount: its facts and its active root frames `[first, endExclusive)`. */
export type RevealProbeMount = NativeMountFacts & { first: number; endExclusive: number };

/** `REVEAL-PROBE.json`: which mounts the runtime probe seeks, at which frames, and which reveals are declared. */
export interface RevealProbeManifest {
  schemaVersion: 1;
  source: { plan: string; sha256: string };
  rate: number;
  totalFrames: number;
  mounts: RevealProbeMount[];
  declarations: NativeRevealDeclaration[];
}

/** The probe root's title; seeking graphics needs no plan title. */
const TITLE = "Native reveal probe";
/** The shared runtime script every native root loads. */
const GSAP = "assets/gsap.min.js";
/** Font files by extension; one is copied only when the root or a composition references its path. */
const FONT = /\.(?:otf|ttf|woff2?)$/iu;

interface ProbeSource { plan: NativeShortProjectInput; file: string; sha256: string }

/**
 * A built project is read by the cold reader (the full build validation). A plan JSON gets the canvas validation
 * `measure` uses; the rest of assembly is not repeated for it, because assembly hashes every asset (X74).
 */
function probeSource(input: string): ProbeSource {
  const directory = statSync(input).isDirectory(), file = directory ? path.join(input, "SHORT-PROJECT.json") : input;
  const plan = directory ? readNativeShortProject(input, {}, undefined, "draft")
    : JSON.parse(readFileSync(file, "utf8")) as NativeShortProjectInput;
  if (!directory) buildNativeCanvas(plan.canvas);
  const sha256 = fileSha256(file);
  if (!sha256) throw new Error(`Reveal probe source plan disappeared: ${file}`);
  return { plan, file, sha256 };
}

/** The mount's active root frames by the runtime's own snap (`mountFrames`); it must lie inside the Short. */
function probeMount(mount: NativeMountFacts, rate: number, totalFrames: number): RevealProbeMount {
  const range = mountFrames({ "data-start": String(mount.start), "data-duration": String(mount.duration) }, rate);
  if (!range || range[0] >= range[1] || range[1] > totalFrames) {
    throw new Error(`Catalog mount ${mount.id} has no exact frame range inside the Short`);
  }
  return { ...mount, first: range[0], endExclusive: range[1] };
}

/** The pinned GSAP and each font whose path the root or a composition references, as the plan binds them. */
function probeAssets(plan: NativeShortProjectInput, documents: string[]): NativeAssetBinding[] {
  const referenced = (file: string) => documents.some(text => text.includes(file));
  const rows = plan.assets.filter(row => path.posix.dirname(row.file) === "assets"
    && (row.file === GSAP || (FONT.test(row.file) && referenced(row.file))));
  if (!rows.some(row => row.file === GSAP)) throw new Error("Reveal probe needs the plan's pinned GSAP runtime asset");
  return rows;
}

/** Copy each asset exclusively and re-hash the copy against the plan's binding. */
function stageAssets(rows: NativeAssetBinding[], directory: string): void {
  mkdirSync(path.join(directory, "assets"), { mode: 0o700 });
  for (const row of rows) {
    const target = path.join(directory, row.file);
    copyFileSync(row.path, target, constants.COPYFILE_EXCL | constants.COPYFILE_FICLONE);
    if (fileSha256(target) !== row.sha256) throw new Error(`Reveal probe asset changed while staging: ${row.file}`);
  }
}

/**
 * Write a new graphics-only probe project and return its manifest. Every check runs before the directory exists.
 * @param input a plan JSON, or a built native project directory
 * @param destination a new directory (refused when it exists)
 * @returns the `REVEAL-PROBE.json` manifest
 */
export function writeNativeRevealProbeProject(input: string, destination: string): RevealProbeManifest {
  const source = probeSource(path.resolve(input)), plan = source.plan, directory = path.resolve(destination);
  const { frameRate, totalFrames, background } = plan.canvas, [num, den] = frameRate.split("/").map(Number);
  const markup = plan.extension?.markup ?? "", compositions = nativeCatalogFiles(plan.catalogFiles);
  const declarations = assertNativeRevealDeclarations(plan, compositions);
  const mounts = nativeMountFacts(markup).map(mount => probeMount(mount, num / den, totalFrames));
  if (!mounts.length) throw new Error("Reveal probe needs at least one catalog mount");
  // P2-03 keeps the mounts' markup and the extension CSS only; the root timeline registers the canvas alone.
  const html = nativeRootDocument({ title: TITLE, background, fontFaces: "", head: plan.extension?.css ?? "",
    frameRate, totalFrames, content: markup, timeline: "" });
  const assets = probeAssets(plan, [html, ...Object.values(compositions)]);
  const manifest: RevealProbeManifest = { schemaVersion: 1, source: { plan: source.file, sha256: source.sha256 },
    rate: num / den, totalFrames, mounts, declarations };
  mkdirSync(directory, { mode: 0o700 });
  mkdirSync(path.join(directory, "compositions"), { mode: 0o700 });
  stageAssets(assets, directory);
  const files = { "index.html": html, ...compositions, "REVEAL-PROBE.json": canonicalJson(manifest),
    "SHORT-PROJECT.json": canonicalJson({ schemaVersion: 1, canvas: { frameRate, totalFrames } }) };
  for (const [name, content] of Object.entries(files)) writeFileSync(path.join(directory, name), content, { flag: "wx", mode: 0o600 });
  return manifest;
}
