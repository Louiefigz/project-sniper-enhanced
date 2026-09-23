/** Reusable, declared independent judgments on actual native moving-preview regions. */
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { validateProducerReview } from "@/app/api/producer/auto-edit/review-contract";
import { exactKeys, objectValue, sha256, stringValue } from "@/lib/producer/contracts/validation";
import { reviewCoverage, reviewEvidence, reviewIdentity } from "./native-short-prebuild-review";

interface Unit { id: string; hash: string }
interface Packet { project: string; units: Unit[] }

function regionPacket(value: unknown): Packet {
  const row = objectValue(value, "native region packet");
  const project = stringValue(row.project, "native region project", 4096);
  if (!Array.isArray(row.units) || !row.units.length || row.units.length > 259) throw new Error("Invalid native region packet");
  const units = row.units.map(value => {
    const unit = objectValue(value, "native region unit");
    return { id: stringValue(unit.id, "native region ID", 128), hash: sha256(unit.hash, "native region hash") };
  });
  if (new Set(units.map(unit => unit.id)).size !== units.length) throw new Error("Duplicate native review region");
  return { project, units };
}

function reviewRow(value: unknown, packet: Packet) {
  const row = objectValue(value, "native motion review");
  const keys = ["reviewer", "coverage", "evidence", "review", "units", "preview", "assessment"];
  exactKeys(row, keys, keys, "native motion review");
  const reviewer = reviewIdentity(row.reviewer);
  reviewCoverage(row.coverage);
  const units = objectValue(row.units, "native reviewed units");
  for (const hash of Object.values(units)) sha256(hash, "native review unit hash");
  const matching = packet.units.filter(unit => units[unit.id] === unit.hash);
  if (!matching.length) return { session: reviewer.sessionId, units: [], pins: [] };
  const review = validateProducerReview(row.review, "plan");
  if (review.verdict !== "pass" || review.materialIssues.length) throw new Error("Native preview review has unresolved material findings");
  const evidence = reviewEvidence(row.evidence);
  stringValue(row.assessment, "native playback assessment and limitations", 4000);
  const preview = objectValue(row.preview, "native reviewed preview");
  exactKeys(preview, ["path", "sha256"], ["path", "sha256"], "native reviewed preview");
  const file = stringValue(preview.path, "native preview path", 4096), observed = readCutPreviewObject(file);
  if (observed.sha256 !== sha256(preview.sha256, "native preview hash")) throw new Error("Reviewed native preview changed");
  const result = objectValue(observed.value, "native preview result"), prior = regionPacket(result.packet);
  if (result.status !== "native-motion-previews-complete" || prior.project !== packet.project
      || matching.some(unit => !prior.units.some(prior => prior.id === unit.id && prior.hash === unit.hash))) {
    throw new Error("Native review does not bind current preview regions");
  }
  return { session: reviewer.sessionId, units: matching.map(unit => unit.id),
    pins: [...evidence, { path: file, sha256: observed.sha256 }] };
}

/** Python additionally validates completed owners, ancestor receipts and actual retained media. */
export function assertNativeMotionReviews(file: string, packetFile: string) {
  const packet = regionPacket(readCutPreviewObject(packetFile).value);
  const observed = readCutPreviewObject(file), bundle = objectValue(observed.value, "native motion reviews");
  exactKeys(bundle, ["schemaVersion", "reviews"], ["schemaVersion", "reviews"], "native motion reviews");
  if (bundle.schemaVersion !== 1 || !Array.isArray(bundle.reviews) || bundle.reviews.length > 256) {
    throw new Error("Invalid native motion review bundle");
  }
  const rows = bundle.reviews.map(row => reviewRow(row, packet));
  for (const unit of packet.units) {
    if (!rows.some(row => row.units.includes(unit.id))) throw new Error(`Native moving preview needs a current independent review for ${unit.id}`);
  }
  return { status: "recorded-independent-motion-pass", independence: "reviewer-declared-not-authenticated",
    pins: [{ path: file, sha256: observed.sha256 }, ...rows.flatMap(row => row.pins)] };
}
