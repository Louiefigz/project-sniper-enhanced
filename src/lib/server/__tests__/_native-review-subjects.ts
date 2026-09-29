/** TEST plan and checked-export subjects with role packets and complete TEST observation drafts. Nobody judged,
 * watched or heard anything. */
import path from "node:path";
import type { TestContext } from "node:test";
import { fileSha256 } from "../auto-edit-hash";
import { submitNativeFinalReview } from "../native-final-review-submission";
import { submitNativePrebuildReview } from "../native-prebuild-review-submission";
import { nativeShortPrebuildPlanHash } from "../native-short-prebuild-review";
import { nativeShortFixture } from "./_native-short-project-fixture";
import { coverage, inspected, reviewer, rolePacket, testRoot, writeJson, writeText } from "./_native-review-fixture";

export function planSetup(t: TestContext) {
  const root = testRoot(t, "TEST-prebuild-submit-"), input = nativeShortFixture(root);
  delete input.prebuildReview;
  const planFile = writeJson(path.join(root, "clip", "native-plan-v1.json"), input), planHash = nativeShortPrebuildPlanHash(input);
  const scenes = input.strategy.scenes.map((scene, index) => ({ index, startFrame: scene.startFrame, endFrame: scene.endFrame }));
  const packet = rolePacket(root, "plan-critic", { plan: { path: planFile, sha256: fileSha256(planFile)!, planHash },
    frameRate: input.canvas.frameRate, totalFrames: input.canvas.totalFrames, scenes }, [planFile]);
  const records = path.dirname(packet.path), observations = path.join(records, "PREBUILD-REVIEW-v1-OBSERVATIONS.json");
  const draft = () => ({ schemaVersion: 2, kind: "native-plan-review-observations", rolePacketSha256: packet.sha256,
    reviewer: reviewer(), coverage: coverage(), verdict: "pass", summary: "TEST structural submission; no plan was judged.",
    materialIssues: [] as unknown[], findings: [] as unknown[], limitations: [] as string[], evidence: [] as unknown[],
    inspection: [] as unknown[], approves: [] as string[],
    scenes: scenes.map(scene => ({ ...scene, note: "TEST synthetic scene note" })) });
  const output = path.join(records, "PREBUILD-REVIEW-v1.json");
  return { root, input, planFile, planHash, packet, records, observations, output, draft,
    write: (value: unknown) => writeJson(observations, value),
    submit: () => submitNativePrebuildReview({ packet: packet.path, observations, output }) };
}

export function finalSetup(t: TestContext) {
  const root = testRoot(t, "TEST-final-submit-"), project = path.join(root, "clip", "native-v1");
  const plan = { schemaVersion: 1, canvas: { frameRate: "30/1", totalFrames: 300 }, strategy: { scenes: [] }, assets: [] };
  writeJson(path.join(project, "SHORT-PROJECT.json"), plan);
  const exportDir = path.join(root, "clip", "final-v1"), video = writeText(path.join(exportDir, "review.mp4"), "TEST synthetic mp4 bytes");
  const delivery = writeJson(path.join(exportDir, "delivery.json"), { status: "native-short-checked-for-review", output: video,
    sha256: fileSha256(video), humanApproved: false });
  writeJson(path.join(exportDir, "export-request.json"), { project });
  const events = [0, 144, 299].map(frame => ({ frame, seconds: frame / 30, labels: ["TEST event"], coveredByPreview: frame === 0 }));
  const subject = { export: { directory: exportDir, delivery: { path: delivery, sha256: fileSha256(delivery)! },
    video: { path: video, sha256: fileSha256(video)!, links: 1 } }, frameRate: "30/1", totalFrames: 300, events };
  const packet = rolePacket(root, "final-critic", subject, [delivery, [video, "linked-media"]]);
  const records = path.dirname(packet.path), observations = path.join(records, "FINAL-REVIEW-v1-OBSERVATIONS.json");
  const output = path.join(records, "FINAL-REVIEW-v1.json");
  const file = { path: video, sha256: fileSha256(video)! };
  const draft = () => ({ schemaVersion: 2, kind: "native-final-review-observations", rolePacketSha256: packet.sha256,
    reviewer: reviewer(), coverage: coverage(), verdict: "pass", summary: "TEST structural submission; nothing was watched.",
    materialIssues: [] as unknown[], findings: [] as unknown[], limitations: ["TEST: no playback or listening occurred."],
    evidence: [] as unknown[], inspection: [inspected("motion-playback", file), inspected("audio-listening", file)] as unknown[],
    approves: ["picture", "motion", "audio"] as string[], frameNotes: [{ frame: 0, note: "TEST" }],
    events: events.map(row => ({ frame: row.frame, note: "TEST" })), assessment: "TEST validator fixture only." });
  return { root, project, plan, video, file, delivery, packet, records, observations, output, draft,
    write: (value: unknown) => writeJson(observations, value),
    submit: () => submitNativeFinalReview({ packet: packet.path, observations, output }) };
}
