/** Supplied-only SDK proposals: library plus bounded JSON stdio, never HTML persistence or rendering. */
import { createHash } from "node:crypto";
import { constants, openSync, closeSync, fstatSync, lstatSync, readSync, realpathSync } from "node:fs";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { isDeepStrictEqual } from "node:util";
import { openComposition } from "@hyperframes/sdk";

const INSTALLED_SDK = Object.freeze({ openComposition });
const SUPPORTED_BUNDLE_RUNTIMES = ["0.7.33", "0.8.31"];
const KEYS = ["html", "originalHtmlSha256", "scene", "bundle", "unitId", "elementId",
  "variable", "expectedValue", "value", "expectedSceneVersion"];
const SCENE_KEYS = ["schemaVersion", "sceneId", "version", "timing", "canvas", "renderMode",
  "composition", "elements", "renderUnits", "captionPolicy", "dependencies", "provenance", "visualSources"];
const MANIFEST_KEYS = ["schemaVersion", "bundleId", "fullEntry", "unitEntries", "supportedCanvases",
  "supportedFps", "variables", "assetIds", "seed", "runtime"];
const sha = value => createHash("sha256").update(value).digest("hex");

function requireValue(condition, message) {
  if (!condition) throw new Error(`SDK scene proposal: ${message}`);
}

function closed(value, keys) {
  requireValue(value !== null && typeof value === "object" && Object.getPrototypeOf(value) === Object.prototype
    && isDeepStrictEqual(Object.keys(value).sort(), [...keys].sort()), "closed fields differ");
}

function factory(sdk) {
  closed(sdk, ["openComposition"]);
  requireValue(Reflect.ownKeys(sdk).length === 1, "unexpected SDK factory fields");
  const descriptor = Object.getOwnPropertyDescriptor(sdk, "openComposition");
  requireValue("value" in descriptor && typeof descriptor.value === "function", "own data SDK factory required");
  return descriptor.value;
}

/** Bound plain supplied JSON before the first injected SDK callback, including getters/cycles. */
function snapshot(value) {
  const pending = [{ value, depth: 0 }]; let nodes = 0, bytes = 0;
  while (pending.length) {
    const item = pending.pop(), current = item.value;
    requireValue(++nodes <= 8192 && item.depth <= 12, "input structure exceeds bound");
    if (typeof current === "string") {
      bytes += Buffer.byteLength(current); requireValue(bytes <= 1024 * 1024, "input strings exceed bound"); continue;
    }
    if (current === null || typeof current === "boolean") continue;
    if (typeof current === "number") { requireValue(Number.isFinite(current), "non-finite value"); continue; }
    requireValue(typeof current === "object" && (Array.isArray(current)
      || Object.getPrototypeOf(current) === Object.prototype), "plain JSON required");
    requireValue(!Array.isArray(current) || Object.getPrototypeOf(current) === Array.prototype && Object.keys(current).length === current.length
      && Object.keys(current).every((key, index) => key === String(index)), "dense plain array required");
    const descriptors = Object.getOwnPropertyDescriptors(current);
    requireValue(Reflect.ownKeys(current).every(key => typeof key === "string"), "symbol field unsupported");
    for (const [key, descriptor] of Object.entries(descriptors)) {
      bytes += Buffer.byteLength(key); requireValue(bytes <= 1024 * 1024, "input keys exceed bound");
      requireValue("value" in descriptor && (descriptor.enumerable || key === "length"), "accessors/hidden data unsupported");
      pending.push({ value: descriptor.value, depth: item.depth + 1 });
    }
  }
  const text = JSON.stringify(value);
  requireValue(Buffer.byteLength(text) <= 1024 * 1024, "input JSON exceeds 1 MiB");
  return JSON.parse(text);
}

function unique(rows, key) {
  requireValue(Array.isArray(rows) && rows.length > 0 && rows.length <= 256, "bounded nonempty rows required");
  requireValue(new Set(rows.map(row => row[key])).size === rows.length, "duplicate identity");
}

function one(rows, predicate) {
  const selected = rows.filter(predicate);
  requireValue(selected.length === 1, "target must resolve exactly once");
  return selected[0];
}

