import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync,
  writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { canonicalJson, fileSha256 } from "../../server/auto-edit-hash";
import { materializeVisualPlanContext } from
  "../../../../scripts/producer/visual-plan-context";
import { writeAdmittedMediaManifest } from "./_visual-plan-media-manifest-fixture";

function json(file: string, value: unknown): void {
  writeFileSync(file, `${JSON.stringify(value)}\n`);
}

function canonicalReceiptBytes(value: unknown): Buffer {
  const ascii = canonicalJson(value).replace(/[^\x00-\x7f]/g, character =>
    `\\u${character.charCodeAt(0).toString(16).padStart(4, "0")}`);
  return Buffer.from(`${ascii}\n`, "ascii");
}

function fixture(disposition?: "approved" | "needs-review" | "blocked" | "expired"):
  { root: string; producer: string; project: string;
    authorizationEvidence?: { path: string; sha256: string } } {
  const root = realpathSync(mkdtempSync(path.join(os.tmpdir(), "visual-plan-context-cli-")));
  const project = path.join(root, "workspace", "project");
  const producer = path.join(project, "producer"), source = path.join(project, "source");
  mkdirSync(producer, { recursive: true }); mkdirSync(source);
  json(path.join(project, "project.json"), { origin: "raw", history: [], intent: {
    mode: "short", scope: "produced", lanes: {}, brief: "Explain the retained point.",
  } });
  json(path.join(producer, "edit_plan.json"), {
    cutTrack: [{ sourceId: "source:one", start: 0, end: 1, speed: 1 }],
    cutDecisions: { schemaVersion: 1, removals: [] },
  });
  const mediaPath = path.join(source, "source.mp4");
  const brollPath = path.join(source, "support.png");
  const punctBrollPath = path.join(source, "_support.png");
  const unicodeBrollPath = path.join(source, "é-support.png");
  const externalPath = path.join(source, "authorized-custom-cutaway.mp4");
  writeFileSync(mediaPath, "TEST source metadata authority bytes");
  writeFileSync(brollPath, "TEST supplied B-roll metadata authority bytes");
  writeFileSync(punctBrollPath, "TEST punctuation B-roll metadata authority bytes");
  writeFileSync(unicodeBrollPath, "TEST unicode B-roll metadata authority bytes");
  writeFileSync(externalPath, "TEST admitted external custom B-roll bytes");
  let authorizationEvidence: { path: string; sha256: string } | undefined;
  if (disposition) {
    const originPath = path.join(project, "source/ASSET-ORIGIN.json");
    json(originPath, { schemaVersion: 1, kind: "native-short-asset-origin",
      assetFile: "assets/custom.mp4", record: { sha256: fileSha256(externalPath),
        publicationDisposition: disposition, rights: {
          allowedUses: ["editorial"], allowedPlatforms: ["local-review"] } },
      acquisition: { kind: disposition === "approved" ? "provided" : "public-web-capture",
        accessScope: disposition === "approved" ? "project-private" : "public", evidence: [] } });
    authorizationEvidence = { path: originPath, sha256: fileSha256(originPath)! };
  }
  writeAdmittedMediaManifest(path.join(source, "asset_manifest.json"), {
    sources: [{ id: "source:one", path: mediaPath,
      transcriptPath: "source.transcript.json" }],
    broll: [{ id: "support:Z", path: brollPath },
      { id: "support:_", path: punctBrollPath },
      { id: "support:a", path: unicodeBrollPath }],
    externalMedia: [{ id: "external:one", path: externalPath, authorizationEvidence }],
  });
  json(path.join(source, "source.transcript.json"), { transcript: [{
    start: 0, end: 1, text: "One useful idea", words: [
      { word: "One", start: 0, end: 0.2 }, { word: "useful", start: 0.25, end: 0.55 },
      { word: "idea", start: 0.6, end: 0.95 },
    ],
  }] });
  return { root, producer, project, authorizationEvidence };
}

function main(): void {
  const item = fixture();
  try {
    const context = materializeVisualPlanContext(item.producer);
    assert.equal(context.kind, "route-neutral-visual-plan-context");
    assert.equal(context.project.mode, "short");
    const transcript = JSON.parse(readFileSync(context.transcriptAuthority.path, "utf8"));
    assert.deepEqual(transcript.words.map((word: { text: string }) => word.text),
      ["One", "useful", "idea"]);
    const media = JSON.parse(readFileSync(context.mediaAuthority.path, "utf8"));
    assert.deepEqual(media.inventory.map((row: { modality: string; recordId: string }) =>
      [row.modality, row.recordId]), [
      ["external-media", "external:one"],
      ["source-footage", "source:one"],
      ["supplied-broll", "support:Z"],
      ["supplied-broll", "support:_"],
      ["supplied-broll", "support:a"],
    ]);
    for (const row of media.inventory) {
      assert.match(row.path, /\.sniper-external-media\/[a-f0-9]{64}\.media$/);
      assert.match(row.sourceSetEvidence.path,
        /\.sniper-external-media\/receipts\/[a-f0-9]{64}\.json$/);
      assert.equal(row.sourceSetEvidence.sha256.length, 64);
    }
    assert.equal(media.sourceSetAdmission.entryCount, 5);
    const catalog = JSON.parse(readFileSync(
      path.join(item.producer, "CATALOG-AUTHORITY.json"), "utf8"));
    assert.equal(catalog.total, 372);
    assert.equal(context.relatedUsage.length, 0);

    json(path.join(item.project, "project.json"), { origin: "raw", history: [], intent: {
      mode: "short", scope: "light", lanes: {}, brief: "Keep this simple.",
    } });
    assert.throws(() => materializeVisualPlanContext(item.producer), /produced or full/);
  } finally {
    rmSync(item.root, { recursive: true, force: true });
  }
}

