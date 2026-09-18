import {
  enumValue,
  exactKeys,
  objectValue,
  stableId,
  stringValue,
  uniqueStrings,
} from "./validation";

const DISPOSITIONS = [
  "path-owner",
  "reader",
  "writer",
  "reader-writer",
  "launcher",
  "non-authority",
] as const;

export interface CurrentSystemInventoryArtifactV1 {
  artifactId: string;
  pathPattern: string;
  owner: string;
  authority: "canonical" | "receipt" | "derived" | "compatibility-shadow";
  readers: string[];
  writers: string[];
  promotionPoint: string;
  fingerprintInputs: string[];
  durability: string;
  disposition: "reuse" | "extend" | "adapter" | "replace" | "retain-shadow";
  parityFixture: string;
  removalCondition: string;
  authorityPathTokens: string[];
  callSiteDispositions: Record<string, typeof DISPOSITIONS[number]>;
}

export interface CurrentSystemInventoryV1 {
  schemaVersion: 1;
  asOf: string;
  completeness: "partial" | "complete";
  phaseExit: "blocked" | "passed";
  inventoryGaps: string[];
  baseline: {
    status: "required-unmeasured" | "measured";
    requiredFixtures: string[];
    evidencePaths: string[];
  };
  callSiteAudit: {
    roots: string[];
    extensions: string[];
    excludedPathSegments: string[];
  };
  authorityDiscovery: {
    literalPrefixes: string[];
    artifactBindings: Record<string, string>;
    backlog: Record<string, string>;
    pathBoundaryEvidence: string;
    persistenceDispositionEvidence: string;
  };
  artifacts: CurrentSystemInventoryArtifactV1[];
}

function strings(value: unknown, label: string): string[] {
  return uniqueStrings(value, label, (item, itemLabel) =>
    stringValue(item, itemLabel, 2_000));
}

function parseCallSites(
  value: unknown,
  label: string,
): Record<string, typeof DISPOSITIONS[number]> {
  const mapping = objectValue(value, label);
  const result: Record<string, typeof DISPOSITIONS[number]> = {};
  for (const [filePath, disposition] of Object.entries(mapping)) {
    stringValue(filePath, `${label} path`, 2_000);
    result[filePath] = enumValue(disposition, DISPOSITIONS, `${label}.${filePath}`);
  }
  if (!Object.keys(result).length) throw new Error(`${label} is empty`);
  return result;
}

function parseArtifact(
  value: unknown,
  index: number,
): CurrentSystemInventoryArtifactV1 {
  const label = `inventory.artifacts[${index}]`;
  const row = objectValue(value, label);
  const keys = [
    "artifactId", "pathPattern", "owner", "authority", "readers", "writers",
    "promotionPoint", "fingerprintInputs", "durability", "disposition",
    "parityFixture", "removalCondition", "authorityPathTokens",
    "callSiteDispositions",
  ] as const;
  exactKeys(row, keys, keys, label);
  const readers = strings(row.readers, `${label}.readers`);
  const writers = strings(row.writers, `${label}.writers`);
  if (!readers.length || !writers.length) {
    throw new Error("inventory artifacts require readers and writers");
  }
  return {
    artifactId: stableId(row.artifactId, `${label}.artifactId`),
    pathPattern: stringValue(row.pathPattern, `${label}.pathPattern`, 2_000),
    owner: stringValue(row.owner, `${label}.owner`, 2_000),
    authority: enumValue(
      row.authority,
      ["canonical", "receipt", "derived", "compatibility-shadow"] as const,
      `${label}.authority`,
    ),
    readers,
    writers,
    promotionPoint: stringValue(
      row.promotionPoint, `${label}.promotionPoint`, 2_000),
    fingerprintInputs: strings(
      row.fingerprintInputs, `${label}.fingerprintInputs`),
    durability: stringValue(row.durability, `${label}.durability`, 2_000),
    disposition: enumValue(
      row.disposition,
      ["reuse", "extend", "adapter", "replace", "retain-shadow"] as const,
      `${label}.disposition`,
    ),
    parityFixture: stringValue(
      row.parityFixture, `${label}.parityFixture`, 2_000),
    removalCondition: stringValue(
      row.removalCondition, `${label}.removalCondition`, 2_000),
    authorityPathTokens: strings(
      row.authorityPathTokens, `${label}.authorityPathTokens`),
    callSiteDispositions: parseCallSites(
      row.callSiteDispositions, `${label}.callSiteDispositions`),
  };
}

function parseBaseline(value: unknown): CurrentSystemInventoryV1["baseline"] {
  const baseline = objectValue(value, "inventory.baseline");
  const keys = ["status", "requiredFixtures", "evidencePaths"] as const;
  exactKeys(baseline, keys, keys, "inventory.baseline");
  const result = {
    status: enumValue(
      baseline.status,
      ["required-unmeasured", "measured"] as const,
      "inventory.baseline.status",
    ),
    requiredFixtures: strings(baseline.requiredFixtures, "requiredFixtures"),
    evidencePaths: strings(baseline.evidencePaths, "evidencePaths"),
  };
  if (result.requiredFixtures.length < 2
      || (result.status === "measured"
        && result.evidencePaths.length !== result.requiredFixtures.length)) {
    throw new Error("measured baseline must name every required fixture trace");
  }
  return result;
}