function stable(value) {
  requireValue(typeof value === "string" && value.length <= 96 && /^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$/u.test(value), "stable ID required");
}

function originalBinding(input) {
  closed(input, KEYS); closed(input.scene, SCENE_KEYS);
  closed(input.bundle, ["hash", "manifest", "files"]); closed(input.bundle.manifest, MANIFEST_KEYS);
  const { scene, bundle } = input, manifest = bundle.manifest;
  requireValue(typeof input.html === "string" && Buffer.byteLength(input.html) <= 512 * 1024, "HTML exceeds 512 KiB");
  requireValue(/^[a-f0-9]{64}$/u.test(input.originalHtmlSha256) && sha(input.html) === input.originalHtmlSha256, "original HTML SHA differs");
  requireValue(/^[a-f0-9]{64}$/u.test(bundle.hash) && scene.composition.bundleHash === bundle.hash, "supplied bundle hash differs");
  requireValue(scene.schemaVersion === 1 && manifest.schemaVersion === 1 && scene.composition.type === "project"
    && scene.composition.bundleId === manifest.bundleId
    && SUPPORTED_BUNDLE_RUNTIMES.includes(manifest.runtime.hyperframesVersion), "unsupported scene/runtime binding");
  requireValue(Number.isSafeInteger(input.expectedSceneVersion) && input.expectedSceneVersion > 0
    && scene.version === input.expectedSceneVersion, "stale scene version");
  [scene.sceneId, input.unitId, input.elementId].forEach(stable);
  requireValue(typeof input.variable === "string" && /^[A-Za-z][A-Za-z0-9_]{0,95}$/u.test(input.variable), "declared variable ID required");
  unique(scene.elements, "elementId"); unique(scene.renderUnits, "unitId"); unique(manifest.variables, "id"); unique(bundle.files, "path");
  const element = one(scene.elements, row => row.elementId === input.elementId);
  const owners = scene.elements.filter(row => row.exposedProperties.includes(input.variable) || Object.hasOwn(row.values, input.variable));
  requireValue(owners.length === 1 && owners[0] === element && element.exposedProperties.includes(input.variable), "shared or unexposed variable unsupported");
  const unit = one(scene.renderUnits, row => row.elementIds.includes(input.elementId));
  const declaration = one(manifest.variables, row => row.id === input.variable);
  requireValue(unit.unitId === input.unitId && isDeepStrictEqual(declaration.elementIds, [input.elementId]), "variable/unit ownership differs");
  requireValue(unit.entry === manifest.unitEntries[input.unitId], "bundle unit entry differs");
  const file = one(bundle.files, row => row.path === unit.entry);
  closed(file, ["path", "sha256", "sizeBytes"]);
  requireValue(file.sha256 === input.originalHtmlSha256 && file.sizeBytes === Buffer.byteLength(input.html), "supplied bundle file differs");
  requireValue(declaration.type === "string" && typeof input.expectedValue === "string" && typeof input.value === "string"
    && input.value.trim().length > 0 && input.value !== input.expectedValue, "only changed declared text is supported");
  const limit = declaration.maxLength ?? 1000;
  requireValue(Number.isSafeInteger(limit) && limit > 0 && limit <= 4000
    && [input.expectedValue, input.value].every(value => Array.from(value).length <= Math.min(limit, 1000)), "copy exceeds declared bound");
  requireValue(element.values[input.variable] === input.expectedValue
    && scene.composition.variables[input.variable] === input.expectedValue, "stale element/composition value");
}

