/** Explicit synthetic review records for contract/media tests; never creator approval. */
import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { prepareSavedPlanReview } from "@/app/api/producer/auto-edit/saved-plan-request";
import { NATIVE_PREBUILD_COVERAGE } from "../native-short-prebuild-review";
import { readinessPacket, type ReadinessPacket } from "../plan-readiness-packet";
import { writeRenderReadiness, PLAN_REVIEWS } from "../plan-readiness";
import { canonicalJsonSha256 as hash, fileSha256 } from "../auto-edit-hash";

interface ReviewFixture { root: string; preview: string; evidence: string; packet: ReadinessPacket }
function write(file: string, value: unknown) { writeFileSync(file, JSON.stringify(value)); }

/** Explicit synthetic admission for parser tests, never a live-decode claim. */
function testAdmission(preview: string) {
  const approved = JSON.parse(readFileSync("scripts/producer/headless/native_media_runtime_approval.json", "utf8"));
  const digest = "0".repeat(64), policy = approved.policy;
  const tools = Object.fromEntries(["ffmpeg", "ffprobe"].map(name => [name, { path: `/TEST/${name}`, sha256: digest, version: "TEST" }]));
  const runtime = { kind: "macos-seatbelt", policy, ...approved.approved[0], profileSha256: digest,
    closureSha256: digest, closureCount: 1, openedPathCount: 1, tools };
  const isolation = { kind: "macos-seatbelt", policy, profileSha256: digest, network: "denied",
    processCreation: "denied", writes: "/dev/null only", otherProcesses: "denied", memoryMiB: 768,
    watchdog: "footprint+cpu", jailRuns: ["/dev/null", "/TEST/ffprobe", "/TEST/ffmpeg"].map((decoder, index) => ({
      decoder, sandboxed: true, mode: index ? "exec" : "inspect", input: preview, profileSha256: digest,
      memoryMiB: 768, rlimits: { RLIMIT_FSIZE: [0, 0], RLIMIT_CORE: [0, 0] },
    })) };
  const sizeBytes = readFileSync(preview).length;
  return { schemaVersion: 1, policy: "sniper-external-media-probe-v4-native", runtime, isolation,
    limits: { max_bytes: 1024 ** 3, max_duration_seconds: 30, max_frames: 1800, max_decode_seconds: 90 },
    snapshot: { path: preview, sha256: fileSha256(preview), sizeBytes },
    decoded: { schemaVersion: 1, ok: true, decoded: true, facts: { mediaKind: "timed-media", durationSeconds: 1,
      sizeBytes, width: 320, height: 180, videoStreams: 1, audioStreams: 0, streamCount: 1, declaredFrames: 30 } } };
}


export function reviews(f: ReviewFixture, packet: ReadinessPacket = f.packet) {
  const units = Object.fromEntries(packet.units.map(unit => [unit.id, unit.hash]));
  const receipt = path.join(f.root, `preview-${packet.digest}.json`);
  const core = { schemaVersion: 1, kind: "producer-readiness-preview", units,
    media: { path: f.preview, sha256: fileSha256(f.preview), admission: testAdmission(f.preview) } };
  write(receipt, { ...core, digest: hash(core) });
  return Array.from({ length: packet.requiredReviews }, (_, index) => ({
    reviewer: { identity: `TEST reviewer ${index}`, sessionId: `critic-${index}`, plannerSessionId: "author", independent: true },
    coverage: Object.fromEntries(NATIVE_PREBUILD_COVERAGE.map(key => [key, "TEST assessment of current evidence"])),
    evidence: [{ path: f.evidence, sha256: fileSha256(f.evidence) }],
    review: { schemaVersion: 1, stage: "plan", verdict: "pass", summary: "TEST pass", materialIssues: [], findings: [] },
    units, previews: packet.units.map(unit => ({ unitId: unit.id, unitHash: unit.hash, path: f.preview,
      sha256: fileSha256(f.preview), receipt, assessment: "TEST moving preview assessment" })),
  }));
}


/** Supply explicitly fake editorial evidence to the real CLI in technical media tests. */
export function writeSyntheticReadiness(directory: string): void {
  const ctx = prepareSavedPlanReview(path.resolve(directory)).ctx;
  const root = path.dirname(ctx.dir), preview = path.join(root, "TEST-review-preview.mp4");
  const evidence = path.join(root, "TEST-review-evidence.json");
  writeFileSync(preview, "TEST contract preview; not playable media");
  write(evidence, { test: "Synthetic review fixture; no human/editorial approval" });
  const packet = readinessPacket(ctx);
  write(path.join(ctx.dir, PLAN_REVIEWS), { schemaVersion: 1, reviews: reviews({ root, preview, evidence, packet }) });
  writeRenderReadiness(ctx, { gates: { ok: true, errors: [] } });
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  writeSyntheticReadiness(process.argv[2]);
}
