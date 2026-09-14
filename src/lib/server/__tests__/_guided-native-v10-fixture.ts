/** Tiny local admission and speech fixtures; no decoding, provider or visual-quality claim. */
import { mkdtempSync, realpathSync, writeFileSync, rmSync, lstatSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { canonicalJson, fileSha256 } from "../auto-edit-hash";
import { buildNativeSupportingPolicy } from "../guided-native-supporting";
import type { ProposalEvidence } from "../guided-proposal-evidence";
import { parseTreatmentProposalV10 } from "@/lib/producer/contracts/treatment-proposal-v10";

export function nativeV10Fixture() {
  const directory = realpathSync(mkdtempSync(path.join(os.tmpdir(), "native-v10-")));
  const receiptPath = path.join(directory, "admission.json");
  writeFileSync(receiptPath, canonicalJson({ schemaVersion: 1, scope: "TEST source admission" }));
  const image = path.join(directory, "supplied.png"), video = path.join(directory, "supplied.mp4");
  writeFileSync(image, Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=", "base64"));
  writeFileSync(video, "TEST unsupported video bytes");
  const manifest = { broll: [image, video].map((file, index) => ({ id: index ? "supplied-video" : "supplied-image",
    path: file, sourceSha256: fileSha256(file)!, sourceSizeBytes: lstatSync(file).size, kind: index ? "video" : "image",
    originalPath: file, admissionReceiptPath: receiptPath, admissionReceiptSha256: fileSha256(receiptPath)!,
    resolution: [1, 1], duration: index ? 2 : null })) };
  const manifestPath = path.join(directory, "manifest.json");
  writeFileSync(manifestPath, canonicalJson(manifest));
  const target = { mode: "short", scope: "produced", width: 1080, height: 1920, music: false,
    lanes: { captions: "auto", graphics: "auto", motion: "auto", broll: "auto" } };
  const intent = { mode: "short", scope: "produced", lanes: {}, shortDirection: {
    selection: "auto", supportingVideo: "source-first", mediaPolicy: { placement: "auto", sources: "provided-only" } } };
  const authority = { manifestPath, manifest, intent, target };
  const evidence = { schemaVersion: 10, target, frameRate: "25/1", totalFrames: 50, timelineMapHash: "a".repeat(64),
    anchors: [0, 25, 50], cleanEnds: [50], graphicsAdvice: {}, nativeSupportingPolicy: buildNativeSupportingPolicy(authority),
    segments: [{ index: 0, sourceId: "test", startFrame: 0, endFrameExclusive: 50, text: "Test words." }],
    occurrences: [[0, 0, 0, 0, 25, "Test", 0], [1, 0, 1, 25, 50, "words.", 0]],
    nativeReferences: [{ id: "TEST-STYLE", images: [{ file: "references/TEST.jpg", sha256: "b".repeat(64) }] }],
  } as unknown as ProposalEvidence;
  const output = parseTreatmentProposalV10({ schemaVersion: 10, summary: "TEST supplied image planning",
    clauses: [{ start: 0, end: 4, quote: "Show", disposition: "supported", rationale: "TEST supplied image request", operationIndices: [0] }],
    beats: [{ startAnchor: 0, endAnchorExclusive: 2, purpose: "opening", summary: "TEST whole sentence", supportsBeatIndices: [] }],
    operations: [{ type: "native-scene", clauseIndex: 0, beatIndex: 0, scene: { id: "show-image", startAnchor: 0, endAnchorExclusive: 2,
      mechanism: "supporting-asset", view: "presenter-supporting", question: "What does this show?", object: "TEST supplied image",
      quote: "Test words.", occurrenceIds: [0, 1], referenceIds: ["TEST-STYLE"], referenceReason: "TEST preserves style-only reference distinction",
      requiredAssetIds: ["supplied-image"], before: [], steps: [], result: [], readingHoldFrames: 25, rationale: "TEST explicit image planning only" } }],
    openingEndAnchor: 2, continuityEndAnchor: 2, audioPolicy: "preserve-full-program", colorPolicy: "preserve" });
  return { directory, authority, image, video, receiptPath, evidence, output, rawIntent: "Show",
    plan: { target, cutTrack: [{ sourceId: "test", start: 0, end: 2, speed: 1 }] },
    cleanup: () => rmSync(directory, { recursive: true, force: true }) };
}
