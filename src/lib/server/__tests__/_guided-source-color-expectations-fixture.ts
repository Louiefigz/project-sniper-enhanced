/** TEST metadata only: observer/admission return shape is stubbed; no media bytes or jobs exist. */
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import type { TestContext } from "node:test";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { OPENING_DOCUMENT_NAMES } from "@/lib/producer/contracts/guided-opening-media-v1";
import { SOURCE_COLOR_V2_PROFILE, type GuidedSourceColorV1 } from "@/lib/producer/contracts/guided-source-color-v1";
import type { SourceColorExpectationContext } from "../guided-source-color-expectations";

type Json = Record<string, unknown>;
interface FixtureOptions {
  receipt?: (value: Json) => void; entry?: (value: Json) => void;
  manifest?: (value: Json) => void; plan?: (value: Json) => void;
}
export const testSha = (value: string | Buffer) => createHash("sha256").update(value).digest("hex");

/** New-only fixture publication retains literal whitespace/Unicode bytes, not receipt reserialization. */
function write(file: string, value: unknown) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const bytes = Buffer.from(`${JSON.stringify(value, null, 2)}\n`);
  fs.writeFileSync(file, bytes, { flag: "wx", mode: 0o600 });
  return { path: file, sha256: testSha(bytes) };
}

/** No snapshot file is created: opening admission and EOF observation are explicit TEST stubs. */
function source(producer: string, id: string, options: FixtureOptions) {
  const sourceSha = testSha(`TEST absent media ${id}`), size = 1024, count = id === "raw-b" ? 48 : 24;
  const snapshot = { path: path.join(producer, ".sniper-external-media", `${sourceSha}.media`), sha256: sourceSha, sizeBytes: size };
  const facts = { mediaKind: "timed-media", durationSeconds: count / 24, sizeBytes: size, width: 1920, height: 1080,
    videoStreams: 1, audioStreams: 1, streamCount: 2, declaredFrames: count };
  const receipt: Json = { schemaVersion: 1, policy: "sniper-external-media-probe-v2", snapshot,
    limits: {}, image: {}, isolation: {}, network: {}, decoded: { schemaVersion: 1, ok: true, decoded: true, facts } };
  if (id === "raw-b") options.receipt?.(receipt);
  const receiptSha = testSha(`${JSON.stringify(receipt, null, 2)}\n`);
  const admissionReceiptPath = `.sniper-external-media/receipts/${receiptSha}.json`;
  write(path.join(producer, admissionReceiptPath), receipt);
  const entry: Json = { lane: "source", originalPath: path.join(producer, `${id}-TEST-ingress-撮影.mp4`), snapshotPath: snapshot.path,
    sha256: sourceSha, sizeBytes: size, mediaKind: "timed-media", admissionReceiptPath, admissionReceiptSha256: receiptSha };
  if (id === "raw-b") options.entry?.(entry);
  const row = { id, originalPath: entry.originalPath, path: snapshot.path, sourceSha256: sourceSha, sourceSizeBytes: size,
    vfr: false, frameRate: "24/1", admissionReceiptPath, admissionReceiptSha256: receiptSha };
  return { row, entry };
}

/** Exact explicit operator declarations; unknown V2 history is not filled from a guessed camera. */
function selection(): GuidedSourceColorV1 {
  return { schemaVersion: 1, declarations: Object.fromEntries(["raw-a", "raw-b"].map(id => {
    const v2 = id === "raw-b";
    return [id, { profile: v2 ? SOURCE_COLOR_V2_PROFILE : null, declaration: {
      schemaVersion: v2 ? 2 : 1, sourceId: id, sourceProfile: v2 ? "unknown" : "bt709-sdr",
      cameraProfile: null, historyState: v2 ? "unknown" : "known", transformHistory: [],
      lightingGroups: [{ id: "whole", startFrame: 0, endFrame: v2 ? 48 : 24, intent: "unknown", description: "TEST 手動 declaration" }],
    } }];
  })) } as GuidedSourceColorV1;
}