/** Compare static decimal root duration to the original frame window with exact integer arithmetic. */
function rootTiming(root, scene) {
  closed(scene.canvas, ["width", "height"]);
  closed(scene.timing, ["startFrame", "endFrameExclusive", "fps", "timelineMapHash"]);
  const { startFrame, endFrameExclusive, fps } = scene.timing;
  closed(fps, ["numerator", "denominator"]);
  requireValue([scene.canvas.width, scene.canvas.height].every(value => Number.isSafeInteger(value) && value > 0)
    && root.attributes["data-width"] === String(scene.canvas.width)
    && root.attributes["data-height"] === String(scene.canvas.height), "root geometry differs from scene");
  requireValue(Number.isSafeInteger(startFrame) && startFrame >= 0 && Number.isSafeInteger(endFrameExclusive)
    && endFrameExclusive > startFrame, "exact scene frame window required");
  requireValue([fps.numerator, fps.denominator].every(value => typeof value === "string"
    && /^[1-9][0-9]{0,17}$/u.test(value)), "exact bounded scene rate required");
  const duration = root.attributes["data-duration"];
  requireValue(typeof duration === "string" && /^(?:0|[1-9][0-9]{0,17})(?:\.[0-9]{1,18})?$/u.test(duration), "static decimal root duration required");
  const [whole, fractional = ""] = duration.split(".");
  const ticks = BigInt(whole + fractional), scale = 10n ** BigInt(fractional.length);
  requireValue(ticks * BigInt(fps.numerator) === BigInt(endFrameExclusive - startFrame) * BigInt(fps.denominator) * scale,
    "root duration differs from exact scene frame window");
}

/** Keep the complete SDK-open byte baseline; normalization never becomes replacement source HTML. */
function baseline(session, input) {
  const html = session.serialize(), declarations = snapshot(session.listVariables());
  requireValue(typeof html === "string" && Buffer.byteLength(html) <= 1024 * 1024, "serialized baseline exceeds bound");
  unique(declarations, "id");
  const declared = one(declarations, row => row.id === input.variable);
  requireValue(declared.type === "string" && declared.default === input.expectedValue
    && session.getVariableValue(input.variable) === input.expectedValue, "SDK declaration/current value differs");
  const root = one(session.getElements(), row => Boolean(row.attributes["data-composition-id"]));
  requireValue(typeof root.id === "string" && root.id === root.scopedId && root.id.length <= 256, "ambiguous SDK root");
  rootTiming(root, input.scene);
  return { html, declarations, timing: snapshot(session.getElementTimings()), rootId: root.id,
    css: root.inlineStyles[`--${input.variable}`] ?? null };
}

function expectedPatches(input, before) {
  const id = before.rootId.replaceAll("~", "~0").replaceAll("/", "~1");
  const variable = `/variables/${input.variable}`, css = `/elements/${id}/inlineStyles/--${input.variable}`;
  const forward = [{ op: "replace", path: variable, value: input.value }];
  const inverse = [{ op: "replace", path: variable, value: input.expectedValue }];
  if (before.css !== input.value) {
    forward.push({ op: before.css === null ? "add" : "replace", path: css, value: input.value });
    inverse.unshift(before.css === null ? { op: "remove", path: css } : { op: "replace", path: css, value: before.css });
  }
  return { forward, inverse };
}

function mutate(session, input, before) {
  const events = [], expected = expectedPatches(input, before);
  const unsubscribe = session.on("patch", event => events.push(snapshot(event)));
  try {
    requireValue(session.can({ type: "setVariableValue", id: input.variable, value: input.value }).ok === true, "SDK refused variable");
    session.setVariableValue(input.variable, input.value);
  } finally { unsubscribe(); }
  requireValue(events.length === 1, "unexpected patch count");
  closed(events[0], ["formatVersion", "patches", "inversePatches", "origin", "opTypes"]);
  requireValue(events[0].formatVersion === 1 && events[0].origin === "local"
    && isDeepStrictEqual(events[0].opTypes, ["setVariableValue"])
    && isDeepStrictEqual(events[0].patches, expected.forward)
    && isDeepStrictEqual(events[0].inversePatches, expected.inverse), "patch paths or typed values differ");
  return expected.inverse;
}

function readback(session, input, captured) {
  const { before, inverse, candidate } = captured;
  requireValue(session.serialize() === candidate, "reopened serialized candidate differs");
  const declarations = snapshot(before.declarations);
  one(declarations, row => row.id === input.variable).default = input.value;
  requireValue(session.getVariableValue(input.variable) === input.value
    && isDeepStrictEqual(session.listVariables(), declarations), "reopened declarations differ");
  requireValue(isDeepStrictEqual(session.getElementTimings(), before.timing), "reopened timing differs");
  session.applyPatches(inverse);
  requireValue(session.serialize() === before.html, "unaffected serialized code/structure changed");
}

