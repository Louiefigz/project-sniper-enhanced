/** Stored guided authority must win over a submitted visual plan and its packet. */
import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { assertGuidedNativeAuthority, type GuidedNativeAuthority } from "../guided-native-authority";
import { canonicalJson, fileSha256 } from "../auto-edit-hash";
import { prepareNativeShortRequest } from "../native-short-request";
import { writeNativeShortProject } from "../native-short-project";
import { nativeShortFixture, refreshNativePacingFixture } from "./_native-short-project-fixture";
import type { ProjectIntent } from "@/lib/producer/intent-presets";

function fixture(extra: Partial<ProjectIntent> = {}, externalManifest = false) {
  const directory = realpathSync(mkdtempSync(path.join(os.tmpdir(), "guided-native-authority-")));
  const root = path.join(directory, "project"), producerDir = path.join(root, "producer");
  const source = externalManifest ? path.join(directory, "admitted-media") : path.join(root, "source");
  mkdirSync(source, { recursive: true }); mkdirSync(producerDir, { recursive: true });
  const plan = nativeShortFixture(source), asset = plan.assets[0];
  const intent: ProjectIntent = { mode: "short", scope: "produced", lanes: {}, shortDirection: plan.request, ...extra };
  const receipt = path.join(source, "admission.json"), transcript = path.join(source, "transcript.json");
  writeFileSync(receipt, "TEST source admission"); writeFileSync(transcript, '{"words":[]}');
  const picture = path.join(source, "provided.png"); writeFileSync(picture, "TEST supplied picture");
  const manifest = { sources: [{ id: "test", path: asset.path, sourceSha256: asset.sha256,
    duration: 2, resolution: [1920, 1080], fps: 25, transcriptPath: "transcript.json" }],
    broll: [{ id: "supplied", path: "provided.png", sourceSha256: fileSha256(picture)! }], music: [],
    sourceSetAdmission: { schemaVersion: 1, receiptPath: "admission.json", receiptSha256: fileSha256(receipt)!,
      sourceSetDigest: "a".repeat(64), entryCount: 1 } };
  // Source-set intake requires content-addressed receipt names.
  const receiptPath = `.sniper-source-sets/${fileSha256(receipt)}.json`;
  mkdirSync(path.join(source, ".sniper-source-sets")); writeFileSync(path.join(source, receiptPath), readFileSync(receipt));
  manifest.sourceSetAdmission.receiptPath = receiptPath;
  const manifestPath = path.join(source, externalManifest ? "guided-sources.json" : "asset_manifest.json");
  writeFileSync(manifestPath, canonicalJson(manifest));
  const result = prepareNativeShortRequest({ producerDir, intent, repo: process.cwd(), ...(externalManifest ? { manifestPath } : {}) });
  const packetPath = path.join(result.directory, "SHORT-REQUEST.json");
  plan.requestPacket = { path: packetPath, sha256: fileSha256(packetPath)! }; refreshNativePacingFixture(plan);
  const authority: GuidedNativeAuthority = { intent, manifest: { path: manifestPath, sha256: fileSha256(manifestPath)!, value: manifest } };
  return { directory, plan, authority, packetPath, cleanup: () => rmSync(directory, { recursive: true, force: true }) };
}

function mutatePacket(f: ReturnType<typeof fixture>, change: (packet: Record<string, unknown>) => void): void {
  const packet = JSON.parse(readFileSync(f.packetPath, "utf8")); change(packet);
  writeFileSync(f.packetPath, canonicalJson(packet)); f.plan.requestPacket!.sha256 = fileSha256(f.packetPath)!;
}

test("unchanged prepared guided authority passes and the shared v3 writer remains supported", () => {
  const f = fixture();
  try {
    assert.doesNotThrow(() => assertGuidedNativeAuthority(f.plan, f.authority));
    const result = writeNativeShortProject(f.plan, path.join(f.directory, "assembled"));
    assert.equal(result.manifest.sourceVerified, true);
  } finally { f.cleanup(); }
});

test("omitting a packet cannot discard the guided intent", () => {
  const f = fixture();
  try {
    delete f.plan.requestPacket;
    assert.throws(() => assertGuidedNativeAuthority(f.plan, f.authority), /requires its prepared request packet/);
  } finally { f.cleanup(); }
});

test("changing provided-only to public-web in both plan and packet cannot broaden guided authority", () => {
  const direction = { selection: "auto", supportingVideo: "source-first", mediaPolicy: { placement: "auto", sources: "provided-only" } } as const;
  const f = fixture({ shortDirection: direction });
  try {
    f.plan.request = { ...direction, mediaPolicy: { placement: "auto", sources: "public-web" } };
    mutatePacket(f, packet => { (packet.intent as ProjectIntent).shortDirection = f.plan.request; });
    assert.throws(() => assertGuidedNativeAuthority(f.plan, f.authority), /authoritative guided intent/);
  } finally { f.cleanup(); }
});

