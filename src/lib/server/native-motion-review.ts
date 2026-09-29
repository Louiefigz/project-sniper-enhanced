/** Reusable, declared independent judgments on actual native moving-preview regions.
 * Full picture needs typed motion approval: normal-speed playback of every window of the exact preview bytes,
 * with the answered role packet and submission times re-checked here. Historical rows without typed inspection stay
 * readable; under schema-2 (Short) packets they establish nothing, and under schema-1 (Long) packets, which have no
 * typed review producer yet, they keep their historical admission and are reported as untyped. A route-canary TEST
 * declaration admits only its own TEST fixture's project and never counts as a review. */
import { realpathSync } from "node:fs";
import path from "node:path";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { validateProducerReview } from "@/app/api/producer/auto-edit/review-contract";
import { exactKeys, objectValue, sha256, stringValue, type JsonRecord } from "@/lib/producer/contracts/validation";
import { reviewCoverage, reviewEvidence, reviewIdentity } from "./native-short-prebuild-review";
import { canonicalJson } from "./auto-edit-hash";
import { assertApprovals, assertBoundToTargets, INSPECTION_AUTHENTICITY, readInspection, type Inspection, type ReviewTarget,
  type TestFixture } from "./native-review-submission-shared";
import { assertSubmission, frameClock } from "./native-review-provenance";

interface Unit { id: string; hash: string }
/** Schema-2 Short packets name a logical clip subject; schema-1 (Long) packets keep the exact project path. */
interface Packet { identity: string; units: Unit[]; typedRequired: boolean }
interface Admission { typed: boolean; audio: boolean; fixture: boolean; withheld: string | null }
interface ReviewedPreview { file: string; sha256: string; result: JsonRecord }
/** One matching row's already-verified parts. */
interface RowContext { preview: ReviewedPreview; packet: Packet; verdict: string; evidence: Array<{ path: string; sha256: string }> }
const ROW_KEYS = ["reviewer", "coverage", "evidence", "review", "units", "preview", "assessment"];
const UNTYPED = "a historical review without typed inspection cannot establish motion playback";
const PICTURE_ONLY = "its pass approves picture only; motion approval needs normal-speed playback of every window";

function packetIdentity(row: Record<string, unknown>): string {
  if (row.schemaVersion !== 2) return `project:${stringValue(row.project, "native region project", 4096)}`;
  const subject = objectValue(row.subject, "native region subject");
  const keys = Object.keys(subject);
  if (keys.length !== 1 || !["clip", "project"].includes(keys[0])) throw new Error("Invalid native region subject");
  stringValue(subject[keys[0]], "native region subject identity", 4096);
  return `subject:${canonicalJson(subject)}`;
}

function regionPacket(value: unknown): Packet {
  const row = objectValue(value, "native region packet");
  const identity = packetIdentity(row);
  if (!Array.isArray(row.units) || !row.units.length || row.units.length > 259) throw new Error("Invalid native region packet");
  const units = row.units.map(value => {
    const unit = objectValue(value, "native region unit");
    return { id: stringValue(unit.id, "native region ID", 128), hash: sha256(unit.hash, "native region hash") };
  });
  if (new Set(units.map(unit => unit.id)).size !== units.length) throw new Error("Duplicate native review region");
  return { identity, units, typedRequired: row.schemaVersion === 2 };
}

/** The reviewed preview's clips, which typed inspection must cover on their exact bytes. */
function previewTargets(result: JsonRecord): ReviewTarget[] {
  if (!Array.isArray(result.clips) || !result.clips.length) throw new Error("Reviewed native preview records no clips for typed inspection");
  return result.clips.map((value, index) => {
    const clip = objectValue(value, `native preview clip ${index}`), start = clip.startFrame, end = clip.endFrameExclusive;
    if (!Number.isSafeInteger(start) || !Number.isSafeInteger(end) || (start as number) < 0 || (end as number) <= (start as number)) {
      throw new Error(`native preview clip ${index} frames are invalid`);
    }
    return { path: realpathSync(stringValue(clip.path, "native preview clip path", 4096)),
      sha256: sha256(clip.sha256, "native preview clip hash"), startFrame: start as number, endFrameExclusive: end as number };
  });
}

