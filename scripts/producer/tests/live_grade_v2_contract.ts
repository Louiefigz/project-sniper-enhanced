/** TEST-only closed live-return checks. Importing this module launches nothing. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { canonicalJsonSha256 } from "../../../src/lib/server/auto-edit-hash";
import { object, parents, readRecord, SHA } from "../../../src/lib/server/grade-observation-store";
import type { GradeProcessResult } from "../../../src/lib/server/grade-observation-process";

export const PROFILE = "original-uhd-xvycc709-observation-v2";
export const PROJECT_POLICY = "sniper-private-project-source-observation-v2";
export const WORK_NS = BigInt(120_000_000_000);
export function fixtureProducer(raw: string): string {
  if (!path.isAbsolute(raw) || fs.realpathSync(raw) !== raw || !raw.startsWith("/private/tmp/sniper-grade-v2-live-")
      || path.basename(raw) !== "producer" || path.basename(path.dirname(raw)) !== "synthetic") throw new Error("Exact newly created TEST producer required");
  const project = readRecord(path.join(path.dirname(raw), "project.json"));
  if (project.syntheticTestOnly !== true || project.gradeV2Fixture !== "native24-frames-tag-plumbing-only-v1") throw new Error("Not a V2 synthetic fixture");
  const manifest = readRecord(path.join(raw, "asset_manifest.json"));
  if (!Array.isArray(manifest.sources) || manifest.sources.length !== 1
      || JSON.stringify(manifest.broll) !== "[]" || JSON.stringify(manifest.music) !== "[]") throw new Error("Exactly one TEST source and no other media required");
  const source = object(manifest.sources[0]);
  if (source.originalPath !== path.join(path.dirname(raw), "TEST-UHD-tagged.mp4")
      || source.id !== "raw-1" || typeof source.path !== "string"
      || !source.path.startsWith(path.join(raw, ".sniper-external-media") + path.sep)
      || fs.realpathSync(source.path) !== source.path || fs.statSync(source.path).size > 8 * 1024 * 1024
      || !Number.isSafeInteger(source.sourceSizeBytes) || Number(source.sourceSizeBytes) < 1
      || Number(source.sourceSizeBytes) > 8 * 1024 * 1024) throw new Error("Creator/large media cannot enter this TEST harness");
  return raw;
}
export function v2Input(dir: string, jobId: string, implementationSha256: string, ownerPid = process.pid) {
  if (!/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/u.test(jobId)
      || !SHA.test(implementationSha256) || !Number.isSafeInteger(ownerPid) || ownerPid < 2) throw new Error("Invalid TEST owner identities");
  return { schemaVersion: 2, policy: PROJECT_POLICY, profile: PROFILE, jobId, producerDir: dir,
    sourceId: "raw-1", ownerPid, implementationSha256, expected: parents(dir),
    declaration: { schemaVersion: 2, sourceId: "raw-1", sourceProfile: "unknown", cameraProfile: null,
      historyState: "unknown", transformHistory: [], lightingGroups: [{ id: "whole", startFrame: 0,
        endFrame: 24, intent: "unknown", description: "TEST synthetic metadata only; not color/gamut evidence" }] } };
}
export function workerArgs(script: string, directory: string, inputSha: string): string[] {
  if (!path.isAbsolute(script) || !path.isAbsolute(directory) || !SHA.test(inputSha)) throw new Error("Invalid TEST invocation");
  return ["-I", "-S", "-B", script, path.join(directory, "input.json"), inputSha, "--profile", PROFILE];
}
export function assertLiveReturn(held: GradeProcessResult, closed: { code: number | null; signal: string | null; absent: boolean }): void {
  if (held.status !== "complete" || held.cleanupVerified !== true || !held.resultSha256 || !SHA.test(held.resultSha256)
      || !held.handshake || held.failure || closed.code !== 0 || closed.signal !== null || !closed.absent)
    throw new Error("Actual normal owner return, group absence and exact cleanup are required");
}
export function assertResult(value: Record<string, unknown>, input: ReturnType<typeof v2Input>, inputSha: string): Record<string, unknown> {
  const keys = ["schemaVersion", "policy", "profile", "limits", "jobId", "inputSha256", "status", "cleanupVerified",
    "cleanupMs", "workerPhaseMs", "replayMs", "gradeApplicable", "deliveryApproved", "parentsSha256", "observation",
    "implementation", "elapsedMs", "artifactHash"];
  if (Object.keys(value).sort().join() !== keys.sort().join()) throw new Error("V2 success record is not closed");
  const { artifactHash, ...body } = value;
  if (artifactHash !== canonicalJsonSha256(body) || value.schemaVersion !== 2 || value.policy !== PROJECT_POLICY
      || value.profile !== PROFILE || value.inputSha256 !== inputSha || value.jobId !== input.jobId
      || value.status !== "complete" || value.cleanupVerified !== true || value.gradeApplicable !== false
      || value.deliveryApproved !== false) throw new Error("V2 live result authority differs");
  const observation = object(value.observation), source = object(observation.source);
  const metadata = object(observation.sourceMetadata);
  if (source.sourceId !== "raw-1" || source.fps !== "24000/1001" || source.frameCount !== 24
      || source.declarationSha256 !== canonicalJsonSha256(input.declaration)
      || observation.decodedFrames !== 24 || observation.width !== 3840 || observation.height !== 2160
      || observation.firstPts !== 0 || observation.timeBase !== "1/24000" || observation.stepTicks !== 1001
      || observation.gradeApplicable !== false || observation.deliveryApproved !== false
      || metadata.profile !== PROFILE || metadata.transfer !== "iec61966-2-4" || metadata.transformApplicable !== false)
    throw new Error("Whole original UHD EOF/clock/metadata observation differs");
  return observation;
}
export function assertSameParents(dir: string, expected: ReturnType<typeof parents>): void {
  assert.deepEqual(parents(dir), expected, "Original project/plan/manifest changed");
}
