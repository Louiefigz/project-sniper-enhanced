/** Physical media preparation preserves the original editorial and transcript clocks. */
import { execFileSync } from "node:child_process";
import { mkdirSync, realpathSync, writeFileSync } from "node:fs";
import path from "node:path";
import { pythonInterpreter } from "@/app/api/_lib/spawn-python";
import { fileSha256 } from "./auto-edit-hash";
import type { NativeShortProjectInput } from "./native-short-project";

export interface PreparedSourcesBinding { path: string; sha256: string }
export interface PreparedAsset {
  file: string; path: string; sha256: string; bytes: number;
  sourceOrigin: string; sourceStart: string; sourceEnd: string;
}
export interface PreparedSourceResult {
  schemaVersion: 1;
  selection: { sources: Array<{ file: string; path: string; sha256: string }> };
  sections: Array<{ sourceFile: string; video: PreparedAsset; audio: PreparedAsset | null }>;
}
interface MediaUse { id: string; kind: "video" | "audio"; sourceFile: string; start: number; end: number }
export interface PreparedMediaMapping extends MediaUse { preparedFile: string; mediaStart: number; sourceOrigin: string }

function rational(value: string): number {
  if (!/^-?\d+(?:\/\d+)?$/u.test(value)) throw new Error("Invalid prepared rational clock");
  const [num, den = "1"] = value.split("/"), result = Number(num) / Number(den);
  if (!Number.isFinite(result)) throw new Error("Invalid prepared rational clock");
  return result;
}

function attribute(tag: string, name: string): string {
  const values = [...tag.matchAll(new RegExp(`\\s${name}="([^"]*)"`, "gu"))];
  if (values.length !== 1) throw new Error(`Prepared media needs one explicit ${name}`);
  return values[0][1];
}

function mediaUse(tag: string, kind: "video" | "audio"): MediaUse {
  const start = Number(attribute(tag, "data-media-start")), duration = Number(attribute(tag, "data-duration"));
  if (!Number.isFinite(start) || start < 0 || !Number.isFinite(duration) || duration <= 0
      || /\sdata-playback-(?:rate|start)\b/iu.test(tag)) throw new Error("Prepared media requires a bounded speed-one range");
  return { id: attribute(tag, "id"), kind, sourceFile: attribute(tag, "src"), start, end: start + duration };
}

/** Collect actual media ranges after the normal source/strategy validators pass. */
export function selectedSourceRequest(input: NativeShortProjectInput, html: string) {
  const ranges = [...html.matchAll(/<(video|audio)\b[^>]*>/giu)].map(match => mediaUse(match[0], match[1].toLowerCase() as "video" | "audio"))
    .map(({ sourceFile, start, end }) => ({ sourceFile, start, end }));
  const unique = [...new Map(ranges.map(row => [JSON.stringify(row), row])).values()];
  const files = new Set(unique.map(row => row.sourceFile));
  const sources = input.assets.filter(row => files.has(row.file)).map(({ file, path, sha256 }) => ({ file, path, sha256 }));
  if (sources.length !== files.size) throw new Error("Selected media range lacks an original asset");
  return { schemaVersion: 1, sources, ranges: unique, handleSeconds: 1 };
}

/** Prepare once at the CLI boundary; visual revisions retain and reuse the returned binding. */
export function prepareNativeSourceMedia(input: NativeShortProjectInput, html: string, destination: string): NativeShortProjectInput {
  if (input.preparedSources) {
    preparedProjectMedia(input, html);
    return input;
  }
  const root = path.resolve(destination), selection = selectedSourceRequest(input, html);
  if (realpathSync(path.dirname(root)) !== path.dirname(root)) throw new Error("Prepared source destination parent must be canonical");
  mkdirSync(root, { mode: 0o700 });
  const request = path.join(root, "selection.json");
  writeFileSync(request, JSON.stringify(selection), { flag: "wx", mode: 0o600 });
  execFileSync(pythonInterpreter(), [path.resolve("scripts/producer/edit/selected_sources.py"), "prepare", request, path.join(root, "package")],
    { cwd: process.cwd(), encoding: "utf8", timeout: 660_000, maxBuffer: 16 * 1024 * 1024 });
  const receipt = path.join(root, "package/run/selected-sources-stage.json");
  const sha256 = fileSha256(receipt);
  if (!sha256) throw new Error("Selected preparation did not produce a sealed package");
  const plan = { ...input, preparedSources: { path: receipt, sha256 } };
  preparedProjectMedia(plan, html);
  writeFileSync(path.join(root, "prepared-plan.json"), JSON.stringify(plan), { flag: "wx", mode: 0o600 });
  return plan;
}

