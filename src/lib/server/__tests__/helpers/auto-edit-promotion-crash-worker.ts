import fs from "node:fs";
import path from "node:path";
import {
  promoteApprovedCandidate,
  type ApprovalRecord,
} from "../../auto-edit-quality-artifacts";
import type { PromotionCrashBoundary } from
  "../../candidate-promotion-transaction";

const root = path.resolve(process.argv[2] ?? "");
const producer = path.join(root, "producer");
const candidate = process.argv[3] ?? "";
const boundary = process.argv[4] as PromotionCrashBoundary;
const record = JSON.parse(
  fs.readFileSync(path.join(root, "approval-record.json"), "utf8"),
) as ApprovalRecord;

promoteApprovedCandidate(candidate, producer, record, {
  afterBoundary: (observed) => {
    if (observed === boundary) process.exit(71);
  },
});
