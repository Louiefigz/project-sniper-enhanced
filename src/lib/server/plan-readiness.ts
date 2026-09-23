/** Agent-authored editorial evidence is mandatory at every ordinary full-render entry. */
import path from "node:path";
import { spawnSync } from "node:child_process";
import { pythonInterpreter } from "@/app/api/_lib/spawn-python";
import { readCutPreviewObject, observeCutPreviewFile } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { validateProducerReview } from "@/app/api/producer/auto-edit/review-contract";
import type { AutoEditCtx } from "@/app/api/producer/auto-edit/stream";
import { exactKeys, objectValue, stringValue, sha256 } from "@/lib/producer/contracts/validation";
import { canonicalJsonSha256 as hash } from "./auto-edit-hash";
import { atomicWriteJsonSync } from "./atomic-file";
import { readinessPacket, type ReadinessPacket } from "./plan-readiness-packet";
import { reviewIdentity, reviewCoverage, reviewEvidence } from "./native-short-prebuild-review";

export const PLAN_REVIEWS = ".sniper-plan-reviews.json";
export const RENDER_READY = ".sniper-render-ready.json";
export const DRAFT_READY = ".sniper-draft-ready.json";
interface PreviewObservations { receipts: Set<string>; hashes: Map<string, string> }

function previews(value: unknown, units: Record<string, unknown>, observed: PreviewObservations): Set<string> {
  if (!Array.isArray(value) || value.length > 1001) throw new Error("Review needs bounded preview evidence");
  const covered = new Set<string>();
  for (const item of value) {
    const row = objectValue(item, "preview");
    const keys = ["unitId", "unitHash", "path", "sha256", "receipt", "assessment"];
    exactKeys(row, keys, keys, "preview");
    const id = stringValue(row.unitId, "preview unit", 128);
    if (row.unitHash !== units[id]) throw new Error("Preview has a different review unit");
    const file = stringValue(row.path, "preview file", 4096);
    if (!path.isAbsolute(file) || !/\.(mp4|mov|webm)$/i.test(file)) throw new Error("Preview must bind a local moving-image file");
    if (!observed.hashes.has(file)) observed.hashes.set(file, observeCutPreviewFile(file, 1024 ** 3).sha256);
    if (observed.hashes.get(file) !== sha256(row.sha256, "preview hash")) throw new Error("Preview bytes changed");
    const receiptPath = stringValue(row.receipt, "preview receipt", 4096);
    const receipt = objectValue(readCutPreviewObject(receiptPath).value, "preview receipt");
    const receiptKeys = ["schemaVersion", "kind", "units", "media", "digest"];
    exactKeys(receipt, receiptKeys, receiptKeys, "preview receipt");
    const { digest, ...core } = receipt;
    const binding = objectValue(receipt.units, "preview receipt units");
    const media = objectValue(receipt.media, "preview media");
    const admission = objectValue(media.admission, "preview admission");
    const decoded = objectValue(admission.decoded, "preview decode");
    if (receipt.schemaVersion !== 1 || receipt.kind !== "producer-readiness-preview" || digest !== hash(core)
        || binding[id] !== row.unitHash || media.path !== file || media.sha256 !== row.sha256
        || decoded.ok !== true || decoded.decoded !== true) throw new Error("Preview decode or current-unit binding is missing");
    stringValue(row.assessment, "preview assessment", 2000);
    observed.receipts.add(receiptPath);
    covered.add(id);
  }
  return covered;
}

