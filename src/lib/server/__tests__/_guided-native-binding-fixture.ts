/** Structural compiler/writer fixture. The injected reader is not real guided acceptance. */
import { mkdirSync, readFileSync, writeFileSync, lstatSync } from "node:fs";
import path from "node:path";
import { canonicalJson, fileSha256 } from "../auto-edit-hash";
import { buildNativeTreatmentCandidate } from "../guided-native-candidate";
import { buildNativeSupportingPolicy } from "../guided-native-supporting";
import { prepareGuidedNativeShortRequest } from "../guided-native-authority";
import { buildGuidedNativeBinding, type GuidedNativeProposal } from "../guided-native-binding";
import { writeNativeAssetOrigin } from "../native-short-asset-origin";
import { parseShortDirection } from "@/lib/producer/short-direction";
import { nativeV10Fixture } from "./_guided-native-v10-fixture";
import { nativeShortFixture, refreshNativePacingFixture } from "./_native-short-project-fixture";

function sourceManifest(f: ReturnType<typeof nativeV10Fixture>, input: ReturnType<typeof nativeShortFixture>) {
  const transcript = path.join(f.directory, "transcript.json");
  writeFileSync(transcript, canonicalJson({ words: [] }));
  const admission = path.join(f.directory, ".sniper-source-sets"); mkdirSync(admission);
  const receipt = path.join(admission, `${fileSha256(f.receiptPath)}.json`);
  writeFileSync(receipt, readFileSync(f.receiptPath));
  const source = input.assets[0];
  return { ...f.authority.manifest, sources: [{ id: "test", path: source.path, sourceSha256: source.sha256,
    duration: 2, resolution: [1920, 1080], fps: 25, transcriptPath: transcript }], music: [],
  sourceSetAdmission: { schemaVersion: 1, receiptPath: path.relative(f.directory, receipt), receiptSha256: fileSha256(receipt),
    sourceSetDigest: "a".repeat(64), entryCount: 1 } };
}

function suppliedImage(f: ReturnType<typeof nativeV10Fixture>, input: ReturnType<typeof nativeShortFixture>): void {
  const asset = writeNativeAssetOrigin({ asset: { path: f.image, file: "assets/supplied.png", sha256: fileSha256(f.image)!, role: "image" },
    record: { schemaVersion: 1, assetId: "supplied-image", sha256: fileSha256(f.image)!, sizeBytes: lstatSync(f.image).size,
      mime: "image/png", origin: "operator-upload", acquiredAt: "2026-09-12T00:00:00Z",
      rights: { license: "TEST structural supplied fixture", allowedUses: ["editorial"], allowedPlatforms: ["local-review"],
        consent: "unknown", attributionRequired: false }, media: { width: 1, height: 1 },
      provenance: { source: f.image }, publicationDisposition: "needs-review" },
    acquisition: { kind: "provided", accessScope: "operator-private", evidence: [{ path: f.receiptPath, sha256: fileSha256(f.receiptPath)! }] } },
  path.join(f.directory, "image-origin.json"));
  input.assets.push(asset);
  input.extension = { css: "", motion: "", markup: '<img id="show-image" class="clip" src="assets/supplied.png" data-start="0" data-duration="2">' };
  input.strategy.scenes[0].visibleIds.push("show-image");
}

/** Real packet, compiler, source hashes, origins and assembly; only immutable lineage reconstruction is injected. */
export function guidedBindingFixture(version: 9 | 10 = 10) {
  const f = nativeV10Fixture(), input = nativeShortFixture(f.directory), producerDir = path.join(f.directory, "producer");
  mkdirSync(producerDir); input.request = parseShortDirection(f.authority.intent.shortDirection, "short")!;
  input.strategy.request = input.request; input.canvas.occurrences = f.evidence.occurrences;
  const manifest = sourceManifest(f, input); writeFileSync(f.authority.manifestPath, canonicalJson(manifest));
  f.evidence.nativeSupportingPolicy = buildNativeSupportingPolicy({ ...f.authority, manifest });
  const output = structuredClone(f.output) as unknown as Record<string, unknown>;
  if (version === 9) {
    output.schemaVersion = 9; f.evidence.schemaVersion = 9; delete f.evidence.nativeSupportingPolicy;
    Object.assign((output.operations as Array<{ scene: object }>)[0].scene,
      { mechanism: "presenter-hold", view: "presenter", requiredAssetIds: [] });
  } else suppliedImage(f, input);
  const result = buildNativeTreatmentCandidate({ ...f, output });
  if (!result.candidate || result.blockers.length) throw new Error(`TEST fixture did not compile: ${JSON.stringify(result.blockers)}`);
  const proposal = { result, evidence: f.evidence, proposalHash: "c".repeat(64),
    job: { ctx: { dir: producerDir, intent: f.authority.intent, manifestPath: f.authority.manifestPath,
      pipeline: { snapshotRoot: f.directory } } }, manifest: { value: manifest, sha256: fileSha256(f.authority.manifestPath)! } } as unknown as GuidedNativeProposal;
  const dependencies = { readGuidedProposal: () => proposal };
  const prepared = prepareGuidedNativeShortRequest(producerDir, { readProposal: dependencies.readGuidedProposal });
  const packetPath = path.join(prepared.directory, "SHORT-REQUEST.json");
  input.requestPacket = { path: packetPath, sha256: fileSha256(packetPath)! }; refreshNativePacingFixture(input);
  const mappings = version === 10 ? [{ sceneId: "show-image", assetId: "supplied-image", decisionId: "test-use-0" }] : [];
  const bind = () => { input.guidedBinding = buildGuidedNativeBinding(input, proposal, mappings); };
  return { ...f, input, proposal, producerDir, dependencies, prepared, mappings, bind };
}
