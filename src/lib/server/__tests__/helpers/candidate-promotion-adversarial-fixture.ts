import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import type { PromotionTopology } from "../../candidate-promotion-transaction";

const WORKER = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  "candidate-promotion-crash-worker.ts",
);

export type PromotionFixture = {
  root: string;
  producer: string;
  topology: PromotionTopology;
};

export function fixture(name: string): PromotionFixture {
  const root = fs.mkdtempSync(path.join(
    os.tmpdir(), `sniper-promotion-adversarial-${name}-`));
  const producer = path.join(root, "producer");
  fs.mkdirSync(producer);
  fs.writeFileSync(path.join(producer, "candidate.mp4"), "new-media");
  fs.writeFileSync(path.join(producer, "candidate-audit.json"), "new-audit");
  fs.writeFileSync(path.join(producer, "final.mp4"), "old-media");
  fs.writeFileSync(path.join(producer, "audit.json"), "old-audit");
  fs.writeFileSync(path.join(producer, "edit_plan.json"), "old-plan");
  return {
    root,
    producer,
    topology: {
      scopeRoot: producer,
      transactionId: "a".repeat(64),
      recoveryRoot: path.join(producer, ".recovery"),
      reconciliationPath: path.join(producer, ".promotion-intent.json"),
      moves: [{
        source: path.join(producer, "candidate.mp4"),
        destination: path.join(producer, "final.mp4"),
      }],
      copies: [{
        source: path.join(producer, "candidate-audit.json"),
        destination: path.join(producer, "audit.json"),
      }],
      mutablePaths: [path.join(producer, "edit_plan.json")],
    },
  };
}

export function crash(item: PromotionFixture, boundary: string): void {
  const result = spawnSync(
    process.execPath,
    ["--import", "tsx", WORKER, item.root, boundary],
    { encoding: "utf8" },
  );
  if (result.status !== 70) {
    throw new Error(result.stderr || result.stdout);
  }
}

export function marker(
  item: PromotionFixture,
): Record<string, unknown> {
  return JSON.parse(fs.readFileSync(
    item.topology.reconciliationPath, "utf8")) as Record<string, unknown>;
}

export function withFixture(
  name: string,
  test: (item: PromotionFixture) => void,
): void {
  const item = fixture(name);
  try {
    test(item);
  } finally {
    fs.rmSync(item.root, { recursive: true, force: true });
  }
}

export function terminalPath(item: PromotionFixture): string {
  return path.join(
    path.dirname(item.topology.recoveryRoot),
    "promotion-commits",
    `committed-${item.topology.transactionId}.json`,
  );
}