function parseAudit(value: unknown): CurrentSystemInventoryV1["callSiteAudit"] {
  const audit = objectValue(value, "inventory.callSiteAudit");
  const keys = ["roots", "extensions", "excludedPathSegments"] as const;
  exactKeys(audit, keys, keys, "inventory.callSiteAudit");
  const result = {
    roots: strings(audit.roots, "inventory.callSiteAudit.roots"),
    extensions: strings(audit.extensions, "inventory.callSiteAudit.extensions"),
    excludedPathSegments: strings(
      audit.excludedPathSegments,
      "inventory.callSiteAudit.excludedPathSegments",
    ),
  };
  if (!result.roots.length || !result.extensions.length) {
    throw new Error("inventory call-site audit scope is empty");
  }
  return result;
}

function parseStringMap(
  value: unknown,
  label: string,
  allowEmpty = false,
): Record<string, string> {
  const mapping = objectValue(value, label);
  const result: Record<string, string> = {};
  for (const [key, item] of Object.entries(mapping)) {
    result[stringValue(key, `${label} key`, 2_000)] =
      stringValue(item, `${label}.${key}`, 2_000);
  }
  if (!allowEmpty && !Object.keys(result).length) {
    throw new Error(`${label} is empty`);
  }
  return result;
}

function parseDiscovery(
  value: unknown,
): CurrentSystemInventoryV1["authorityDiscovery"] {
  const discovery = objectValue(value, "inventory.authorityDiscovery");
  const keys = [
    "literalPrefixes", "artifactBindings", "backlog", "pathBoundaryEvidence",
    "persistenceDispositionEvidence",
  ] as const;
  exactKeys(discovery, keys, keys, "inventory.authorityDiscovery");
  const result = {
    literalPrefixes: strings(
      discovery.literalPrefixes, "authorityDiscovery.literalPrefixes"),
    artifactBindings: parseStringMap(
      discovery.artifactBindings, "authorityDiscovery.artifactBindings"),
    backlog: parseStringMap(
      discovery.backlog, "authorityDiscovery.backlog", true),
    pathBoundaryEvidence: stringValue(
      discovery.pathBoundaryEvidence,
      "authorityDiscovery.pathBoundaryEvidence",
      2_000,
    ),
    persistenceDispositionEvidence: stringValue(
      discovery.persistenceDispositionEvidence,
      "authorityDiscovery.persistenceDispositionEvidence",
      2_000,
    ),
  };
  const overlap = Object.keys(result.artifactBindings)
    .filter((token) => token in result.backlog);
  if (overlap.length) throw new Error("authority discovery token repeats");
  return result;
}

function verifyDiscoveryBindings(result: CurrentSystemInventoryV1): void {
  const artifactIds = new Set(result.artifacts.map((row) => row.artifactId));
  const absent = Object.values(result.authorityDiscovery.artifactBindings)
    .filter((artifactId) => !artifactIds.has(artifactId));
  if (absent.length) {
    throw new Error("authority discovery binding names an absent artifact");
  }
  const bypassed = Object.entries(
    result.authorityDiscovery.artifactBindings,
  ).filter(([token, artifactId]) => {
    const artifact = result.artifacts.find((row) => row.artifactId === artifactId);
    return !artifact?.authorityPathTokens.some(
      (searchToken) => searchToken.replace(/^["'`]|["'`]$/gu, "") === token,
    );
  });
  if (bypassed.length) {
    throw new Error("authority discovery binding bypasses artifact tokens");
  }
}

function verifyInventoryExit(result: CurrentSystemInventoryV1): void {
  if (!/^\d{4}-\d{2}-\d{2}$/u.test(result.asOf)
      || result.baseline.requiredFixtures.length < 2) {
    throw new Error("P0 inventory date or baseline fixtures are invalid");
  }
  if ((result.completeness === "complete") === Boolean(result.inventoryGaps.length)) {
    throw new Error("inventory completeness and inventory gaps disagree");
  }
  if (result.phaseExit === "passed"
      && (result.completeness !== "complete"
        || result.baseline.status !== "measured"
        || !result.baseline.evidencePaths.length)) {
    throw new Error("P0 cannot pass without complete inventory and measured baseline");
  }
}

export function parseCurrentSystemInventoryV1(
  value: unknown,
): CurrentSystemInventoryV1 {
  const inventory = objectValue(value, "CurrentSystemInventoryV1");
  const keys = [
    "schemaVersion", "asOf", "completeness", "phaseExit", "inventoryGaps",
    "baseline", "callSiteAudit", "authorityDiscovery", "artifacts",
  ] as const;
  exactKeys(inventory, keys, keys, "CurrentSystemInventoryV1");
  if (inventory.schemaVersion !== 1 || !Array.isArray(inventory.artifacts)) {
    throw new Error("CurrentSystemInventoryV1 version or artifacts are invalid");
  }
  const artifacts = inventory.artifacts.map(parseArtifact);
  const ids = artifacts.map((row) => row.artifactId);
  if (!artifacts.length || new Set(ids).size !== ids.length) {
    throw new Error("inventory artifacts are empty or repeat");
  }
  const result: CurrentSystemInventoryV1 = {
    schemaVersion: 1,
    asOf: stringValue(inventory.asOf, "inventory.asOf", 10),
    completeness: enumValue(
      inventory.completeness,
      ["partial", "complete"] as const,
      "inventory.completeness",
    ),
    phaseExit: enumValue(
      inventory.phaseExit,
      ["blocked", "passed"] as const,
      "inventory.phaseExit",
    ),
    inventoryGaps: strings(inventory.inventoryGaps, "inventory.inventoryGaps"),
    baseline: parseBaseline(inventory.baseline),
    callSiteAudit: parseAudit(inventory.callSiteAudit),
    authorityDiscovery: parseDiscovery(inventory.authorityDiscovery),
    artifacts,
  };
  verifyDiscoveryBindings(result);
  verifyInventoryExit(result);
  return result;
}
