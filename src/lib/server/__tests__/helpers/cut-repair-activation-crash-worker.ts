import fs from "node:fs";
import path from "node:path";
import { activateCutRepairPromotionMediaSync } from
  "../../cut-repair-media-activation";
import { parseCutRepairTransitionRecord } from
  "../../cut-repair-transition-model";
import type { PromotionCrashBoundary } from
  "../../candidate-promotion-transaction";

const root = path.resolve(process.argv[2] ?? "");
const producer = process.argv[3] ?? "";
const boundary = process.argv[4] as PromotionCrashBoundary;
const record = parseCutRepairTransitionRecord(JSON.parse(
  fs.readFileSync(path.join(root, "cut-repair-record.json"), "utf8"),
));

activateCutRepairPromotionMediaSync(producer, record, (observed) => {
  if (observed === boundary) process.exit(72);
});
