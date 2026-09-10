import path from "node:path";
import {
  assertCutRepairSurgicalRenderGraph,
} from "@/lib/producer/contracts/cut-repair-surgical-render-graph";
import {
  exactKeys,
  objectValue,
  sha256,
  uniqueStrings,
} from "@/lib/producer/contracts/validation";
import type { CutRepairPicturePlanAuthorityV1 } from
  "@/lib/producer/contracts/cut-repair-picture-plan-authority";
import {
  fileSha256,
} from "@/lib/server/auto-edit-hash";
import type { CutRepairPreparedRender } from
  "@/lib/server/cut-repair-prepared-render-authority";
import {
  readAuthorityJsonSync,
} from "@/lib/server/producer-authority-files";
import type {
  StagedRenderGraphAuthority,
  StagedRenderGraphExpectation,
} from "@/lib/server/staged-render-graph-authority";
import { SCRIPTS_DIR } from "../../_lib/spawn-python";
import type { PreparedMediaResult } from "./cut-repair-preparation-plan";
import {
  runCutRepairPython,
  type CutRepairProcessResult,
} from "./cut-repair-route-runner";
import { verifyPrivatePictureTerminal } from
  "./cut-repair-private-picture-terminal";

const SURGICAL_TERMINAL = path.join(
  SCRIPTS_DIR, "producer", "edit", "cut_repair_surgical_terminal.py");
const TIMEOUT_MS = 90 * 60 * 1000;
const EVENT_KEYS = [
  "status", "graphHash", "receiptHash", "terminalReceiptHash",
  "terminalReceiptPath", "candidateSha256", "candidatePath",
  "previousGraphHash", "previousReceiptHash", "parentMediaSha256",
  "dirtyNodeIds", "reusedNodeIds",
] as const;
const NODE_IDS = [
  "node-source", "node-timeline", "node-base",
  "node-composite", "node-final",
];

export interface PrivatePictureRenderInput {
  producerDir: string;
  manifestPath: string;
  planPath: string;
  preparedPath: string;
  artifactDir: string;
  candidatePath: string;
  planObjectHash: string;
  planContentHash: string;
  prepared: PreparedMediaResult;
  pictureAuthority: CutRepairPicturePlanAuthorityV1;
}

export type PrivatePictureExecutor = (
  script: string,
  args: string[],
  label: string,
  timeoutMs: number,
) => Promise<CutRepairProcessResult>;
export type PrivatePictureObserver = (
  input: StagedRenderGraphExpectation,
) => StagedRenderGraphAuthority;

interface SurgicalEvent {
  graphHash: string;
  receiptHash: string;
  terminalReceiptHash: string;
  terminalReceiptPath: string;
  candidateSha256: string;
  candidatePath: string;
  previousGraphHash: string;
  previousReceiptHash: string;
  parentMediaSha256: string;
}

function parseEvent(
  result: CutRepairProcessResult,
  input: PrivatePictureRenderInput,
): SurgicalEvent {
  let value: unknown;
  try {
    value = JSON.parse(result.stdout.trim()) as unknown;
  } catch {
    throw new Error(
      result.stderr.trim() || "surgical picture render returned no JSON");
  }
  const row = objectValue(value, "surgical picture render event");
  if (result.code !== 0) {
    throw new Error(
      typeof row.error === "string"
        ? row.error : result.stderr.trim() || "surgical picture render failed");
  }
  exactKeys(row, EVENT_KEYS, EVENT_KEYS, "surgical picture render event");
  const dirty = uniqueStrings(row.dirtyNodeIds, "surgical dirty nodes");
  const reused = uniqueStrings(row.reusedNodeIds, "surgical reused nodes");
  if (row.status !== "render_graph_candidate_staged"
      || JSON.stringify([...dirty, ...reused].sort())
        !== JSON.stringify([...NODE_IDS].sort())
      || dirty.some((nodeId) => reused.includes(nodeId))
      || row.candidatePath !== input.candidatePath) {
    throw new Error("surgical picture render event is outside the closed lane");
  }
  return {
    graphHash: sha256(row.graphHash, "surgical graph hash"),
    receiptHash: sha256(row.receiptHash, "surgical graph receipt"),
    terminalReceiptHash: sha256(
      row.terminalReceiptHash, "surgical terminal receipt"),
    terminalReceiptPath: String(row.terminalReceiptPath),
    candidateSha256: sha256(row.candidateSha256, "surgical candidate"),
    candidatePath: row.candidatePath,
    previousGraphHash: sha256(
      row.previousGraphHash, "surgical previous graph"),
    previousReceiptHash: sha256(
      row.previousReceiptHash, "surgical previous receipt"),
    parentMediaSha256: sha256(
      row.parentMediaSha256, "surgical parent media"),
  };
}