function adversarialReceiptChecks(): void {
  const missing = fixture();
  try {
    const manifestPath = path.join(missing.project, "source/asset_manifest.json");
    const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
    delete manifest.sourceSetAdmission;
    json(manifestPath, manifest);
    assert.throws(() => materializeVisualPlanContext(missing.producer),
      /source-set admission must be an object/);
  } finally { rmSync(missing.root, { recursive: true, force: true }); }

  const stale = fixture();
  try {
    const manifestPath = path.join(stale.project, "source/asset_manifest.json");
    const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
    const receiptPath = path.join(path.dirname(manifestPath),
      manifest.sourceSetAdmission.receiptPath);
    const receipt = JSON.parse(readFileSync(receiptPath, "utf8"));
    receipt.entries[0].originalPath += ".stale";
    const bytes = canonicalReceiptBytes(receipt);
    const sha256 = createHash("sha256").update(bytes).digest("hex");
    const forgedPath = path.join(path.dirname(receiptPath), `${sha256}.json`);
    writeFileSync(forgedPath, bytes);
    manifest.sourceSetAdmission.receiptPath = `.sniper-source-sets/${sha256}.json`;
    manifest.sourceSetAdmission.receiptSha256 = sha256;
    json(manifestPath, manifest);
    assert.throws(() => materializeVisualPlanContext(stale.producer),
      /digest or ordering is stale/);
  } finally { rmSync(stale.root, { recursive: true, force: true }); }

  const forged = fixture();
  try {
    const manifestPath = path.join(forged.project, "source/asset_manifest.json");
    const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
    manifest.externalMedia[0].sourceSha256 = "f".repeat(64);
    json(manifestPath, manifest);
    assert.throws(() => materializeVisualPlanContext(forged.producer),
      /absent from source-set receipt/);
  } finally { rmSync(forged.root, { recursive: true, force: true }); }

  const tampered = fixture();
  try {
    const manifestPath = path.join(tampered.project, "source/asset_manifest.json");
    const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
    const pin = manifest.sources[0];
    const receiptPath = path.join(path.dirname(manifestPath), pin.admissionReceiptPath);
    writeFileSync(receiptPath, `${readFileSync(receiptPath, "utf8")} `);
    assert.throws(() => materializeVisualPlanContext(tampered.producer),
      /media admission receipt hash differs/);
  } finally { rmSync(tampered.root, { recursive: true, force: true }); }

  const authorized = fixture("approved");
  try {
    const context = materializeVisualPlanContext(authorized.producer);
    const authority = JSON.parse(readFileSync(context.mediaAuthority.path, "utf8"));
    const row = authority.inventory.find(
      (item: { modality: string }) => item.modality === "external-media");
    assert.deepEqual(row.authorizationEvidence, authorized.authorizationEvidence);
  } finally { rmSync(authorized.root, { recursive: true, force: true }); }

  const reviewableWeb = fixture("needs-review");
  try {
    const context = materializeVisualPlanContext(reviewableWeb.producer);
    const authority = JSON.parse(readFileSync(context.mediaAuthority.path, "utf8"));
    const row = authority.inventory.find(
      (item: { modality: string }) => item.modality === "external-media");
    assert.deepEqual(row.authorizationEvidence, reviewableWeb.authorizationEvidence);
  } finally { rmSync(reviewableWeb.root, { recursive: true, force: true }); }

  for (const disposition of ["blocked", "expired"] as const) {
    const denied = fixture(disposition);
    try {
      assert.throws(() => materializeVisualPlanContext(denied.producer),
        /not eligible for local review/);
    } finally { rmSync(denied.root, { recursive: true, force: true }); }
  }

  const manifestOnly = fixture();
  try {
    const manifestPath = path.join(manifestOnly.project, "source/asset_manifest.json");
    const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
    const external = manifest.externalMedia[0];
    const originPath = path.join(manifestOnly.project, "source/POST-INGEST-ORIGIN.json");
    json(originPath, { schemaVersion: 1, kind: "native-short-asset-origin",
      assetFile: "assets/custom.mp4", record: { sha256: external.sourceSha256,
        publicationDisposition: "approved", rights: {
          allowedUses: ["editorial"], allowedPlatforms: ["local-review"] } },
      acquisition: { kind: "provided", accessScope: "project-private", evidence: [] } });
    external.authorizationEvidence = { path: originPath, sha256: fileSha256(originPath) };
    json(manifestPath, manifest);
    assert.throws(() => materializeVisualPlanContext(manifestOnly.producer),
      /manifest authorization differs from its source-set receipt/);
  } finally { rmSync(manifestOnly.root, { recursive: true, force: true }); }
}

main();
adversarialReceiptChecks();
console.log("visual-plan context CLI tests passed");
