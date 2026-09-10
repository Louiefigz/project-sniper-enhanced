import {
  enumValue,
  exactKeys,
  objectValue,
  stableId,
  stringValue,
  uniqueStrings,
} from "./validation";

export {
  parseCurrentSystemInventoryV1,
} from "./p0-inventory-contract";
export type {
  CurrentSystemInventoryV1,
} from "./p0-inventory-contract";

export interface ProductCapabilityMatrixV1 {
  schemaVersion: 1;
  asOf: string;
  completeness: "partial" | "complete";
  phaseExit: "blocked" | "passed";
  capabilities: Array<{
    capabilityId: string;
    status: "released" | "compatibility" | "unsupported" | "unqualified";
    codeEvidence: string[];
    uiEvidence: string[];
    skillEvidence: string[];
    docsEvidence: string[];
    blockingGates: string[];
  }>;
}

export interface FpsSupportMatrixV1 {
  schemaVersion: 1;
  asOf: string;
  phaseExit: "blocked" | "passed";
  rows: Array<{
    surface: "graphics-comp-catalog" | "producer-master" | "palmier-native";
    numerator: string;
    denominator: string;
    status: "measured-released" | "implemented-unqualified" | "unsupported";
    evidence: string[];
    limits: string;
  }>;
}

const TOP_KEYS = ["schemaVersion", "asOf", "completeness", "phaseExit"] as const;
function date(value: unknown, label: string): string {
  const result = stringValue(value, label, 10);
  if (!/^\d{4}-\d{2}-\d{2}$/u.test(result)) throw new Error(`${label} is not a date`);
  return result;
}
function strings(value: unknown, label: string): string[] {
  return uniqueStrings(value, label, (item, itemLabel) =>
    stringValue(item, itemLabel, 1_000));
}

function parseCapability(value: unknown, index: number) {
  const row = objectValue(value, `capabilities[${index}]`);
  const keys = [
    "capabilityId", "status", "codeEvidence", "uiEvidence", "skillEvidence",
    "docsEvidence", "blockingGates",
  ] as const;
  exactKeys(row, keys, keys, `capabilities[${index}]`);
  const result = {
    capabilityId: stableId(row.capabilityId, `capabilities[${index}].capabilityId`),
    status: enumValue(
      row.status,
      ["released", "compatibility", "unsupported", "unqualified"] as const,
      `capabilities[${index}].status`,
    ),
    codeEvidence: strings(row.codeEvidence, `capabilities[${index}].codeEvidence`),
    uiEvidence: strings(row.uiEvidence, `capabilities[${index}].uiEvidence`),
    skillEvidence: strings(row.skillEvidence, `capabilities[${index}].skillEvidence`),
    docsEvidence: strings(row.docsEvidence, `capabilities[${index}].docsEvidence`),
    blockingGates: strings(row.blockingGates, `capabilities[${index}].blockingGates`),
  };
  if (result.status === "released" && [
    result.codeEvidence,
    result.uiEvidence,
    result.skillEvidence,
    result.docsEvidence,
  ].some((evidence) => !evidence.length)) {
    throw new Error(`${result.capabilityId} lacks released evidence`);
  }
  if (result.status !== "released" && !result.blockingGates.length) {
    throw new Error(`${result.capabilityId} lacks blocking gates`);
  }
  return result;
}

export function parseProductCapabilityMatrixV1(
  value: unknown,
): ProductCapabilityMatrixV1 {
  const matrix = objectValue(value, "ProductCapabilityMatrixV1");
  exactKeys(
    matrix,
    [...TOP_KEYS, "capabilities"],
    [...TOP_KEYS, "capabilities"],
    "ProductCapabilityMatrixV1",
  );
  if (matrix.schemaVersion !== 1 || !Array.isArray(matrix.capabilities)) {
    throw new Error("ProductCapabilityMatrixV1 is malformed");
  }
  const capabilities = matrix.capabilities.map(parseCapability);
  if (new Set(capabilities.map((row) => row.capabilityId)).size
      !== capabilities.length) {
    throw new Error("capability ids repeat");
  }
  const result: ProductCapabilityMatrixV1 = {
    schemaVersion: 1,
    asOf: date(matrix.asOf, "capability matrix asOf"),
    completeness: enumValue(
      matrix.completeness,
      ["partial", "complete"] as const,
      "capability matrix completeness",
    ),
    phaseExit: enumValue(
      matrix.phaseExit,
      ["blocked", "passed"] as const,
      "capability matrix phaseExit",
    ),
    capabilities,
  };
  if (result.phaseExit === "passed" && (
    result.completeness !== "complete"
    || result.capabilities.some((row) => row.status === "unqualified")
  )) {
    throw new Error("P0 capability matrix cannot pass while incomplete or unqualified");
  }
  return result;
}

function gcd(left: bigint, right: bigint): bigint {
  let a = left;
  let b = right;
  while (b !== BigInt(0)) [a, b] = [b, a % b];
  return a;
}

function parseFpsRow(value: unknown, index: number): FpsSupportMatrixV1["rows"][number] {
  const row = objectValue(value, `fps.rows[${index}]`);
  const keys = ["surface", "numerator", "denominator", "status", "evidence", "limits"];
  exactKeys(row, keys, keys, `fps.rows[${index}]`);
  const numerator = stringValue(row.numerator, `fps.rows[${index}].numerator`, 32);
  const denominator = stringValue(row.denominator, `fps.rows[${index}].denominator`, 32);
  if (!/^[1-9][0-9]*$/u.test(numerator)
      || !/^[1-9][0-9]*$/u.test(denominator)
      || gcd(BigInt(numerator), BigInt(denominator)) !== BigInt(1)) {
    throw new Error(`fps.rows[${index}] rational must be positive and reduced`);
  }
  return {
    surface: enumValue(
      row.surface,
      ["graphics-comp-catalog", "producer-master", "palmier-native"] as const,
      `fps.rows[${index}].surface`,
    ),
    numerator,
    denominator,
    status: enumValue(
      row.status,
      ["measured-released", "implemented-unqualified", "unsupported"] as const,
      `fps.rows[${index}].status`,
    ),
    evidence: strings(row.evidence, `fps.rows[${index}].evidence`),
    limits: stringValue(row.limits, `fps.rows[${index}].limits`, 2_000),
  };
}

export function parseFpsSupportMatrixV1(value: unknown): FpsSupportMatrixV1 {
  const matrix = objectValue(value, "FpsSupportMatrixV1");
  exactKeys(
    matrix,
    ["schemaVersion", "asOf", "phaseExit", "rows"],
    ["schemaVersion", "asOf", "phaseExit", "rows"],
    "FpsSupportMatrixV1",
  );
  if (matrix.schemaVersion !== 1 || !Array.isArray(matrix.rows) || !matrix.rows.length) {
    throw new Error("FpsSupportMatrixV1 is malformed");
  }
  const rows = matrix.rows.map(parseFpsRow);
  const identities = rows.map((row) =>
    `${row.surface}:${row.numerator}/${row.denominator}`);
  if (new Set(identities).size !== identities.length) throw new Error("FPS rows repeat");
  const phaseExit = enumValue(
    matrix.phaseExit,
    ["blocked", "passed"] as const,
    "fps phaseExit",
  );
  if (phaseExit === "passed"
      && rows.some((row) => row.status === "implemented-unqualified")) {
    throw new Error("FPS phase cannot pass with unqualified rows");
  }
  return {
    schemaVersion: 1,
    asOf: date(matrix.asOf, "fps asOf"),
    phaseExit,
    rows,
  };
}
