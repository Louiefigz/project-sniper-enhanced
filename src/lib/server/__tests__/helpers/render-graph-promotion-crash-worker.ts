import fs from "node:fs";
import path from "node:path";
import type { ApprovalRecord } from "../../auto-edit-quality-artifacts";
import { promoteApprovedCandidateWithRenderGraph } from
  "../../current-render-graph-candidate";
import type { PromotionCrashBoundary } from
  "../../candidate-promotion-transaction";
import { renderGraphPromotionCommand } from
  "./render-graph-promotion-command";

const root = path.resolve(process.argv[2] ?? "");
const producer = process.argv[3] ?? "";
const candidate = process.argv[4] ?? "";
const boundary = process.argv[5] as PromotionCrashBoundary;
const record = JSON.parse(fs.readFileSync(
  path.join(root, "graph-promotion-record.json"), "utf8",
)) as ApprovalRecord;

promoteApprovedCandidateWithRenderGraph(
  candidate,
  producer,
  record,
  {
    command: renderGraphPromotionCommand,
    afterPromotionBoundary: (observed) => {
      if (observed === boundary) process.exit(73);
    },
  },
);