/** Invoke the same read-only stage verifier used by the media owner and exporter. */
export function loadPreparedSources(binding: PreparedSourcesBinding): PreparedSourceResult {
  if (!path.isAbsolute(binding.path) || realpathSync(binding.path) !== binding.path
      || !/^[a-f0-9]{64}$/u.test(binding.sha256) || fileSha256(binding.path) !== binding.sha256) {
    throw new Error("Prepared source binding changed");
  }
  const raw = execFileSync(pythonInterpreter(), [path.resolve("scripts/producer/edit/selected_sources.py"), "check", binding.path],
    { cwd: process.cwd(), encoding: "utf8", timeout: 120_000, maxBuffer: 16 * 1024 * 1024 });
  if (fileSha256(binding.path) !== binding.sha256) throw new Error("Prepared source binding changed during verification");
  return JSON.parse(raw).result;
}

/** A missing or short prepared range is an error; never fall back to the whole recording. */
export function mapPreparedMedia(use: MediaUse, result: PreparedSourceResult): PreparedMediaMapping {
  const section = result.sections.find(row => row.sourceFile === use.sourceFile && row[use.kind]
    && rational(row[use.kind]!.sourceStart) <= use.start + 1e-9 && rational(row[use.kind]!.sourceEnd) >= use.end - 1e-9);
  const asset = section?.[use.kind];
  if (!asset) throw new Error(`Prepared sources do not cover ${use.id}: ${use.start}–${use.end}`);
  const local = use.start - rational(asset.sourceOrigin);
  if (local < 0) throw new Error("Prepared source offset is negative");
  return { ...use, preparedFile: asset.file, mediaStart: Number(local.toFixed(12)), sourceOrigin: asset.sourceOrigin };
}

/** Transform only executable source URLs/offsets; source cuts and word occurrences remain unchanged. */
export function preparedProjectMedia(input: NativeShortProjectInput, html: string, supplied?: PreparedSourceResult) {
  if (!input.preparedSources) return { html, assets: input.assets, report: undefined };
  const result = supplied ?? loadPreparedSources(input.preparedSources);
  for (const source of result.selection.sources) {
    if (!input.assets.some(row => row.file === source.file && row.path === source.path && row.sha256 === source.sha256)) {
      throw new Error("Prepared sources substituted original source identity");
    }
  }
  const mappings: PreparedMediaMapping[] = [];
  const executable = html.replace(/<(video|audio)\b[^>]*>/giu, (tag: string, kind: string) => {
    const mapping = mapPreparedMedia(mediaUse(tag, kind.toLowerCase() as "video" | "audio"), result);
    mappings.push(mapping);
    return tag.replace(/\ssrc="[^"]*"/u, ` src="${mapping.preparedFile}"`)
      .replace(/\sdata-media-start="[^"]*"/u, ` data-media-start="${mapping.mediaStart}"`);
  });
  const used = new Set(mappings.map(row => row.preparedFile));
  const derived = result.sections.flatMap(row => [row.video, row.audio]).filter((row): row is PreparedAsset => !!row && used.has(row.file));
  const retained = input.assets.filter(row => !["source", "supporting-video"].includes(row.role));
  const assets = [...retained, ...new Map(derived.map(row => [row.file, row])).values()];
  if (new Set(assets.map(row => row.file)).size !== assets.length) throw new Error("Prepared source asset aliases collide");
  return { html: executable, assets, report: { schemaVersion: 1, package: input.preparedSources,
    editorialClock: "original-source", executableClock: "prepared-media", mappings } };
}
