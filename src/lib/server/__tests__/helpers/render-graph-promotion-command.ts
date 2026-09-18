import fs from "node:fs";
import path from "node:path";
import {
  canonicalJson,
  canonicalJsonSha256,
  fileSha256,
} from "../../auto-edit-hash";

function argument(args: string[], name: string): string {
  const index = args.indexOf(name);
  if (index < 0 || !args[index + 1]) {
    throw new Error(`missing render graph test argument ${name}`);
  }
  return args[index + 1]!;
}

function candidatePointer(
  producer: string,
  candidate: string,
): Record<string, unknown> {
  const key = canonicalJsonSha256({
    kind: "current-render-candidate-path",
    path: candidate,
  });
  return JSON.parse(fs.readFileSync(path.join(
    producer, ".render-graph-v1", "candidates", `${key}.json`,
  ), "utf8")) as Record<string, unknown>;
}

function writeJson(filePath: string, value: unknown): void {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, `${canonicalJson(value)}\n`);
}

function activate(args: string[]): { ok: true; graphHash: string } {
  const producer = argument(args, "--producer-dir");
  const candidate = argument(args, "--candidate");
  const final = argument(args, "--final");
  const pointer = candidatePointer(producer, candidate);
  const graphHash = String(pointer.graphHash);
  const receiptHash = String(pointer.receiptHash);
  const receiptPath = path.join(
    producer, ".render-graph-v1", "generations", graphHash,
    "receipts", `${receiptHash}.json`,
  );
  const receipt = JSON.parse(
    fs.readFileSync(receiptPath, "utf8")) as Record<string, unknown>;
  const artifacts = receipt.artifacts as Array<Record<string, unknown>>;
  receipt.artifacts = artifacts.map((row) =>
    row.nodeId === "node-final" ? {
      ...row,
      path: final,
      sha256: fileSha256(final),
      sizeBytes: fs.statSync(final).size,
    } : row);
  const promotedReceiptHash = canonicalJsonSha256(receipt);
  writeJson(path.join(
    producer, ".render-graph-v1", "generations", graphHash,
    "receipts", `${promotedReceiptHash}.json`,
  ), receipt);
  writeJson(path.join(producer, ".render-graph-v1", "ACTIVE.json"), {
    schemaVersion: 1,
    graphHash,
    receiptHash: promotedReceiptHash,
  });
  return { ok: true, graphHash };
}

export function renderGraphPromotionCommand(args: string[]) {
  const action = args[0];
  const producer = argument(args, "--producer-dir");
  const candidate = argument(args, "--candidate");
  const pointer = candidatePointer(producer, candidate);
  const graphHash = String(pointer.graphHash);
  if (action === "verify") return { ok: true, graphHash };
  if (action === "activate") return activate(args);
  if (action === "candidate-active") return { ok: true, graphHash };
  if (action === "rollback") {
    fs.rmSync(path.join(
      producer, ".render-graph-v1", "ACTIVE.json"), { force: true });
    return { ok: true, graphHash };
  }
  throw new Error(`unsupported render graph test action ${action}`);
}
