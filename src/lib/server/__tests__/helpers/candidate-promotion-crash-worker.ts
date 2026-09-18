import fs from "node:fs";
import path from "node:path";
import {
  runRecoverablePromotionSync,
  type PromotionCrashBoundary,
} from "../../candidate-promotion-transaction";

const root = path.resolve(process.argv[2] ?? "");
const boundary = process.argv[3] as PromotionCrashBoundary | "during-commit";
const producer = path.join(root, "producer");
const candidate = path.join(producer, "candidate.mp4");
const diagnostic = path.join(producer, "candidate-audit.json");
const plan = path.join(producer, "edit_plan.json");

runRecoverablePromotionSync({
  scopeRoot: producer,
  transactionId: "a".repeat(64),
  recoveryRoot: path.join(producer, ".recovery"),
  reconciliationPath: path.join(producer, ".promotion-intent.json"),
  moves: [{
    source: candidate,
    destination: path.join(producer, "final.mp4"),
  }],
  copies: [{
    source: diagnostic,
    destination: path.join(producer, "audit.json"),
  }],
  mutablePaths: [plan],
  commit: () => {
    fs.writeFileSync(plan, "new-plan");
    if (boundary === "during-commit") process.exit(70);
    if (boundary === "after-rollback-marked") {
      throw new Error("force rollback cleanup");
    }
  },
  afterBoundary: (observed) => {
    if (observed === boundary) process.exit(70);
  },
});