async function dispose(sessions, errors) {
  for (const session of [...sessions].reverse()) {
    try { await session.dispose(); } catch (error) { errors.push(error); }
  }
}

/** Validate one supplied text revision; all real bundle/source, render and publication authority stays outside. */
export async function proposeSceneVariable(input, sdk = INSTALLED_SDK) {
  const fixed = snapshot(input), open = factory(sdk); originalBinding(fixed);
  const unchanged = () => requireValue(isDeepStrictEqual(snapshot(input), fixed) && factory(sdk) === open, "original supplied input/factory changed");
  const sessions = [], errors = [];
  try {
    const first = await open(fixed.html, { history: false }); sessions.push(first); unchanged();
    const before = baseline(first, fixed), inverse = mutate(first, fixed, before);
    const candidate = first.serialize(); requireValue(Buffer.byteLength(candidate) <= 1024 * 1024, "serialized candidate exceeds bound"); unchanged();
    const second = await open(candidate, { history: false }); sessions.push(second); unchanged();
    requireValue(second !== first, "SDK reopen must return a distinct session");
    readback(second, fixed, { before, inverse, candidate }); unchanged();
  } catch (error) { errors.push(error); }
  await dispose(sessions, errors);
  try { unchanged(); } catch (error) { errors.push(error); }
  if (errors.length) throw new AggregateError(errors, "SDK scene proposal refused; no state was published");
  return { operation: { schemaVersion: 1, operation: "title.setText", sceneId: fixed.scene.sceneId,
    elementId: fixed.elementId, variable: fixed.variable, text: fixed.value,
    expectedText: fixed.expectedValue, expectedSceneVersion: fixed.expectedSceneVersion },
    proposalOnly: true, applied: false, approved: false, renderVerified: false, suppliedBindingsOnly: true };
}

/** Read the bridge's exact temporary JSON, bounded before allocation and never execute source HTML. */
function requestIdentity(info) {
  return [info.dev, info.ino, info.mode, info.nlink, info.uid, info.size, info.mtimeNs, info.ctimeNs];
}

/** Access time can move on a read; byte size, inode and write metadata cannot. */
function commandInput() {
  requireValue(process.argv.length === 5, "command requires request path, SHA256 and byte size");
  const [path, digest, count] = process.argv.slice(2), size = Number(count);
  requireValue(path === resolve(path) && realpathSync(path) === path && /^[a-f0-9]{64}$/u.test(digest)
    && String(size) === count && Number.isSafeInteger(size) && size > 0 && size <= 1024 * 1024, "invalid bounded request reference");
  const fd = openSync(path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
  try {
    const before = fstatSync(fd, { bigint: true }), bytes = Buffer.alloc(size + 1);
    requireValue(before.isFile() && before.nlink === 1n && before.uid === BigInt(process.getuid())
      && before.size === BigInt(size), "request is not one exact owned regular file");
    requireValue(readSync(fd, bytes, 0, bytes.length, null) === size && readSync(fd, Buffer.alloc(1), 0, 1, null) === 0,
      "request size changed");
    requireValue(isDeepStrictEqual(requestIdentity(before), requestIdentity(fstatSync(fd, { bigint: true })))
      && isDeepStrictEqual(requestIdentity(before), requestIdentity(lstatSync(path, { bigint: true })))
      && realpathSync(path) === path && sha(bytes.subarray(0, size)) === digest, "request identity or SHA changed");
    return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes.subarray(0, size)));
  } finally { closeSync(fd); }
}

/** The command uses only the installed SDK; injection remains a library-test seam. */
async function command() {
  const result = JSON.stringify(await proposeSceneVariable(commandInput()));
  requireValue(Buffer.byteLength(result) <= 64 * 1024, "stdout exceeds 64 KiB");
  process.stdout.write(`${result}\n`);
}

if (process.argv[1] && pathToFileURL(resolve(process.argv[1])).href === import.meta.url) {
  try { await command(); } catch {
    process.stderr.write("SDK text proposal refused; no state was applied or approved.\n");
    process.exitCode = 65;
  }
}
