import path from "node:path";
import {
  exactKeys,
  objectValue,
  sha256,
} from "@/lib/producer/contracts/validation";
import { canonicalJsonSha256 } from "@/lib/server/auto-edit-hash";
import { loadCutRepairPreparationByHashSync } from
  "@/lib/server/cut-repair-preparation-store";
import {
  runCutRepairPython,
  type CutRepairProcessResult,
} from "./cut-repair-route-runner";
import { SCRIPTS_DIR } from "../../_lib/spawn-python";

const CONTROLLER = path.join(
  SCRIPTS_DIR, "producer", "edit", "cut_repair_candidate_qc.py");
const TIMEOUT_MS = 15 * 60 * 1000;
const LANES = ["alignment", "vad", "retranscription", "seam"] as const;

export interface CutRepairAutomatedQcLane {
  status: "bounded-pass";
  receiptHash: string;
  candidateCompositeSha256: string;
  receipt: Record<string, unknown>;
}

export interface CutRepairAutomatedQcPass {
  ok: true;
  status: "automated-qc-passed";
  preparationHash: string;
  candidateDescriptorHash: string;
  operationHash: string;
  candidateCompositeSha256: string;
  automatedQcBundleHash: string;
  automatedQcBundlePath: string;
  alignment: CutRepairAutomatedQcLane;
  vad: CutRepairAutomatedQcLane;
  retranscription: CutRepairAutomatedQcLane;
  seam: CutRepairAutomatedQcLane;
  operatorAuditionProduced: false;
}

export interface CutRepairAutomatedQcBlocked {
  ok: false;
  status: "automated-qc-blocked";
  preparationHash: string;
  candidateDescriptorHash: string;
  operationHash: string;
  candidateCompositeSha256: string;
  blockers: Record<string, { code: string; message: string }>;
  operatorAuditionProduced: false;
}

export type CutRepairAutomatedQcResult =
  | CutRepairAutomatedQcPass
  | CutRepairAutomatedQcBlocked;

function processValue(result: CutRepairProcessResult): Record<string, unknown> {
  let value: unknown;
  try {
    value = JSON.parse(result.stdout.trim());
  } catch {
    throw new Error(
      result.stderr.trim() || "candidate QC controller returned no JSON");
  }
  const row = objectValue(value, "candidate QC controller result");
  if (result.code !== 0) {
    const blocker = objectValue(
      row.blocker, "candidate QC controller blocker");
    throw new Error(
      typeof blocker.message === "string"
        ? blocker.message : "candidate QC controller rejected its input");
  }
  return row;
}

function laneValue(
  value: unknown,
  operationHash: string,
  candidateHash: string,
  label: string,
): CutRepairAutomatedQcLane {
  const lane = objectValue(value, `${label} automated QC lane`);
  const keys = [
    "status", "receiptHash", "candidateCompositeSha256", "receipt",
  ];
  exactKeys(lane, keys, keys, `${label} automated QC lane`);
  const receipt = objectValue(lane.receipt, `${label} automated QC receipt`);
  const receiptHash = sha256(
    lane.receiptHash, `${label} automated QC receipt hash`);
  if (lane.status !== "bounded-pass"
      || lane.candidateCompositeSha256 !== candidateHash
      || receipt.status !== "bounded-pass"
      || receipt.operationHash !== operationHash
      || receipt.candidateCompositeSha256 !== candidateHash
      || canonicalJsonSha256(receipt) !== receiptHash) {
    throw new Error(`${label} automated QC receipt is stale`);
  }
  return {
    status: "bounded-pass",
    receiptHash,
    candidateCompositeSha256: candidateHash,
    receipt,
  };
}

function blockers(value: unknown): Record<
  string, { code: string; message: string }
> {
  const row = objectValue(value, "candidate QC blockers");
  return Object.fromEntries(Object.entries(row).map(([lane, item]) => {
    const blocker = objectValue(item, `${lane} candidate QC blocker`);
    exactKeys(
      blocker, ["code", "message"], ["code", "message"],
      `${lane} candidate QC blocker`);
    if (typeof blocker.code !== "string" || !blocker.code
        || typeof blocker.message !== "string" || !blocker.message) {
      throw new Error(`${lane} candidate QC blocker is malformed`);
    }
    return [lane, { code: blocker.code, message: blocker.message }];
  }));
}