function currentReview(value: unknown, packet: ReadinessPacket, observed: PreviewObservations): { session: string; units: string[] } {
  const row = objectValue(value, "plan review");
  const keys = ["reviewer", "coverage", "evidence", "review", "units", "previews"];
  exactKeys(row, keys, keys, "plan review");
  const reviewer = reviewIdentity(row.reviewer);
  reviewCoverage(row.coverage);
  const units = objectValue(row.units, "reviewed units");
  for (const digest of Object.values(units)) sha256(digest, "reviewed unit hash");
  const matching = packet.units.filter(unit => units[unit.id] === unit.hash);
  if (!matching.length) return { session: reviewer.sessionId, units: [] };
  const review = validateProducerReview(row.review, "plan");
  if (review.verdict !== "pass" || review.materialIssues.length) throw new Error("Current review has unresolved material findings");
  reviewEvidence(row.evidence);
  const previewed = previews(row.previews, units, observed);
  if (matching.some(unit => unit.previewRequired && !previewed.has(unit.id))) throw new Error("Current review lacks required moving-preview evidence");
  return { session: reviewer.sessionId, units: matching.map(unit => unit.id) };
}

/** Retain unchanged units; count distinct declared reviewers on each current dependency set. */
export function assertPlanReviews(directory: string, packet: ReadinessPacket): string {
  const observed = readCutPreviewObject(path.join(directory, PLAN_REVIEWS));
  const bundle = objectValue(observed.value, "plan review bundle");
  exactKeys(bundle, ["schemaVersion", "reviews"], ["schemaVersion", "reviews"], "plan review bundle");
  if (bundle.schemaVersion !== 1 || !Array.isArray(bundle.reviews) || bundle.reviews.length > 256) throw new Error("Invalid plan review bundle");
  const previewsSeen: PreviewObservations = { receipts: new Set(), hashes: new Map() };
  const reviews = bundle.reviews.map(row => currentReview(row, packet, previewsSeen));
  for (const unit of packet.units) {
    const sessions = new Set(reviews.filter(review => review.units.includes(unit.id)).map(review => review.session));
    if (sessions.size < packet.requiredReviews) throw new Error(`Render readiness needs ${packet.requiredReviews} current independent reviews for ${unit.id}`);
  }
  const decoded = spawnSync(pythonInterpreter(), ["scripts/producer/readiness_preview.py", "--verify"],
    { input: JSON.stringify([...previewsSeen.receipts]), encoding: "utf8", timeout: 120000, maxBuffer: 1024 * 1024 });
  if (decoded.error || decoded.status !== 0) throw new Error(`Preview admission rejected: ${decoded.error?.message || decoded.stdout || decoded.stderr}`);
  return observed.sha256;
}

/** Called only after the shared deterministic gate bundle passed; drafts have separate authority. */
export function writeRenderReadiness(ctx: AutoEditCtx, approval: { draft?: boolean; gates: { ok: boolean; errors: unknown[] } }): void {
  if (!approval.gates.ok || approval.gates.errors.length) throw new Error("Render readiness requires passing deterministic gates");
  const draft = approval.draft === true;
  const packet = readinessPacket(ctx);
  const reviews = draft ? null : assertPlanReviews(ctx.dir, packet);
  const core = { schemaVersion: 1, kind: draft ? "producer-draft-readiness" : "producer-render-readiness",
    packetDigest: packet.digest, reviewsSha256: reviews, gateDigest: hash(approval.gates),
    independence: "reviewer-declared-not-authenticated" };
  atomicWriteJsonSync(path.join(ctx.dir, draft ? DRAFT_READY : RENDER_READY), { ...core, digest: hash(core) });
}

/** No graphic/scope exception: a draft receipt never admits a full final or resume. */
export function assertRenderReadiness(ctx: AutoEditCtx, draft = false): void {
  const packet = readinessPacket(ctx);
  const row = objectValue(readCutPreviewObject(path.join(ctx.dir, draft ? DRAFT_READY : RENDER_READY)).value, "render readiness");
  const { digest, ...core } = row;
  if (row.schemaVersion !== 1 || row.kind !== (draft ? "producer-draft-readiness" : "producer-render-readiness")
      || digest !== hash(core) || row.packetDigest !== packet.digest) throw new Error("Render readiness is stale or invalid; review the current plan");
  if (!draft && row.reviewsSha256 !== assertPlanReviews(ctx.dir, packet)) throw new Error("Plan reviews changed after render approval");
}
