/** Read the Director's canonical libraries; retain their exact bytes instead of forking a catalog. */
import path from "node:path";
import { createHash } from "node:crypto";
import { observeCutPreviewFile } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { canonicalJsonSha256 } from "./auto-edit-hash";

/** The packaged, original Director library (see resources/director/README.md). */
const FILES = {
  formats: "formats.md",
  hooks: "hook-anchors.md",
  formulas: "hook-formulas.md",
  references: "hook-references.md",
  problemTraining: "hook-training-problem-aware.md",
  solutionTraining: "hook-training-solution-aware.md",
} as const;
/** Packaged library location, relative to the application root. */
export const PACKAGED_DIRECTOR_LIBRARY = path.join("resources", "director");
export interface DirectorSource { name: string; sha256: string; content: string }
export interface DirectorExample { id: string; content: string; formula: string; slots: string[]; disqualifyIf: string }
export interface DirectorCatalog {
  schemaVersion: 1; sources: DirectorSource[];
  formats: Array<{ id: string; content: string }>;
  anchors: Array<{ id: string; category: string; template: string; sources: string }>;
  examples: DirectorExample[];
}

function sections(text: string, pattern: RegExp) {
  const matches = [...text.matchAll(pattern)];
  return matches.map((match, index) => ({ id: match[1],
    content: text.slice(match.index! + match[0].length, matches[index + 1]?.index ?? text.length).trim() }));
}

export function templateSlots(template: string): string[] {
  return [...new Set([...template.matchAll(/\[([^\]\n]+)\]/gu)].map((match) => match[1]))];
}

function examples(sources: Record<keyof typeof FILES, string>): DirectorExample[] {
  const index = new Map(sections(sources.formulas, /^### ([RT]\d{3}) · [^\n]+\n/gmu).map((row) => [row.id, row.content]));
  const references = [...sources.references.matchAll(/^- \*\*([RT]\d{3}) · ([^\n]+)$/gmu)]
    .map((row) => ({ id: row[1], content: row[2] }));
  const training = [sources.problemTraining, sources.solutionTraining]
    .flatMap((text) => sections(text, /^### (T\d{3})\s*\n/gmu));
  const rows = [...references, ...training].map((row) => {
    const entry = index.get(row.id) ?? "";
    const formula = /^- formula: (.+)$/mu.exec(entry)?.[1] ?? "";
    return { ...row, formula, slots: templateSlots(formula),
      disqualifyIf: /^- disqualify-if: (.+)$/mu.exec(entry)?.[1] ?? "Use the named hook anchor's slots; this training example is not a claim source." };
  });
  if (!rows.length || new Set(rows.map((row) => row.id)).size !== rows.length) throw new Error("Director example IDs are empty or duplicated");
  for (const id of index.keys()) if (!rows.some((row) => row.id === id)) throw new Error(`Director formula has no source entry: ${id}`);
  return rows;
}

/** The stored source bytes are also the cold-read authority. Parsing never reaches a database/provider. */
export function catalogFromSources(rows: DirectorSource[]): DirectorCatalog {
  if (rows.length !== Object.keys(FILES).length) throw new Error("Director library source set is incomplete");
  const texts = {} as Record<keyof typeof FILES, string>;
  for (const [key, name] of Object.entries(FILES)) {
    const matching = rows.filter((row) => row.name === name), row = matching[0];
    if (matching.length !== 1 || typeof row.content !== "string" || Buffer.byteLength(row.content) > 256 * 1024) throw new Error("Invalid Director library source");
    // File hashes use raw UTF-8, not the JSON encoding of that string.
    if (textHash(row.content) !== row.sha256) throw new Error(`Director source bytes changed: ${name}`);
    texts[key as keyof typeof FILES] = row.content;
  }
  const formats = sections(texts.formats, /^## ([a-z_]+) — [^\n]+\n/gmu);
  const anchors: DirectorCatalog["anchors"] = [];
  let category = "";
  for (const line of texts.hooks.split("\n")) {
    const heading = /^### \d+\. ([A-Z -]+) — /u.exec(line);
    if (heading) category = heading[1].trim();
    const row = /^\| `([a-z][a-z0-9-]+)` \| (.+?) \| (.+) \|$/u.exec(line);
    if (row) anchors.push({ id: row[1], category, template: row[2], sources: row[3] });
  }
  if (!formats.length || !anchors.length || anchors.some((row) => !row.category)
      || new Set(anchors.map((row) => row.id)).size !== anchors.length) throw new Error("Director format/anchor library is malformed");
  return { schemaVersion: 1, sources: rows, formats, anchors, examples: examples(texts) };
}

function textHash(value: string): string { return createHash("sha256").update(value).digest("hex"); }

/**
 * The Director reads only the library packaged with the application, or an operator
 * configured SNIPER_DIRECTOR_LIBRARY with the same six files. There is no fallback to
 * any other repository, and model output can never choose a library path.
 */
export function directorLibraryRoot(env: NodeJS.ProcessEnv = process.env): string {
  const configured = env.SNIPER_DIRECTOR_LIBRARY?.trim();
  if (configured) {
    if (!path.isAbsolute(configured)) throw new Error("SNIPER_DIRECTOR_LIBRARY must be absolute");
    return configured;
  }
  return path.resolve(process.cwd(), PACKAGED_DIRECTOR_LIBRARY);
}

export function loadDirectorCatalog(root = directorLibraryRoot()): DirectorCatalog {
  if (!path.isAbsolute(root)) throw new Error("Director library path must be absolute");
  const sources = Object.values(FILES).map((name) => {
    const observed = observeCutPreviewFile(path.join(root, name), 256 * 1024, true);
    return { name, sha256: observed.sha256, content: new TextDecoder("utf-8", { fatal: true }).decode(observed.bytes) };
  });
  return catalogFromSources(sources);
}

export function directorCatalogHash(catalog: DirectorCatalog): string {
  return canonicalJsonSha256(catalog.sources.map(({ name, sha256 }) => ({ name, sha256 })));
}
