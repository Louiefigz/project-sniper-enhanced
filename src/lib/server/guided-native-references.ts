/** Selected, immutable visual evidence for the native proposal worker. Never production pixels. */
import path from "node:path";
import { writeFileSync } from "node:fs";
import { observeCutPreviewFile, readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { objectValue, stringValue, sha256 } from "@/lib/producer/contracts/validation";
import { createHumanCutIndex, humanCutDirectory } from "./human-cut-acceptance-store";
import { SEQUENCE_LIBRARY } from "./reference-library-paths";

export interface NativeReferenceSelection { caseId: string; beatId: string }
export interface NativeReference {
  id: string; caseId: string; caseVersion: unknown; caseHash: string;
  beat: Record<string, unknown>;
  images: Array<{ file: string; sha256: string; sizeBytes: number }>;
  scope: "research-reference-not-production-asset-or-qualified-template";
}
const LIBRARY = SEQUENCE_LIBRARY;
const INDEX = "native-references.json";
const SCOPE = "research-reference-not-production-asset-or-qualified-template" as const;

function selectedCase(selection: NativeReferenceSelection) {
  if (!/^SQ\d{2}$/u.test(selection.caseId) || !new RegExp(`^${selection.caseId}-B\\d{2}$`, "u").test(selection.beatId)) {
    throw new Error("Native reference selection must name an exact curated case and beat");
  }
  const observed = readCutPreviewObject(path.join(process.cwd(), LIBRARY, "cases", `${selection.caseId}.json`));
  const rows = observed.value.beats;
  const beat = Array.isArray(rows) ? rows.find((value) => objectValue(value, "reference beat").id === selection.beatId) : null;
  if (!beat) throw new Error("Selected native reference beat does not exist");
  return { observed, beat: objectValue(beat, "reference beat") };
}

function copyFrames(input: { directory: string; beat: Record<string, unknown>; index: number }) {
  const frames = input.beat.source_frames;
  if (!Array.isArray(frames) || !frames.length) throw new Error("Native reference needs individual source frames");
  // First, middle and final source frame show development; selected evidence stays bounded.
  const selected = [...new Set([0, Math.floor((frames.length - 1) / 2), frames.length - 1])];
  return selected.map((frameIndex, imageIndex) => {
    const frame = objectValue(frames[frameIndex], "reference frame"), relative = stringValue(frame.path, "reference image", 1024);
    const file = path.resolve(process.cwd(), relative), library = path.resolve(process.cwd(), LIBRARY, "frames");
    if (!file.startsWith(`${library}${path.sep}`) || !file.endsWith(".jpg")) throw new Error("Reference image escapes the curated frame library");
    const observed = observeCutPreviewFile(file, 3 * 1024 * 1024, true);
    if (frame.sha256 !== observed.sha256) throw new Error("Selected reference frame differs from its reviewed hash");
    const name = `${input.index}-${imageIndex}.jpg`;
    writeFileSync(path.join(input.directory, name), observed.bytes, { flag: "wx", mode: 0o600 });
    return { file: `native-references/${name}`, sha256: observed.sha256, sizeBytes: observed.sizeBytes };
  });
}

/** Snapshot only explicitly selected examples; no bulk library upload or provider-selected filesystem paths. */
export function stageNativeReferences(directory: string, selections: NativeReferenceSelection[]): NativeReference[] {
  if (!selections.length || selections.length > 4 || new Set(selections.map((row) => row.beatId)).size !== selections.length) {
    throw new Error("Native proposal requires one to four unique selected reference beats");
  }
  const images = humanCutDirectory(directory, "native-references");
  const references = selections.map((selection, index): NativeReference => {
    const { observed, beat } = selectedCase(selection);
    return { id: selection.beatId, caseId: selection.caseId, caseVersion: observed.value.version, caseHash: observed.sha256,
      beat, images: copyFrames({ directory: images, beat, index }), scope: SCOPE };
  });
  createHumanCutIndex(path.join(directory, INDEX), { schemaVersion: 1, references });
  return readNativeReferences(directory);
}

/** Cold read verifies every attached image; a prose-only reference can never replace the frozen visual evidence. */
export function readNativeReferences(directory: string): NativeReference[] {
  const index = readCutPreviewObject(path.join(directory, INDEX)).value;
  if (index.schemaVersion !== 1 || !Array.isArray(index.references) || !index.references.length || index.references.length > 4) {
    throw new Error("Native reference snapshot is missing or malformed");
  }
  let total = 0;
  const references = index.references.map((value, referenceIndex) => {
    const row = objectValue(value, "native reference") as unknown as NativeReference;
    sha256(row.caseHash, "case hash");
    if (row.scope !== SCOPE || !Array.isArray(row.images) || !row.images.length || row.images.length > 3
        || row.id !== row.beat.id) throw new Error("Native reference snapshot lost its identity or images");
    row.images.forEach((image, imageIndex) => {
      if (image.file !== `native-references/${referenceIndex}-${imageIndex}.jpg`) throw new Error("Native image path is not controller-owned");
      const observed = observeCutPreviewFile(path.join(directory, image.file), 3 * 1024 * 1024, true);
      total += observed.sizeBytes;
      if (observed.sha256 !== image.sha256 || observed.sizeBytes !== image.sizeBytes || total > 16 * 1024 * 1024) {
        throw new Error("Native reference image changed or attachment budget exceeded");
      }
    });
    return row;
  });
  if (new Set(references.map((row) => row.id)).size !== references.length) throw new Error("Duplicate native reference identities");
  return references;
}

export function nativeReferenceImages(execution: string, references: NativeReference[]): string[] {
  return references.flatMap((row) => row.images.map((image) => path.join(execution, "candidate-inputs", image.file)));
}
