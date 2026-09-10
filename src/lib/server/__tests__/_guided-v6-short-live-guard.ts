/** TEST-only fresh-factory boundary. Metadata binding never manufactures source or human authority. */
import assert from "node:assert/strict";
import { existsSync, realpathSync } from "node:fs";
import path from "node:path";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { assertBootstrapBytes, assertNoBootstrapFailure, readBootstrapIntake } from "../guided-project-bootstrap-store";
import { observeHumanCutJob } from "../human-cut-acceptance-store";
import type { createV6ShortBootstrapFixture } from "./_guided-v6-short-fixture";

type Fixture = Pick<Awaited<ReturnType<typeof createV6ShortBootstrapFixture>>,
  "workspace" | "sourceRoot" | "dir" | "root" | "request" | "original" | "saved">;
const MARKER = { synthetic: true, genuineHumanAcceptance: false, actualAsr: false, providerCalls: 0,
  launchTransport: "in-process TEST controller, not detached qualification" };
const INTENT = { mode: "short", scope: "light", lanes: { captions: "auto", motion: "off", graphics: "off" } };

function assertTopology(fixture: Fixture): void {
  const { workspace, sourceRoot, request, root, dir } = fixture;
  assert.equal(realpathSync(workspace), workspace); assert.match(path.basename(workspace), /^sniper-v6-short-[A-Za-z0-9]+$/u);
  assert.equal(sourceRoot, path.join(workspace, "TEST-source"));
  assert.equal(root, path.join(workspace, `guided-${request.idempotencyKey}`));
  assert.equal(dir, path.join(root, "producer")); assert.equal(realpathSync(dir), dir);
  assert.equal(request.candidate.path, path.join(sourceRoot, "TEST-previsual-plan.json"));
  assert.equal(request.manifest.path, path.join(sourceRoot, "source/asset_manifest.json"));
  assert.deepEqual(request.intent, INTENT);
}

function assertOriginal(fixture: Fixture): void {
  const { original, saved, request, sourceRoot } = fixture;
  assert.equal(original.sha256, request.candidate.sha256);
  assert.deepEqual(Object.keys(original.value).sort(), ["cutDecisions", "cutTrack", "planVersion", "target"]);
  assert.deepEqual(original.value.target, { ...INTENT, width: 1080, height: 1920, fps: 30 });
  assert.deepEqual(original.value.cutTrack, [{ sourceId: "raw-1", start: 0, end: 16, speed: 1,
    rationale: "TEST ONLY retain the complete synthetic program." }]);
  assert.deepEqual(original.value.cutDecisions, { schemaVersion: 1, removals: [] });
  assert.equal(original.value.planVersion, 1);
  assert.deepEqual(saved.value, { ...original.value, planVersion: 2 });
  const documents = readCutPreviewObject(path.join(sourceRoot, "TEST-initial-documents.json")).value;
  assert.equal(documents.scope, "TEST-only-synthetic-text-not-ASR-or-human-approval");
  assert.deepEqual(documents.plan, original.value); assert.deepEqual(documents.intent, request.intent);
}

/** Capture only immediately after the actual new bootstrap factory, before any TEST cut decision. */
export function bindV6ShortSynthetic(fixture: Fixture): () => void {
  assertTopology(fixture); assertOriginal(fixture);
  const { dir, workspace, sourceRoot } = fixture, intake = readBootstrapIntake(dir);
  assert.deepEqual(intake.request, fixture.request);
  const markerPath = path.join(workspace, "TEST-ONLY.json");
  assert.deepEqual(readCutPreviewObject(markerPath).value, MARKER);
  const manifest = readCutPreviewObject(fixture.request.manifest.path);
  assert.equal(manifest.sha256, fixture.request.manifest.sha256);
  assert.ok(Array.isArray(manifest.value.sources)); assert.equal(manifest.value.sources.length, 1);
  assert.equal(manifest.value.sources[0].id, "raw-1");
  assert.equal(manifest.value.sources[0].transcriptPath, "raw.transcript.json");
  const files = [markerPath, path.join(sourceRoot, "TEST-initial-documents.json"),
    fixture.request.candidate.path, fixture.request.manifest.path, path.join(dir, "edit_plan.json"),
    path.join(sourceRoot, "source/raw.transcript.json")].map((file) => ({ file, sha256: readCutPreviewObject(file).sha256 }));
  assert.equal(files[2].sha256, fixture.original.sha256); assert.equal(files[4].sha256, fixture.saved.sha256);
  const guard = () => {
    assert.equal(realpathSync(dir), dir); assert.equal(realpathSync(workspace), workspace);
    assert.equal(readBootstrapIntake(dir).sha256, intake.sha256);
    assertNoBootstrapFailure(dir); assertBootstrapBytes(observeHumanCutJob(dir).job);
    for (const row of files) assert.equal(readCutPreviewObject(row.file).sha256, row.sha256, `TEST original bytes changed: ${row.file}`);
    for (const name of ["final.mp4", ".sniper-qc-approved.json"]) assert.equal(existsSync(path.join(dir, name)), false);
  };
  guard(); return guard;
}