test("a submitted plan cannot replace a legacy local-only style request", () => {
  const f = fixture({ shortDirection: undefined });
  try {
    assert.doesNotThrow(() => assertGuidedNativeAuthority(f.plan, f.authority));
    f.plan.request = { ...f.plan.request, mediaPolicy: { placement: "auto", sources: "public-web" } };
    assert.throws(() => assertGuidedNativeAuthority(f.plan, f.authority), /prepared style request|authoritative.*request|intent|direction/);
  } finally { f.cleanup(); }
});

test("operator-owned and disabled B-roll lanes reject a selected insertion before assembly", () => {
  for (const broll of ["operator", "off"] as const) {
    const f = fixture({ lanes: { broll } });
    try {
      f.plan.strategy.supportingSearch.candidates.push({ assetFile: f.plan.canvas.sourceFile, sourceStart: 0, sourceEnd: 1,
        observed: "TEST actual source window", role: "context", claimLimit: "TEST illustrative only", selected: true,
        reason: "TEST insert attempt", visibleId: "test-cutaway", startFrame: 0, endFrame: 25 });
      assert.throws(() => assertGuidedNativeAuthority(f.plan, f.authority), /broll lane ownership/);
    } finally { f.cleanup(); }
  }
});

test("packet cannot remove guided audio work or change a disabled lane to auto", () => {
  for (const extra of [{ music: true }, { lanes: { captions: "off" as const } }]) {
    const f = fixture(extra);
    try {
      mutatePacket(f, packet => { packet.intent = { mode: "short", scope: "produced", lanes: {}, shortDirection: f.plan.request }; });
      assert.throws(() => assertGuidedNativeAuthority(f.plan, f.authority), /authoritative guided intent/);
    } finally { f.cleanup(); }
  }
});

test("a matching packet preserves the guided audio requirement and disabled captions", () => {
  for (const extra of [{ music: true }, { lanes: { captions: "off" as const } }]) {
    const f = fixture(extra);
    try { assert.throws(() => assertGuidedNativeAuthority(f.plan, f.authority), /requested music|captions lane ownership/); }
    finally { f.cleanup(); }
  }
});

test("rehashing a substituted or incomplete supplied inventory does not make it authoritative", () => {
  for (const key of ["sources", "availableSupportingAssets"] as const) {
    const f = fixture();
    try {
      mutatePacket(f, packet => { (packet[key] as Array<Record<string, unknown>>)[0].sha256 = "b".repeat(64); });
      assert.throws(() => assertGuidedNativeAuthority(f.plan, f.authority), /substituted the guided supplied inventory/);
      mutatePacket(f, packet => { packet[key] = []; });
      assert.throws(() => assertGuidedNativeAuthority(f.plan, f.authority), /substituted the guided supplied inventory/);
    } finally { f.cleanup(); }
  }
});

test("another frozen manifest cannot substitute for the actual guided source manifest", () => {
  const f = fixture();
  try {
    mutatePacket(f, packet => { (packet.manifest as { sha256: string }).sha256 = "b".repeat(64); });
    assert.throws(() => assertGuidedNativeAuthority(f.plan, f.authority), /different guided manifest/);
  } finally { f.cleanup(); }
});

test("a guided bootstrap manifest outside the default source directory prepares and remains bound", () => {
  const f = fixture({}, true);
  try {
    const packet = JSON.parse(readFileSync(f.packetPath, "utf8"));
    assert.equal(packet.manifest.path, f.authority.manifest.path);
    assert.match(packet.manifest.path, /admitted-media\/guided-sources\.json$/);
    assert.doesNotThrow(() => assertGuidedNativeAuthority(f.plan, f.authority));
    assert.equal(writeNativeShortProject(f.plan, path.join(f.directory, "assembled")).manifest.sourceVerified, true);
    mutatePacket(f, value => { (value.manifest as { path: string }).path = path.join(f.directory, "different-manifest.json"); });
    assert.throws(() => assertGuidedNativeAuthority(f.plan, f.authority), /different guided manifest/);
  } finally { f.cleanup(); }
});

test("shared inventory observation rejects modified admitted source bytes", () => {
  const f = fixture();
  try {
    writeFileSync(f.plan.assets[0].path, "TEST altered source footage after preparation");
    assert.throws(() => assertGuidedNativeAuthority(f.plan, f.authority), /source changed since ingest/);
  } finally { f.cleanup(); }
});