interface ExpectedBindings {
  preparationHash: string;
  descriptorHash: string;
  operationHash: string;
  candidateHash: string;
}

function assertBindings(
  row: Record<string, unknown>,
  expected: ExpectedBindings,
): void {
  if (row.preparationHash !== expected.preparationHash
      || row.candidateDescriptorHash !== expected.descriptorHash
      || row.operationHash !== expected.operationHash
      || row.candidateCompositeSha256 !== expected.candidateHash
      || row.operatorAuditionProduced !== false) {
    throw new Error("candidate QC result is stale or manufactured audition");
  }
}

function parsePass(
  row: Record<string, unknown>,
  expected: ExpectedBindings,
): CutRepairAutomatedQcPass {
  assertBindings(row, expected);
  if (row.ok !== true || row.status !== "automated-qc-passed"
      || typeof row.automatedQcBundlePath !== "string") {
    throw new Error("candidate QC pass result is malformed");
  }
  const result = {
    ok: true,
    status: "automated-qc-passed",
    preparationHash: expected.preparationHash,
    candidateDescriptorHash: expected.descriptorHash,
    operationHash: expected.operationHash,
    candidateCompositeSha256: expected.candidateHash,
    automatedQcBundleHash: sha256(
      row.automatedQcBundleHash, "automated QC bundle hash"),
    automatedQcBundlePath: row.automatedQcBundlePath,
    operatorAuditionProduced: false,
  } as CutRepairAutomatedQcPass;
  LANES.forEach((lane) => {
    result[lane] = laneValue(
      row[lane], expected.operationHash, expected.candidateHash, lane);
  });
  return result;
}

function parseResult(
  row: Record<string, unknown>,
  expected: ExpectedBindings,
): CutRepairAutomatedQcResult {
  if (row.status === "automated-qc-passed") {
    return parsePass(row, expected);
  }
  assertBindings(row, expected);
  if (row.ok !== false || row.status !== "automated-qc-blocked") {
    throw new Error("candidate QC result status is unsupported");
  }
  return {
    ok: false,
    status: "automated-qc-blocked",
    preparationHash: expected.preparationHash,
    candidateDescriptorHash: expected.descriptorHash,
    operationHash: expected.operationHash,
    candidateCompositeSha256: expected.candidateHash,
    blockers: blockers(row.blockers),
    operatorAuditionProduced: false,
  };
}

function expectedBindings(
  preparationHash: string,
  packageValue: ReturnType<
    typeof loadCutRepairPreparationByHashSync
  >["package"],
): ExpectedBindings {
  return {
    preparationHash,
    descriptorHash: packageValue.reviewCandidateDescriptorHash,
    operationHash: packageValue.proposedReviewAction.operationHash,
    candidateHash: packageValue.reviewCandidateMediaSha256,
  };
}

async function invoke(
  producerDir: string,
  preparationHash: string,
  args: string[],
): Promise<Record<string, unknown>> {
  return processValue(await runCutRepairPython(
    CONTROLLER, [producerDir, preparationHash, ...args],
    "cut repair candidate automated QC", TIMEOUT_MS));
}

/** Run exact candidate QC after reopening the full preparation authority. */
export async function runCutRepairCandidateQc(
  producerDir: string,
  preparationHash: string,
  toolManifestPath: string,
): Promise<CutRepairAutomatedQcResult> {
  const stored = loadCutRepairPreparationByHashSync(
    producerDir, preparationHash);
  const row = await invoke(
    producerDir, preparationHash, [toolManifestPath]);
  return parseResult(
    row, expectedBindings(preparationHash, stored.package));
}

/** Reopen the immutable pass bundle without rerunning media observers. */
export async function loadCutRepairCandidateQc(
  producerDir: string,
  preparationHash: string,
): Promise<CutRepairAutomatedQcPass> {
  const stored = loadCutRepairPreparationByHashSync(
    producerDir, preparationHash);
  const row = await invoke(producerDir, preparationHash, ["--reopen"]);
  const parsed = parseResult(
    row, expectedBindings(preparationHash, stored.package));
  if (!parsed.ok) throw new Error("stored candidate QC bundle is not a pass");
  return parsed;
}
