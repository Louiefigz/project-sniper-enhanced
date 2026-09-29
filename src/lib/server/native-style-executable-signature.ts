/** Exact composition signatures derived from mounted bytes and executable HTML. */
import { canonicalJsonSha256 } from "./auto-edit-hash";
import type { NativeCatalogFile } from "./native-catalog-files";

export interface StyleSignatureChoice {
  choiceId: string;
  sceneIndex: number;
  catalogFiles: string[];
  visibleIds: string[];
}

function tagsFor(html: string, ids: string[]): string[] {
  const wanted = new Set(ids);
  return (html.match(/<[^>]{1,8192}>/gu) ?? []).filter(tag => {
    const match = tag.match(/\bid="([^"]{1,256})"/u);
    return match ? wanted.has(match[1]) : false;
  }).sort();
}

function executableShape(tag: string) {
  const name = tag.match(/^<\s*([A-Za-z][A-Za-z0-9-]*)/u)?.[1]?.toLowerCase();
  if (!name) throw new Error("Style signature contains an invalid element tag");
  const ignored = new Set(["id", "data-start", "data-duration", "data-composition-src"]);
  const attributes = [...tag.matchAll(/\s+([A-Za-z_:][A-Za-z0-9_.:-]*)="([^"]*)"/gu)]
    .filter(match => !ignored.has(match[1].toLowerCase()))
    .map(match => [match[1].toLowerCase(), match[2]] as const)
    .sort(([left], [right]) => left.localeCompare(right));
  return { name, attributes };
}

/** Hash the exact staged components and mounted element tags for one choice. */
export function nativeStyleExecutableSignature(choice: StyleSignatureChoice,
  catalogFiles: NativeCatalogFile[], html: string): string {
  const files = new Set(choice.catalogFiles);
  const bindings = catalogFiles.filter(row => files.has(row.file)).map(row => ({
    sha256: row.sha256, catalogId: row.catalogId,
    sourceSha256: row.sourceSha256,
  })).sort((left, right) => canonicalJsonSha256(left).localeCompare(canonicalJsonSha256(right)));
  if (bindings.length !== files.size) throw new Error("Style signature has an unbound catalog file");
  const tags = tagsFor(html, choice.visibleIds);
  if (!tags.length || choice.visibleIds.some(id => !tags.some(tag => tag.includes(`id="${id}"`)))) {
    throw new Error("Style signature has no exact executable visual element");
  }
  return canonicalJsonSha256({ catalogBindings: bindings,
    elementShapes: tags.map(executableShape) });
}

/** Derive every choice signature without accepting prose as execution evidence. */
export function nativeStyleExecutableSignatures(choices: StyleSignatureChoice[],
  catalogFiles: NativeCatalogFile[], html: string): Record<string, string> {
  return Object.fromEntries(choices.map(choice => [choice.choiceId,
    nativeStyleExecutableSignature(choice, catalogFiles, html)]));
}
