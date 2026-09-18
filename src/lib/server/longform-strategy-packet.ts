/** Immutable local strategy packets; no renderer or provider admission. */
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { assertCutPreviewDirectory, observeCutPreviewFile } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { objectValue, stringValue } from "@/lib/producer/contracts/validation";
import { canonicalJson, canonicalJsonSha256 } from "./auto-edit-hash";
import { strategyFile, type StrategyFilePin } from "./reference-strategy-library";

const SCOPE = "local-longform-request-awaiting-editorial-strategy";
const REQUEST = "LONG-REQUEST.json";
const MAX_FILE_BYTES = 64 * 1024 ** 3;

/** Stream even long source recordings through the existing stable-file observer. */
export function longformInputPin(file: string): StrategyFilePin {
  const held = observeCutPreviewFile(file, MAX_FILE_BYTES);
  return { path: file, sha256: held.sha256, sizeBytes: held.sizeBytes };
}

function documentName(name: string): string {
  if (!/^[A-Za-z0-9][A-Za-z0-9_.-]{0,180}$/u.test(name) || name === REQUEST) {
    throw new Error("Invalid long-form strategy document name");
  }
  return name;
}

function writeExact(file: string, text: string): void {
  if (existsSync(file)) {
    if (strategyFile(file).text !== text) throw new Error("Saved long-form strategy document changed");
    return;
  }
  writeFileSync(file, text, { flag: "wx", mode: 0o600 });
}

function uniquePins(pins: StrategyFilePin[]): StrategyFilePin[] {
  const result = new Map<string, StrategyFilePin>();
  for (const pin of pins) {
    const previous = result.get(pin.path);
    if (previous && canonicalJson(previous) !== canonicalJson(pin)) throw new Error("Conflicting long-form input pins");
    result.set(pin.path, pin);
  }
  return [...result.values()];
}

function childDirectory(parent: string, name: string): string {
  assertCutPreviewDirectory(parent);
  const directory = path.join(parent, name);
  if (!existsSync(directory)) mkdirSync(directory, { mode: 0o700 });
  assertCutPreviewDirectory(directory);
  return directory;
}

/** Content-address the complete packet and retain previous versions without overwriting. */
export function writeLongformPacket(input: {
  producerDir: string; request: Record<string, unknown>; files: Record<string, string>; pins: StrategyFilePin[];
}) {
  assertCutPreviewDirectory(input.producerDir);
  const documents = Object.fromEntries(Object.entries(input.files).map(([name, text]) =>
    [documentName(name), canonicalJsonSha256(text)]));
  const inputPins = uniquePins(input.pins);
  const packet = { ...input.request, schemaVersion: 1, scope: SCOPE, inputPins, documents,
    providerCalls: 0, renderApproved: false, strategyAuthored: false };
  const requestHash = canonicalJsonSha256(packet);
  const parent = childDirectory(childDirectory(input.producerDir, "native-longform"), "requests");
  const directory = childDirectory(parent, requestHash);
  for (const [name, text] of Object.entries(input.files)) writeExact(path.join(directory, name), text);
  writeExact(path.join(directory, REQUEST), canonicalJson(packet));
  return { directory, requestHash, packet };
}

/** Check all supplied files and preserved documents before a later reasoning session. */
export function readLongformPacket(directory: string) {
  assertCutPreviewDirectory(directory);
  const packet = objectValue(JSON.parse(strategyFile(path.join(directory, REQUEST)).text), "long-form packet");
  if (packet.schemaVersion !== 1 || packet.scope !== SCOPE || packet.renderApproved !== false
      || packet.strategyAuthored !== false || packet.providerCalls !== 0
      || canonicalJsonSha256(packet) !== path.basename(directory)) throw new Error("Long-form packet identity changed");
  const pins = packet.inputPins;
  if (!Array.isArray(pins) || !pins.length || pins.length > 10_000) throw new Error("Long-form input inventory is invalid");
  for (const value of pins) {
    const pin = objectValue(value, "input pin"), file = stringValue(pin.path, "input path", 4096);
    if (canonicalJson(longformInputPin(file)) !== canonicalJson(pin)) throw new Error(`Long-form input changed: ${file}`);
  }
  const documents = objectValue(packet.documents, "strategy documents");
  for (const [name, hash] of Object.entries(documents)) {
    if (canonicalJsonSha256(strategyFile(path.join(directory, documentName(name))).text) !== hash) {
      throw new Error(`Long-form strategy document changed: ${name}`);
    }
  }
  return packet;
}
