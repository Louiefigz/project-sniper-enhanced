import {
  enumValue,
  exactKeys,
  objectValue,
  stableId,
  stringValue,
  uniqueStrings,
} from "./validation";

export interface LegacyRegressionGateV1 {
  gateId: string;
  lessonIds: string[];
  sourceDocuments: string[];
  ownerPhases: Array<"P0" | "P1" | "P2" | "P3" | "P4" | "P5">;
  classification: "blocking" | "diagnostic" | "approved-approximation";
  implementationStatus: "enforced" | "blocked";
  enforcingCode: string[];
  fixtures: Array<{ path: string; expected: string }>;
  evidenceArtifacts: string[];
  receiptBindings: string[];
  knownGap: string;
}

export interface LegacyRegressionGateRegistryV1 {
  schemaVersion: 1;
  asOf: string;
  completeness: "complete";
  gates: LegacyRegressionGateV1[];
}

const PHASES = ["P0", "P1", "P2", "P3", "P4", "P5"] as const;
const GATE_KEYS = [
  "gateId",
  "lessonIds",
  "sourceDocuments",
  "ownerPhases",
  "classification",
  "implementationStatus",
  "enforcingCode",
  "fixtures",
  "evidenceArtifacts",
  "receiptBindings",
  "knownGap",
] as const;

function strings(value: unknown, label: string): string[] {
  return uniqueStrings(value, label, (item, itemLabel) =>
    stringValue(item, itemLabel, 2_000));
}

function fixture(value: unknown, index: number, gateIndex: number) {
  const label = `gates[${gateIndex}].fixtures[${index}]`;
  const row = objectValue(value, label);
  exactKeys(row, ["path", "expected"], ["path", "expected"], label);
  return {
    path: stringValue(row.path, `${label}.path`, 2_000),
    expected: stringValue(row.expected, `${label}.expected`, 4_000),
  };
}

function phases(value: unknown, label: string): LegacyRegressionGateV1["ownerPhases"] {
  if (!Array.isArray(value) || !value.length) {
    throw new Error(`${label} must name at least one owner`);
  }
  const parsed = value.map((item, index) =>
    enumValue(item, PHASES, `${label}[${index}]`));
  if (new Set(parsed).size !== parsed.length) {
    throw new Error(`${label} must contain unique owners`);
  }
  return parsed;
}

function parseGate(value: unknown, index: number): LegacyRegressionGateV1 {
  const label = `gates[${index}]`;
  const row = objectValue(value, label);
  exactKeys(row, GATE_KEYS, GATE_KEYS, label);
  if (!Array.isArray(row.fixtures) || !row.fixtures.length) {
    throw new Error(`${label} must name at least one fixture`);
  }
  const gate = {
    gateId: stableId(row.gateId, `${label}.gateId`),
    lessonIds: strings(row.lessonIds, `${label}.lessonIds`),
    sourceDocuments: strings(row.sourceDocuments, `${label}.sourceDocuments`),
    ownerPhases: phases(row.ownerPhases, `${label}.ownerPhases`),
    classification: enumValue(
      row.classification,
      ["blocking", "diagnostic", "approved-approximation"] as const,
      `${label}.classification`,
    ),
    implementationStatus: enumValue(
      row.implementationStatus,
      ["enforced", "blocked"] as const,
      `${label}.implementationStatus`,
    ),
    enforcingCode: strings(row.enforcingCode, `${label}.enforcingCode`),
    fixtures: row.fixtures.map((item, fixtureIndex) =>
      fixture(item, fixtureIndex, index)),
    evidenceArtifacts: strings(row.evidenceArtifacts, `${label}.evidenceArtifacts`),
    receiptBindings: strings(row.receiptBindings, `${label}.receiptBindings`),
    knownGap: stringValue(row.knownGap, `${label}.knownGap`, 4_000),
  };
  validateGateEvidence(gate, label);
  return gate;
}

function validateGateEvidence(gate: LegacyRegressionGateV1, label: string): void {
  if (!gate.lessonIds.length || !gate.sourceDocuments.length) {
    throw new Error(`${label} must trace a lesson and source document`);
  }
  if (!gate.enforcingCode.length || !gate.evidenceArtifacts.length) {
    throw new Error(`${label} must name current code and evidence`);
  }
  if (gate.implementationStatus === "enforced" && !gate.receiptBindings.length) {
    throw new Error(`${label} enforced status requires a receipt binding`);
  }
  if (gate.implementationStatus === "blocked" && gate.knownGap === "none") {
    throw new Error(`${label} blocked status requires an exact known gap`);
  }
  if (gate.implementationStatus === "enforced" && gate.knownGap !== "none") {
    throw new Error(`${label} enforced status cannot retain a known gap`);
  }
}

export function parseLegacyRegressionGateRegistryV1(
  value: unknown,
): LegacyRegressionGateRegistryV1 {
  const row = objectValue(value, "LegacyRegressionGateRegistryV1");
  const keys = ["schemaVersion", "asOf", "completeness", "gates"] as const;
  exactKeys(row, keys, keys, "LegacyRegressionGateRegistryV1");
  if (row.schemaVersion !== 1 || row.completeness !== "complete"
      || !Array.isArray(row.gates) || !row.gates.length) {
    throw new Error("LegacyRegressionGateRegistryV1 is malformed");
  }
  const asOf = stringValue(row.asOf, "legacy gate registry asOf", 10);
  if (!/^\d{4}-\d{2}-\d{2}$/u.test(asOf)) {
    throw new Error("legacy gate registry asOf is not a date");
  }
  const gates = row.gates.map(parseGate);
  if (new Set(gates.map((gate) => gate.gateId)).size !== gates.length) {
    throw new Error("legacy regression gate ids repeat");
  }
  return { schemaVersion: 1, asOf, completeness: "complete", gates };
}