/** A TEST declaration names a TEST fixture manifest without production authority, and the reviewed preview's attempt
 * exported exactly the fixture project that manifest lists. */
function assertTestFixture(fixture: TestFixture, preview: ReviewedPreview): void {
  const observed = readCutPreviewObject(fixture.manifest.path), manifest = objectValue(observed.value, "TEST fixture manifest");
  const projects = Object.values(objectValue(manifest.variants, "TEST fixture variants"))
    .map(row => objectValue(row, "TEST fixture variant").project);
  const request = objectValue(readCutPreviewObject(path.join(path.dirname(preview.file), "export-request.json")).value,
    "TEST preview export request");
  const root = path.dirname(fixture.manifest.path);
  if (observed.sha256 !== fixture.manifest.sha256 || manifest.scope !== fixture.scope || manifest.productionAuthority !== false
      || fixture.manifest.path !== path.join(root, "FIXTURE.json") || request.productionBudget !== undefined
      || !projects.includes(fixture.project) || request.project !== fixture.project
      || !fixture.project.startsWith(`${root}${path.sep}`)) {
    throw new Error("A TEST route-canary declaration is admitted only for its own TEST fixture project (the canary "
      + "layout's <root>/FIXTURE.json, a preview no production batch budgets) without production authority");
  }
}

/** Provenance for a typed row, or the TEST fixture check for a canary declaration (which carries none). */
function assertRowProvenance(row: JsonRecord, inspection: Inspection, context: RowContext, targets: ReviewTarget[]): void {
  if (inspection.fixture) {
    if (row.submission !== null || row.approvedContent !== null) throw new Error("A TEST fixture declaration carries no submission");
    assertTestFixture(inspection.fixture, context.preview);
    return;
  }
  const canvas = objectValue(objectValue(context.preview.result.packet, "native region packet").canvas, "native region canvas");
  assertSubmission(row.submission, { role: "motion-critic", evidence: context.evidence, inspection, targets,
    fps: frameClock(canvas.frameRate, canvas.totalFrames).fps, reviewer: row.reviewer, verdict: context.verdict,
    approvedContent: row.approvedContent, subject: { preview: { path: context.preview.file, sha256: context.preview.sha256 } },
    record: row });
}

/** Typed rows admit only a verified motion approval on their own preview's clips. */
function admission(row: JsonRecord, context: RowContext): Admission {
  if (row.inspection === undefined) {
    return { typed: false, audio: false, fixture: false, withheld: context.packet.typedRequired ? UNTYPED : null };
  }
  const inspection = readInspection(row.inspection, "native motion review inspection", true);
  const targets = previewTargets(context.preview.result);
  assertBoundToTargets(inspection, targets);
  assertApprovals(inspection, targets, context.verdict);
  assertRowProvenance(row, inspection, context, targets);
  return { typed: true, audio: inspection.approves.includes("audio"), fixture: Boolean(inspection.fixture),
    withheld: inspection.approves.includes("motion") ? null : PICTURE_ONLY };
}

function reviewedPreview(row: JsonRecord, packet: Packet, matching: Unit[]): ReviewedPreview {
  const preview = objectValue(row.preview, "native reviewed preview");
  exactKeys(preview, ["path", "sha256"], ["path", "sha256"], "native reviewed preview");
  const file = stringValue(preview.path, "native preview path", 4096), observed = readCutPreviewObject(file);
  if (observed.sha256 !== sha256(preview.sha256, "native preview hash")) throw new Error("Reviewed native preview changed");
  const result = objectValue(observed.value, "native preview result"), prior = regionPacket(result.packet);
  if (result.status !== "native-motion-previews-complete" || prior.identity !== packet.identity
      || matching.some(unit => !prior.units.some(prior => prior.id === unit.id && prior.hash === unit.hash))) {
    throw new Error("Native review does not bind current preview regions");
  }
  return { file, sha256: observed.sha256, result };
}

