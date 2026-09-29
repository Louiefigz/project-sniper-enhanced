/** TEST-only synthetic role packets, previews and exports. Nobody viewed or heard anything; no fixture is authority. */
import { mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import type { TestContext } from "node:test";
import { fileSha256 } from "../auto-edit-hash";
import { SCRIPTS_DIR } from "@/app/api/_lib/spawn-python";
import { NATIVE_PREBUILD_COVERAGE } from "../native-short-prebuild-review";
import { givenCheck, type RecordCheck } from "../native-review-given-check";

export const AUTHOR = "TEST-author-session";
export const CRITIC = "TEST-critic-session";
/** Packets resolve an hour before submission so TEST playback claims are not refused as impossible timing;
 * `rewritePacket` moves resolvedAt when a test needs a fresh packet. */
const RESOLVED_BEFORE_MS = 3600 * 1000;

/** TEST stand-in for the engine's `context.py --given-check` and `--review-submitted`, installed for every test that
 * imports this fixture: the batch authority is taken to agree with the packet's own given block (none is batch-bound
 * unless the block says so), a bound packet's recorded resolution is its own resolvedAt, and recorded submissions live
 * in `TEST_SUBMITTED` (record SHA-256 → event) for this process only. It never reads the real authority. Tests of
 * the re-check itself replace it; the real check runs in the Python end-to-end chain tests. */
export const TEST_SUBMITTED = new Map<string, { clipId: string; role: string; recordSha256: string; elapsed: number }>();

function testPacket(packetPath: string) {
  const packet = JSON.parse(readFileSync(packetPath, "utf8")) as { given?: Record<string, unknown>; resolvedAt: string; role: string };
  return { ...packet, given: packet.given ?? { status: "not-supplied", meaning: "TEST packet without a given block" } };
}

function testSubmitted(record: RecordCheck) {
  const found = TEST_SUBMITTED.get(record.recordSha256);
  if (!found) throw new Error(`Approved-content re-check refused this review: TEST batch did not record the submission of record ${record.recordSha256.slice(0, 12)}`);
  return found;
}

export function testGivenCheck(packetPath: string, record?: RecordCheck) {
  const packet = testPacket(packetPath), given = packet.given, bound = given.status === "bound";
  const clock = bound ? { batchId: given.batchId, clipId: given.clipId, resolvedElapsed: 0,
    nowElapsed: Math.max(0, (Date.now() - Date.parse(packet.resolvedAt)) / 1000) } : null;
  const submitted = bound && record ? testSubmitted(record) : null;
  const asSubmitted = submitted && record?.asSubmitted ? { submittedElapsed: submitted.elapsed, authorityStatus: given.authorityStatus,
    approvalIdentity: given.identity, approvalElapsed: 0, supersededBy: null } : null;
  return { status: "given-current", packet: { path: packetPath, sha256: fileSha256(packetPath)! }, given, batchClock: clock,
    submitted, asSubmitted };
}

export function testRecordSubmitted(packetPath: string, recordSha256: string, elapsed: number) {
  const packet = testPacket(packetPath);
  const event = { clipId: String(packet.given.clipId), role: packet.role, recordSha256, elapsed };
  TEST_SUBMITTED.set(recordSha256, event);
  return { status: "review-submitted-recorded", packet: { path: packetPath, sha256: fileSha256(packetPath)! },
    event: { event: "review-submitted", ...event } };
}
givenCheck.run = testGivenCheck;
givenCheck.record = testRecordSubmitted;

export function testRoot(t: TestContext, prefix = "TEST-native-review-"): string {
  const root = realpathSync(mkdtempSync(path.join(tmpdir(), prefix)));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  return root;
}

export function writeJson(file: string, value: unknown): string {
  mkdirSync(path.dirname(file), { recursive: true });
  writeFileSync(file, `${JSON.stringify(value, null, 2)}\n`);
  return file;
}

export function writeText(file: string, text: string): string {
  mkdirSync(path.dirname(file), { recursive: true });
  writeFileSync(file, text);
  return file;
}

/** A role packet with the same shape context.py publishes, freezing the given files. */
export function rolePacket(root: string, role: string, subject: Record<string, unknown>, frozen: Array<string | [string, "linked-media"]>) {
  const instruction = writeText(path.join(root, "TEST-INSTRUCTIONS.md"), "# TEST instructions\nSynthetic governing text.\n");
  const row = (entry: string | [string, "linked-media"], index: number) => {
    const [file, observation] = typeof entry === "string" ? [entry, "strict"] : entry;
    return { key: `TEST-${index}`, path: file, sha256: fileSha256(file)!, bytes: 1, observation, why: "TEST" };
  };
  const file = writeJson(path.join(root, "records", `${role}-PACKET.json`), { schemaVersion: 1, kind: "sniper-role-packet",
    catalog: "native-short-role-packets-v1", role, route: "native-short", resolvedAt: new Date(Date.now() - RESOLVED_BEFORE_MS).toISOString(),
    repository: root, authorSessionIds: [AUTHOR],
    instructions: [{ path: instruction, sha256: fileSha256(instruction)!, lines: 2, read: "whole", sections: [], why: "TEST" }],
    artifacts: frozen.map(row), declaredMedia: [], subject, checks: [], submission: {}, limits: [] });
  return { path: file, sha256: fileSha256(file)!, instruction };
}

/** Rewrite a TEST packet in place (for example its resolvedAt) and return its new hash. */
export function rewritePacket(file: string, change: (packet: Record<string, unknown>) => void): string {
  const packet = JSON.parse(readFileSync(file, "utf8")) as Record<string, unknown>;
  change(packet);
  writeJson(file, packet);
  return fileSha256(file)!;
}

/** One TEST inspection entry; still-frames name their sampled frames (default [0], for an artifact without a
 * program clock). Nothing was actually looked at, played or heard. */
export function inspected(kind: "still-frames" | "motion-playback" | "audio-listening", file: { path: string; sha256: string },
  span: unknown = "whole", samples: number[] = [0]) {
  return { kind, artifact: { path: file.path, sha256: file.sha256 }, span, method: `TEST fixture ${kind}: nothing was inspected`,
    ...(kind === "still-frames" ? { samples } : {}) };
}

export function coverage(): Record<string, string> {
  return Object.fromEntries(NATIVE_PREBUILD_COVERAGE.map(key => [key, "TEST synthetic assessment; nothing was inspected."]));
}

export function reviewer(sessionId = CRITIC, plannerSessionId = AUTHOR) {
  return { identity: "TEST synthetic critic", sessionId, plannerSessionId, independent: true };
}

/** A completed moving-preview record with three clips and one whole-project unit. */
export function motionFixture(root: string) {
  const project = path.join(root, "clip", "native-v1"), attempt = path.join(root, "clip", "preview-v1");
  mkdirSync(project, { recursive: true });
  const ranges = [[0, 60], [120, 180], [240, 300]];
  const clips = ranges.map(([start, end], index) => {
    const file = writeText(path.join(attempt, `window-${index}`, "core.mp4"), `TEST synthetic clip ${index}`);
    return { startFrame: start, endFrameExclusive: end, path: file, sha256: fileSha256(file)! };
  });
  const units = [{ id: "project", startFrame: 0, endFrame: 300, hash: "a".repeat(64) }];
  const preview = writeJson(path.join(attempt, "motion-previews.json"), { schemaVersion: 1, status: "native-motion-previews-complete",
    packet: { schemaVersion: 1, scope: "native-preview-dependencies-not-editorial-approval", project,
      canvas: { frameRate: "30/1", totalFrames: 300 }, sharedHash: "a".repeat(64), units },
    clips, changedUnits: ["project"], reusedUnits: [], priorPreview: null });
  const subject = { project, frameRate: "30/1", totalFrames: 300, preview: { path: preview, sha256: fileSha256(preview)! },
    windows: clips, units, changedUnits: ["project"], reusedUnits: [],
    retention: { reusedUnits: [], record: null, rows: [], missingUnits: [] } };
  const packet = rolePacket(root, "motion-critic", subject, [preview, ...clips.map(clip => clip.path)]);
  return { root, project, attempt, preview, clips, units, packet };
}

type Clip = { startFrame: number; endFrameExclusive: number; path: string; sha256: string };

/** A complete TEST pass observation file for the motion fixture: typed playback of every window, no listening.
 * Structure only; nobody viewed or heard anything. */
export function motionObservations(packetSha256: string, clips: Clip[]) {
  return { schemaVersion: 2, kind: "native-motion-review-observations", rolePacketSha256: packetSha256, reviewer: reviewer(),
    coverage: coverage(), verdict: "pass", summary: "TEST structural submission; no playback occurred.",
    materialIssues: [] as unknown[], findings: [] as unknown[],
    limitations: ["TEST: no playback or listening occurred; validator fixture only."], evidence: [] as unknown[],
    inspection: clips.map(clip => inspected("motion-playback", clip)) as Array<Record<string, unknown>>,
    approves: ["picture", "motion"] as string[],
    windows: clips.map(clip => ({ startFrame: clip.startFrame, endFrameExclusive: clip.endFrameExclusive,
      observations: [{ frame: clip.startFrame, note: "TEST synthetic note" }] })),
    assessment: "TEST validator fixture only." };
}

const OBSERVATION_KINDS: Record<string, string> = { "plan-critic": "native-plan-review-observations",
  "motion-critic": "native-motion-review-observations", "final-critic": "native-final-review-observations" };

/** The provenance a hand-assembled TEST typed record needs: a TEST role packet (resolved an hour ago), an observations
 * file repeating the record's reviewer, verdict and inspection, their evidence rows and the submission block. */
export function typedRecordParts(root: string, role: string, claims: { reviewer: unknown; verdict: string;
  inspection: { entries: unknown[]; approves: string[] }; materialIssues?: unknown[]; findings?: unknown[] },
  subject: Record<string, unknown> = {}, frozen: string[] = []) {
  const home = path.join(root, `TEST-typed-${role}-${Math.random().toString(36).slice(2, 8)}`);
  const packet = rolePacket(home, role, subject, [writeText(path.join(home, "TEST-subject.txt"), "TEST subject"), ...frozen]);
  const observations = writeJson(path.join(home, "records", "OBSERVATIONS.json"), { kind: OBSERVATION_KINDS[role],
    rolePacketSha256: packet.sha256, reviewer: claims.reviewer, verdict: claims.verdict,
    inspection: claims.inspection.entries, approves: claims.inspection.approves,
    materialIssues: claims.materialIssues ?? [], findings: claims.findings ?? [] });
  const resolvedAt = (JSON.parse(readFileSync(packet.path, "utf8")) as { resolvedAt: string }).resolvedAt;
  return { evidence: [{ path: observations, sha256: fileSha256(observations)! }, { path: packet.path, sha256: packet.sha256 }],
    submission: { schemaVersion: 2, role, rolePacket: { path: packet.path, sha256: packet.sha256 }, packetResolvedAt: resolvedAt,
      submittedAt: new Date().toISOString(), authenticity: "declared-not-authenticated",
      timing: { basis: "declared-not-authenticated" } },
    approvedContent: { approved: null, planChecked: false, departures: [] as string[], contradictions: [] as string[],
      proposedChanges: [] as string[] } };
}

type GivenChange = { planChecked?: boolean; title?: object; selection?: object; captionText?: object; timing?: object };
/** Unit B1's published `packet.given` contract: the same fixture file its Python tests read. */
const GIVEN_CONTRACT = path.join(SCRIPTS_DIR, "producer", "tests", "fixtures", "role-packet-given-contract.json");

type Fact = { matches: boolean; details: Record<string, unknown> };
type BoundExample = Record<string, unknown> & { title: Record<string, unknown>; selection: Fact; captionText: Fact; timing: Fact };

/** A fact change splits into its `matches` flag and the `details` it overrides. */
function changedFact(fact: Fact, change: object = {}) {
  const { matches, ...details } = change as { matches?: unknown };
  return { matches: matches ?? fact.matches, details: { ...fact.details, ...details } };
}

/** A `packet.given` block in the exact shape unit B1 publishes (its contract fixture's `bound` example, with the
 * TEST identities below): every fact agrees unless a change says otherwise. TEST values only. */
export function givenBlock(change: GivenChange = {}) {
  const contract = JSON.parse(readFileSync(GIVEN_CONTRACT, "utf8")) as { examples: { bound: BoundExample } };
  const bound = { ...contract.examples.bound, clipId: "TEST-Q1", identity: "b".repeat(64), scriptSha256: "a".repeat(64),
    title: { ...contract.examples.bound.title, given: "TEST Given Title", planned: "TEST Given Title" } };
  if (change.planChecked === false) {
    return { ...bound, planChecked: false, title: { given: "TEST Given Title" }, selection: null, captionText: null, timing: null };
  }
  return { ...bound, title: { ...bound.title, ...change.title }, selection: changedFact(bound.selection, change.selection),
    captionText: changedFact(bound.captionText, change.captionText), timing: changedFact(bound.timing, change.timing) };
}