/** Build raw original metadata before any projector callback; this is not a real admission qualification. */
function originalDocuments(producer: string, options: FixtureOptions) {
  const rows = ["raw-a", "raw-b"].map(id => source(producer, id, options));
  const set = { schemaVersion: 1, policy: "sniper-producer-source-set-v1", entries: rows.map(row => row.entry),
    sourceSetDigest: testSha("TEST held source-set semantic digest; no full admission validator") };
  const setSha = testSha(`${JSON.stringify(set, null, 2)}\n`), receiptPath = `.sniper-source-sets/${setSha}.json`;
  write(path.join(producer, receiptPath), set);
  const manifest: Json = { sources: rows.map(row => row.row), broll: [], music: [], sourceSetAdmission: {
    schemaVersion: 1, receiptPath, receiptSha256: setSha, sourceSetDigest: set.sourceSetDigest, entryCount: rows.length,
  } };
  const plan: Json = { planVersion: 1, target: { mode: "longform" }, cutTrack: ["raw-b", "raw-a", "raw-b"].map(sourceId =>
    ({ sourceId, start: 0, end: 1 })), cutDecisions: { schemaVersion: 1, removals: [] } };
  options.manifest?.(manifest); options.plan?.(plan);
  write(path.join(producer, "edit_plan.json"), plan); write(path.join(producer, "asset_manifest.json"), manifest);
  write(path.join(path.dirname(producer), "project.json"), { history: [], TEST: "No real camera/history authority" });
  const authority = { sourceSetDigest: set.sourceSetDigest };
  return { plan, manifest, authority, setPath: path.join(producer, receiptPath) };
}

/** All fourteen input refs are real tiny JSON files; full observer semantics are explicitly stubbed. */
export function sourceColorFixture(t: TestContext, options: FixtureOptions = {}) {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "source-color-expectations-")));
  t.after(() => {
    assert.equal(fs.realpathSync(root), root); assert.equal(path.dirname(root), fs.realpathSync(os.tmpdir()));
    fs.rmSync(root, { recursive: true, force: true });
  });
  const producerDir = path.join(root, "producer"); fs.mkdirSync(producerDir);
  const original = originalDocuments(producerDir, options), docsRoot = path.join(producerDir, "TEST-opening");
  const values: Record<string, Json> = { authority: original.authority, acceptedPlan: original.plan,
    candidatePlan: structuredClone(original.plan), manifest: original.manifest };
  const refs = Object.fromEntries(OPENING_DOCUMENT_NAMES.map(name => [name,
    write(path.join(docsRoot, `${name}.json`), values[name] ?? { TEST: `Inert ${name} observer return` })]));
  const input = { schemaVersion: 1, kind: "guided-opening-media-input", executionId: "f612f0c0-bd72-4adf-96b9-50fbb55ef777",
    executionInputHash: testSha("TEST opening input semantic hash"), profile: "unity-source-float-own-screen-v1", documents: refs,
    pipeline: { snapshotRoot: root, lockPath: path.join(root, "TEST-lock.json"), lockSha256: testSha("TEST-lock"), digest: testSha("TEST-pipeline") } };
  const inputRef = write(path.join(docsRoot, "input.json"), input);
  const documents = Object.fromEntries(Object.entries(refs).map(([name, ref]) => [name, readCutPreviewObject(ref.path)]));
  const opening = { input, authority: original.authority, documents, inputSha256: inputRef.sha256,
    observationScope: "bound-input-documents-only", sourceBytesObserved: false, currentJournalObserved: false, pipelineFilesObserved: false };
  let calls = 0, action = () => undefined as void;
  const context: SourceColorExpectationContext = { opening: opening as SourceColorExpectationContext["opening"],
    inputPath: inputRef.path, producerDir, selection: selection(), guard: () => { calls++; action(); } };
  return { root, context, refs, setPath: original.setPath, calls: () => calls,
    onGuard: (value: () => void) => { action = value; } };
}

/** Fault writes may touch only exact real, nonaliased, single-link TEST-owned files. */
export function mutateOwned(fixture: ReturnType<typeof sourceColorFixture>, file: string, bytes: string): void {
  assert.equal(fs.realpathSync(file), file); assert(file.startsWith(`${fixture.root}${path.sep}`));
  const info = fs.lstatSync(file); assert(info.isFile()); assert.equal(info.nlink, 1);
  fs.writeFileSync(file, bytes);
}