function reviewRow(value: unknown, packet: Packet) {
  const row = objectValue(value, "native motion review");
  const typedKeys = [...ROW_KEYS, "inspection", "submission", "approvedContent"];
  exactKeys(row, typedKeys, row.inspection === undefined ? ROW_KEYS : typedKeys, "native motion review");
  const reviewer = reviewIdentity(row.reviewer);
  reviewCoverage(row.coverage);
  const units = objectValue(row.units, "native reviewed units");
  for (const hash of Object.values(units)) sha256(hash, "native review unit hash");
  const matching = packet.units.filter(unit => units[unit.id] === unit.hash);
  const empty = { session: reviewer.sessionId, matched: [] as string[], units: [] as string[], pins: [] as Array<{ path: string; sha256: string }>,
    typed: false, audio: false, fixture: false, withheld: null as string | null };
  if (!matching.length) return empty;
  const review = validateProducerReview(row.review, "plan");
  if (review.verdict !== "pass" || review.materialIssues.length) throw new Error("Native preview review has unresolved material findings");
  const evidence = reviewEvidence(row.evidence);
  stringValue(row.assessment, "native playback assessment and limitations", 4000);
  const preview = reviewedPreview(row, packet, matching);
  const admitted = admission(row, { preview, packet, verdict: review.verdict, evidence });
  const matched = matching.map(unit => unit.id);
  if (admitted.withheld) return { ...empty, matched, typed: admitted.typed, withheld: admitted.withheld };
  return { ...empty, ...admitted, matched, units: matched, pins: [...evidence, { path: preview.file, sha256: preview.sha256 }] };
}

/** Python additionally validates completed owners, ancestor receipts and actual retained media. */
export function assertNativeMotionReviews(file: string, packetFile: string) {
  return assertNativeMotionReviewBundle(file, readCutPreviewObject(packetFile).value);
}

/** The same admission for a packet value already read under the canonical artifact rule. */
export function assertNativeMotionReviewBundle(file: string, packetValue: unknown) {
  const packet = regionPacket(packetValue);
  const observed = readCutPreviewObject(file), bundle = objectValue(observed.value, "native motion reviews");
  exactKeys(bundle, ["schemaVersion", "reviews"], ["schemaVersion", "reviews"], "native motion reviews");
  if (bundle.schemaVersion !== 1 || !Array.isArray(bundle.reviews) || bundle.reviews.length > 256) {
    throw new Error("Invalid native motion review bundle");
  }
  const rows = bundle.reviews.map(row => reviewRow(row, packet));
  for (const unit of packet.units) {
    if (rows.some(row => row.units.includes(unit.id))) continue;
    const reason = rows.find(row => row.withheld && row.matched.includes(unit.id))?.withheld;
    throw new Error(`Native moving preview needs a current independent review for ${unit.id}${reason ? ` (${reason})` : ""}`);
  }
  const admitting = rows.filter(row => row.units.length);
  return { status: "recorded-independent-motion-pass", independence: "reviewer-declared-not-authenticated",
    pins: [{ path: file, sha256: observed.sha256 }, ...rows.flatMap(row => row.pins)],
    inspection: { authenticity: INSPECTION_AUTHENTICITY, typedRows: admitting.filter(row => row.typed && !row.fixture).length,
      untypedRows: admitting.filter(row => !row.typed).length, testFixtureRows: admitting.filter(row => row.fixture).length,
      audioApprovedUnits: [...new Set(admitting.filter(row => row.audio).flatMap(row => row.units))] } };
}