function argumentsFor(input: PrivatePictureRenderInput): string[] {
  return [
    "--producer-dir", input.producerDir,
    "--plan", input.planPath,
    "--manifest", input.manifestPath,
    "--prepared", input.preparedPath,
    "--candidate", input.candidatePath,
    "--artifact-dir", input.artifactDir,
  ];
}

function assertObservedGraph(
  input: PrivatePictureRenderInput,
  event: SurgicalEvent,
  authority: StagedRenderGraphAuthority,
  parentRenderAuthorityHash: string,
): void {
  if (authority.graphHash !== event.graphHash
      || authority.receiptHash !== event.receiptHash
      || authority.candidateMediaHash !== event.candidateSha256
      || authority.previousGraphHash !== event.previousGraphHash
      || authority.previousReceiptHash !== event.previousReceiptHash) {
    throw new Error("surgical staged graph observation changed identity");
  }
  const graphPath = path.join(
    input.producerDir, ".render-graph-v1", "generations",
    authority.graphHash, "graph.json");
  assertCutRepairSurgicalRenderGraph({
    graph: readAuthorityJsonSync(graphPath),
    plan: input.prepared.reviewPlan,
    planContentHash: input.planContentHash,
    operation: input.prepared.operation,
    operationHash: input.prepared.operationHash,
    pictureAuthority: input.pictureAuthority,
    childTimelineMapHash: input.prepared.reviewTimelineMapHash,
    fragmentReceipt: input.prepared.fragmentReceipt,
    compositeReceipt: input.prepared.compositeReceipt,
    candidateHash: event.candidateSha256,
    parentRenderAuthorityHash,
    terminalReceiptHash: event.terminalReceiptHash,
  });
}

/** Stage only the proved dirty picture composite; never invoke a full render. */
export async function renderCutRepairPrivatePicture(
  input: PrivatePictureRenderInput,
  execute: PrivatePictureExecutor = runCutRepairPython,
  observe: PrivatePictureObserver,
): Promise<CutRepairPreparedRender> {
  const result = await execute(
    SURGICAL_TERMINAL, argumentsFor(input),
    "cut repair surgical picture render", TIMEOUT_MS);
  const event = parseEvent(result, input);
  const parentRenderAuthorityHash = verifyPrivatePictureTerminal(
    input, event);
  if (fileSha256(input.candidatePath) !== event.candidateSha256) {
    throw new Error("surgical picture candidate bytes changed");
  }
  const authority = observe({
    producerDir: input.producerDir,
    candidatePath: input.candidatePath,
    expectedCandidateHash: event.candidateSha256,
  });
  assertObservedGraph(
    input, event, authority, parentRenderAuthorityHash);
  return {
    candidatePath: input.candidatePath,
    candidateSha256: event.candidateSha256,
    graphHash: authority.graphHash,
    graphReceiptHash: authority.receiptHash,
    candidatePointerHash: authority.candidatePointerHash,
    previousGraphHash: authority.previousGraphHash,
    previousGraphReceiptHash: authority.previousReceiptHash,
  };
}
