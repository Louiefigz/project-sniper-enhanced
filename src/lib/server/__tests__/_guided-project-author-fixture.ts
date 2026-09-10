/** TEST metadata/stub transport only: these bytes are not admitted source or ASR proof. */
import assert from "node:assert/strict";
import path from "node:path";
import { readFileSync, writeFileSync } from "node:fs";
import type { TestContext } from "node:test";
import { authorGuidedProjectCut } from "../guided-project-bootstrap";
import { parseAuthorCutRequest } from "../guided-project-bootstrap-contract";
import { autoEditJobPath, parseAutoEditJobRecord } from "../auto-edit-job-persistence";
import { readCutPreviewObject, observeCutPreviewFile } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { bootstrapFixture } from "./_guided-project-bootstrap-fixture";

export function authorFixture(t: TestContext) {
  const base = bootstrapFixture(t), transcript = path.join(base.root, "TEST.transcript.json");
  writeFileSync(transcript, JSON.stringify({ transcript: [{ start: 0, end: 1,
    text: "TEST authored speech, not ASR.", words: [{ word: "TEST", start: 0, end: 1 }] }] }));
  writeFileSync(base.manifest, JSON.stringify({ sources: [{ id: "TEST-source", transcriptPath: path.basename(transcript) }],
    sourceSetAdmission: { schemaVersion: 1, testOnly: true } }));
  const request = parseAuthorCutRequest({ schemaVersion: 1, operation: "author-cut", idempotencyKey: base.request.idempotencyKey,
    manifest: { path: base.manifest, sha256: observeCutPreviewFile(base.manifest, 131072).sha256 },
    intent: { ...base.request.intent, brief: "Keep the complete thought for beginners; café 😀.\nDo not imply approval." },
    output: { width: 1920, height: 1080, fps: 23.976 } });
  const originals = [base.manifest, transcript, base.candidate].map(file => ({ file, bytes: readFileSync(file) }));
  const start = async (receivedAt?: string) => {
    const result = await authorGuidedProjectCut(request, receivedAt);
    const dir = result.producerDir, job = parseAutoEditJobRecord(readCutPreviewObject(autoEditJobPath(dir)).value);
    return { result, dir, job };
  };
  return { ...base, request, transcript, originals, start };
}

export function assertOriginalBytes(rows: Array<{ file: string; bytes: Buffer }>): void {
  for (const row of rows) assert.deepEqual(readFileSync(row.file), row.bytes);
}

export function replaceManifestSource(f: ReturnType<typeof authorFixture>, source: unknown) {
  const original = readCutPreviewObject(f.manifest).value;
  writeFileSync(f.manifest, JSON.stringify({ ...original, sources: [source] }));
  return { ...f.request, manifest: { path: f.manifest, sha256: observeCutPreviewFile(f.manifest, 131072).sha256 } };
}

/** A production parser is mandatory even for isolated TEST requests. */
export function shortAuthorRequest(f: ReturnType<typeof authorFixture>) {
  return parseAuthorCutRequest({ ...f.request,
    intent: { mode: "short", scope: "light", lanes: { captions: "auto", graphics: "off", motion: "off" }, brief: f.request.intent.brief },
    output: { width: 1080, height: 1920, fps: 30 } });
}

export function refreshRequestManifest(f: ReturnType<typeof authorFixture>) {
  return { ...f.request, manifest: { path: f.manifest,
    sha256: observeCutPreviewFile(f.manifest, 131072).sha256 } };
}
