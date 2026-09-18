/** Complete curated reference inventory; saved matches remain research evidence. */
import path from "node:path";
import { observeCutPreviewFile } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { canonicalJson } from "./auto-edit-hash";
import { objectValue, stringValue } from "@/lib/producer/contracts/validation";

export interface StrategyFilePin { path: string; sha256: string; sizeBytes: number }
export interface StrategyReferenceRow {
  id: string; title: string; version: unknown; detailFile: string;
  beatCount: number; sourceAspect: "9:16" | "16:9" | "unknown";
  catalogMatches: Array<{ beatId: string; candidates: string[] }>;
  adaptationStatus: "research-not-qualified-for-target";
}
export interface StrategyLibrary {
  schemaVersion: 1; scope: "reference-research-not-production-assets";
  complete: true; total: number; references: StrategyReferenceRow[];
}

/** Reuse the shared bounded, no-follow evidence reader. */
export function strategyFile(file: string): { pin: StrategyFilePin; text: string } {
  const observed = observeCutPreviewFile(file, 16 * 1024 * 1024, true);
  return { pin: { path: file, sha256: observed.sha256, sizeBytes: observed.sizeBytes },
    text: new TextDecoder("utf-8", { fatal: true }).decode(observed.bytes) };
}

function records(value: unknown, label: string): Record<string, unknown>[] {
  if (!Array.isArray(value)) throw new Error(`${label} must be an array`);
  return value.map(row => objectValue(row, label));
}

function ids(value: unknown): string[] {
  if (value === undefined) return [];
  if (!Array.isArray(value)) throw new Error("Reference catalog candidates must be an array");
  return value.map(id => stringValue(id, "catalog candidate", 128));
}

function matches(record: Record<string, unknown>): StrategyReferenceRow["catalogMatches"] {
  const id = stringValue(record.id, "reference id", 128);
  const top = Array.isArray(record.catalog_sources)
    ? record.catalog_sources.map(row => stringValue(objectValue(row, "catalog source").id, "catalog id", 128))
    : ids(record.catalog);
  const beats = record.beats === undefined ? [] : records(record.beats, "reference beats");
  return [{ beatId: id, candidates: top }, ...beats.map(beat => ({
    beatId: stringValue(beat.id, "beat id", 128), candidates: ids(beat.catalog_candidates),
  }))].filter(row => row.candidates.length > 0);
}

function addReference(record: Record<string, unknown>, state: {
  references: StrategyReferenceRow[]; files: Record<string, string>;
}, sourceAspect: StrategyReferenceRow["sourceAspect"] = "9:16") {
  const id = stringValue(record.id, "reference id", 128);
  if (!/^[A-Za-z][A-Za-z0-9_-]{0,127}$/u.test(id) || state.references.some(row => row.id === id)) {
    throw new Error("Curated reference identity is unsafe or duplicated");
  }
  const detailFile = `REFERENCE-${id}.json`;
  state.files[detailFile] = canonicalJson(record);
  state.references.push({ id, title: stringValue(record.title, "reference title", 2048),
    version: record.version ?? null, detailFile,
    beatCount: record.beats === undefined ? 1 : records(record.beats, "reference beats").length,
    sourceAspect, catalogMatches: matches(record),
    adaptationStatus: "research-not-qualified-for-target" });
}

function longformCases(repo: string, read: (file: string) => Record<string, unknown>) {
  const root = path.join(repo, "docs/studies/longform-visual-playbook");
  const manifest = read(path.join(root, "manifest.json"));
  return records(manifest.cases, "long-form cases").map(row => {
    const file = path.resolve(repo, stringValue(row.case_path, "reference case path", 2048));
    if (!file.startsWith(`${root}${path.sep}`)) throw new Error("Reference case escapes its library");
    const detail = read(file);
    if (detail.id !== row.id) throw new Error("Reference case identity differs from its manifest");
    return detail;
  });
}

/** Load complete Shorts and long-form collections with their saved catalog links. */
export function loadReferenceStrategyLibrary(repo: string) {
  const root = path.join(repo, "docs/studies/shorts-visual-playbook");
  const inputs: StrategyFilePin[] = [], state = { references: [] as StrategyReferenceRow[], files: {} as Record<string, string> };
  const read = (file: string) => {
    const held = strategyFile(file); inputs.push(held.pin);
    return objectValue(JSON.parse(held.text), "reference document");
  };
  const base = read(path.join(root, "manifest.json"));
  records(base.entries, "reference entries").forEach(row => addReference(row, state));
  const nate = read(path.join(root, "nate-sequences/manifest.json"));
  records(nate.cases, "Nate cases").forEach(row => addReference(row, state));
  const authentic = read(path.join(root, "authentic-expansion/manifest.json"));
  for (const row of records(authentic.cases, "authentic cases")) {
    const relative = stringValue(row.case_path, "reference case path", 2048);
    const file = path.resolve(repo, relative);
    if (!file.startsWith(`${root}${path.sep}`)) throw new Error("Reference case escapes its library");
    const detail = read(file);
    if (detail.id !== row.id) throw new Error("Reference case identity differs from its manifest");
    addReference(detail, state);
  }
  longformCases(repo, read).forEach(row => addReference(row, state, "16:9"));
  for (const relative of ["FORMAT_FOUNDATIONS.md", "nate-sequences/CATALOG_MAP.md", "authentic-expansion/CATALOG_MAP.md", "authentic-expansion/catalog-sources.json"]) {
    const held = strategyFile(path.join(root, relative)); inputs.push(held.pin);
    state.files[`REFERENCE-${relative.replaceAll("/", "-")}`] = held.text;
  }
  const index: StrategyLibrary = { schemaVersion: 1, scope: "reference-research-not-production-assets",
    complete: true, total: state.references.length, references: state.references };
  return { index, files: state.files, inputs, sourceRoot: repo };
}
