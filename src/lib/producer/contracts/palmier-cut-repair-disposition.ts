import { canonicalJsonSha256 } from "@/lib/server/auto-edit-hash";
import { parsePositiveRationalV1 } from "./positive-rational";
import {
  parseCutRepairRetimeV1,
  type CutRepairRetimeV1,
} from "./cut-repair-retime";
import {
  exactKeys,
  objectValue,
  sha256,
  stableId,
  stringValue,
} from "./validation";

interface PalmierCutRepairSkippedV1 {
  schemaVersion: 1;
  kind: "palmier-cut-repair-disposition";
  selected: false;
  operationHash: string;
  nativeStatus: "skipped";
  deliveryDisposition: "local-exact-only";
  reason: string;
}

interface PalmierExpectedCutV1 {
  sourceId: string;
  source: [number, number];
  frames: [number, number];
  speed: number;
}

interface PalmierCutRepairSelectedV1 {
  schemaVersion: 1;
  kind: "palmier-cut-repair-disposition";
  selected: true;
  operationHash: string;
  nativeStatus: "unsupported" | "frame-exact-unqualified";
  deliveryDisposition: "baked-exact-master";
  sampleExact: false;
  repairSpeed: { numerator: string; denominator: string };
  repairRetime: CutRepairRetimeV1;
  reason: string;
  requiresRepairFragmentImport: true;
  projectionHash: string;
  expectedCuts?: PalmierExpectedCutV1[];
  expectedTotalFrames?: number;
}

export type PalmierCutRepairDispositionV1 =
  | PalmierCutRepairSkippedV1
  | PalmierCutRepairSelectedV1;

const BASE = [
  "schemaVersion", "kind", "selected", "operationHash",
  "nativeStatus", "deliveryDisposition", "reason",
] as const;
const SELECTED = [
  ...BASE, "sampleExact", "repairSpeed", "requiresRepairFragmentImport",
  "repairRetime", "projectionHash",
] as const;

function finite(value: unknown, label: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`${label} must be finite`);
  }
  return value;
}

function pair(
  value: unknown,
  label: string,
  integer: boolean,
): [number, number] {
  if (!Array.isArray(value) || value.length !== 2) {
    throw new Error(`${label} must contain two values`);
  }
  const result: [number, number] = [
    finite(value[0], `${label}[0]`),
    finite(value[1], `${label}[1]`),
  ];
  if (integer && result.some((item) => !Number.isSafeInteger(item))) {
    throw new Error(`${label} must contain safe integers`);
  }
  if (result[0] < 0 || result[1] <= result[0]) {
    throw new Error(`${label} must be an increasing non-negative range`);
  }
  return result;
}

function expectedCut(
  value: unknown,
  position: number,
): PalmierExpectedCutV1 {
  const label = `Palmier expectedCuts[${position}]`;
  const row = objectValue(value, label);
  const keys = ["sourceId", "source", "frames", "speed"] as const;
  exactKeys(row, keys, keys, label);
  const speed = finite(row.speed, `${label}.speed`);
  if (speed <= 0) throw new Error(`${label}.speed must be positive`);
  return {
    sourceId: stableId(row.sourceId, `${label}.sourceId`),
    source: pair(row.source, `${label}.source`, false),
    frames: pair(row.frames, `${label}.frames`, true),
    speed,
  };
}

function header(
  row: Record<string, unknown>,
): Pick<
  PalmierCutRepairSkippedV1,
  "schemaVersion" | "kind" | "operationHash" | "reason"
> {
  if (row.schemaVersion !== 1
      || row.kind !== "palmier-cut-repair-disposition") {
    throw new Error("Palmier cut repair disposition is malformed");
  }
  return {
    schemaVersion: 1,
    kind: "palmier-cut-repair-disposition",
    operationHash: sha256(
      row.operationHash, "Palmier disposition operation"),
    reason: stringValue(row.reason, "Palmier disposition reason", 500),
  };
}

function parseSkipped(
  row: Record<string, unknown>,
): PalmierCutRepairSkippedV1 {
  exactKeys(row, BASE, BASE, "Palmier skipped cut repair disposition");
  if (row.nativeStatus !== "skipped"
      || row.deliveryDisposition !== "local-exact-only") {
    throw new Error("Palmier skipped disposition is inconsistent");
  }
  return {
    ...header(row),
    selected: false,
    nativeStatus: "skipped",
    deliveryDisposition: "local-exact-only",
  };
}

function selectedRetime(
  row: Record<string, unknown>,
): Pick<PalmierCutRepairSelectedV1, "repairSpeed" | "repairRetime"> {
  const repairSpeed = parsePositiveRationalV1(row.repairSpeed);
  const repairRetime = parseCutRepairRetimeV1(row.repairRetime);
  if (canonicalJsonSha256(repairSpeed)
      !== canonicalJsonSha256(repairRetime.requestedSpeed)) {
    throw new Error("Palmier repair speed and renderer retime disagree");
  }
  return { repairSpeed, repairRetime };
}

function parseSelected(
  row: Record<string, unknown>,
): PalmierCutRepairSelectedV1 {
  const qualified = row.nativeStatus === "frame-exact-unqualified";
  const keys = qualified
    ? [...SELECTED, "expectedCuts", "expectedTotalFrames"] : SELECTED;
  exactKeys(row, keys, keys, "Palmier selected cut repair disposition");
  if ((!qualified && row.nativeStatus !== "unsupported")
      || row.deliveryDisposition !== "baked-exact-master"
      || row.sampleExact !== false
      || row.requiresRepairFragmentImport !== true) {
    throw new Error("Palmier selected disposition is inconsistent");
  }
  const cuts = qualified && Array.isArray(row.expectedCuts)
    ? row.expectedCuts.map(expectedCut) : undefined;
  const total = qualified ? finite(
    row.expectedTotalFrames, "Palmier expectedTotalFrames") : undefined;
  if (qualified && (!cuts?.length || !Number.isSafeInteger(total)
      || total! < 1 || cuts.at(-1)!.frames[1] !== total)) {
    throw new Error("Palmier expected cut coverage is malformed");
  }
  const projectionHash = sha256(
    row.projectionHash, "Palmier disposition projection");
  const payload = { ...row };
  delete payload.projectionHash;
  if (canonicalJsonSha256(payload) !== projectionHash) {
    throw new Error("Palmier cut repair projection hash is stale");
  }
  const retime = selectedRetime(row);
  return {
    ...header(row),
    selected: true,
    nativeStatus: qualified
      ? "frame-exact-unqualified" : "unsupported",
    deliveryDisposition: "baked-exact-master",
    sampleExact: false,
    ...retime,
    requiresRepairFragmentImport: true,
    projectionHash,
    ...(qualified ? {
      expectedCuts: cuts,
      expectedTotalFrames: total,
    } : {}),
  };
}

/** Parse the honest local-only or baked-exact Palmier repair disposition. */
export function parsePalmierCutRepairDispositionV1(
  value: unknown,
): PalmierCutRepairDispositionV1 {
  const row = objectValue(value, "PalmierCutRepairDispositionV1");
  return row.selected === false ? parseSkipped(row) : parseSelected(row);
}
