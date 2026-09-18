import {
  existsSync,
  lstatSync,
  readFileSync,
  realpathSync,
} from "node:fs";
import path from "node:path";
import {
  atomicCreateJsonSync,
  atomicWriteJsonSync,
} from "./atomic-file";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import {
  ensureDurableDirectory,
  syncFileAndParent,
  type PromotionDurabilityHooks,
} from "./candidate-promotion-fs";
import {
  parseCandidatePromotionIntentV1,
  promotionTopologyHash,
  type CandidatePromotionIntentV1,
  type PromotionTopology,
} from "./candidate-promotion-intent";

function within(root: string, candidate: string): boolean {
  const relative = path.relative(root, candidate);
  return relative === "" || (!relative.startsWith("..")
    && !path.isAbsolute(relative));
}

function assertRealTraversal(root: string, candidate: string): void {
  const canonicalRoot = realpathSync(root);
  const relative = path.relative(root, candidate);
  let lexical = root;
  let canonical = canonicalRoot;
  for (const part of relative.split(path.sep).filter(Boolean)) {
    lexical = path.join(lexical, part);
    canonical = path.join(canonical, part);
    let stat;
    try {
      stat = lstatSync(lexical);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") return;
      throw error;
    }
    if (stat.isSymbolicLink()) {
      throw new Error(`candidate promotion path has symlink traversal: ${lexical}`);
    }
    if (realpathSync(lexical) !== canonical) {
      throw new Error(`candidate promotion path escapes real scope: ${lexical}`);
    }
  }
}

function overlaps(left: string, right: string): boolean {
  const relation = path.relative(left, right);
  const reverse = path.relative(right, left);
  return relation === "" || (!relation.startsWith("..")
    && !path.isAbsolute(relation)) || (!reverse.startsWith("..")
      && !path.isAbsolute(reverse));
}

function payloadPaths(topology: PromotionTopology): {
  sources: string[];
  destinations: string[];
} {
  return {
    sources: [
      ...topology.moves.map((row) => row.source),
      ...topology.copies.map((row) => row.source),
    ].map((item) => path.resolve(item)),
    destinations: [
      ...topology.moves.map((row) => row.destination),
      ...topology.copies.map((row) => row.destination),
      ...topology.mutablePaths,
    ].map((item) => path.resolve(item)),
  };
}

function assertPayloadAliases(topology: PromotionTopology): void {
  const payload = payloadPaths(topology);
  if (new Set(payload.destinations).size !== payload.destinations.length) {
    throw new Error("candidate promotion destinations must be unique");
  }
  if (payload.sources.some((source) =>
    payload.destinations.some((destination) =>
      overlaps(source, destination)))) {
    throw new Error(
      "candidate promotion source/destination overlap is unsafe");
  }
  for (let index = 0; index < payload.destinations.length; index += 1) {
    const current = payload.destinations[index]!;
    if (payload.destinations.slice(index + 1).some(
      (candidate) => overlaps(current, candidate))) {
      throw new Error("candidate promotion destinations cannot be nested");
    }
  }
}

function assertControlIsolation(
  topology: PromotionTopology,
  root: string,
): void {
  const recovery = path.resolve(topology.recoveryRoot);
  const reconciliation = path.resolve(topology.reconciliationPath);
  const terminal = promotionTerminalPath(topology);
  if (recovery === root || !within(root, recovery)) {
    throw new Error("candidate promotion recovery root must be a descendant");
  }
  const controls = [recovery, reconciliation, terminal];
  const payload = payloadPaths(topology);
  if (!controls.every((item) => within(root, item))
      || controls.some((control, index) =>
        controls.slice(index + 1).some((other) => overlaps(control, other)))
      || controls.some((control) =>
        [...payload.sources, ...payload.destinations].some(
          (item) => overlaps(control, item)))) {
    throw new Error("candidate promotion control paths overlap payload state");
  }
}

export function assertPromotionTopology(topology: PromotionTopology): void {
  const root = path.resolve(topology.scopeRoot);
  const rootStat = lstatSync(root);
  if (!rootStat.isDirectory() || rootStat.isSymbolicLink()) {
    throw new Error("candidate promotion scope must be one real directory");
  }
  assertPayloadAliases(topology);
  assertControlIsolation(topology, root);
  const payload = payloadPaths(topology);
  const paths = [
    topology.recoveryRoot,
    topology.reconciliationPath,
    promotionTerminalPath(topology),
    ...payload.sources,
    ...payload.destinations,
  ].map((item) => path.resolve(item));
  if (!paths.every((item) => within(root, item))) {
    throw new Error("candidate promotion topology escapes its project root");
  }
  paths.forEach((item) => assertRealTraversal(root, item));
}

function expectedRows(topology: PromotionTopology): Array<{
  kind: string;
  source: string | null;
  missingSource: string | null;
  destination: string;
}> {
  return [
    ...topology.moves.map((row) => ({
      kind: "move", ...row, missingSource: row.missingSource ?? "reject",
    })),
    ...topology.copies.map((row) => ({
      kind: "copy", ...row, missingSource: row.missingSource ?? "reject",
    })),
    ...topology.mutablePaths.map((destination) => ({
      kind: "mutable", source: null, missingSource: null, destination,
    })),
  ];
}

function assertIntentIdentity(
  topology: PromotionTopology,
  intent: CandidatePromotionIntentV1,
): void {
  const expectedRecovery = path.join(
    path.resolve(topology.recoveryRoot),
    `promotion-${topology.transactionId}`,
  );
  const expected = expectedRows(topology).map((row, index) => ({
    ...row,
    source: row.source ? path.resolve(row.source) : null,
    destination: path.resolve(row.destination),
    backup: path.join(expectedRecovery, `prior-${index}`),
    temporary: path.join(
      path.dirname(path.resolve(row.destination)),
      `.promotion-${path.basename(expectedRecovery)}-${index}.tmp`,
    ),
  }));
  const observed = intent.entries.map((row) => ({
    kind: row.kind,
    source: row.source,
    missingSource: row.missingSource,
    destination: row.destination,
    backup: row.backup,
    temporary: row.temporary,
  }));
  const normalizedObserved = observed.map((row) => ({
    ...row,
    backup: row.backup ?? expected.find((item) =>
      item.kind === row.kind && item.source === row.source
      && item.destination === row.destination)?.backup,
  }));
  if (intent.transactionId !== topology.transactionId
      || intent.topologyHash !== promotionTopologyHash(topology)
      || intent.recoveryDirectory !== expectedRecovery
      || canonicalJsonSha256(normalizedObserved)
        !== canonicalJsonSha256(expected)) {
    throw new Error(
      "candidate promotion durable intent is stale or foreign; "
        + "manual reconciliation required",
    );
  }
}

function readPromotionIntentAt(
  topology: PromotionTopology,
  filePath: string,
): CandidatePromotionIntentV1 {
  let intent: CandidatePromotionIntentV1;
  try {
    intent = parseCandidatePromotionIntentV1(
      JSON.parse(readFileSync(filePath, "utf8")),
    );
  } catch (error) {
    throw new Error(
      "candidate promotion has torn or malformed durable intent; "
        + "manual reconciliation required",
      { cause: error },
    );
  }
  assertIntentIdentity(topology, intent);
  return intent;
}

export function readPromotionIntent(
  topology: PromotionTopology,
): CandidatePromotionIntentV1 {
  return readPromotionIntentAt(topology, topology.reconciliationPath);
}

export function promotionTerminalPath(topology: PromotionTopology): string {
  return path.join(
    path.dirname(topology.recoveryRoot),
    "promotion-commits",
    `committed-${topology.transactionId}.json`,
  );
}

export function readPromotionTerminal(
  topology: PromotionTopology,
): CandidatePromotionIntentV1 | null {
  const terminal = promotionTerminalPath(topology);
  if (!existsSync(terminal)) return null;
  const intent = readPromotionIntentAt(topology, terminal);
  if (intent.phase !== "committed") {
    throw new Error("candidate promotion terminal is not committed");
  }
  return intent;
}

export function publishPromotionTerminal(
  topology: PromotionTopology,
  intent: CandidatePromotionIntentV1,
  durabilityHooks: PromotionDurabilityHooks = {},
): void {
  const terminal = promotionTerminalPath(topology);
  ensureDurableDirectory(path.dirname(terminal), topology.scopeRoot);
  if (existsSync(terminal)) {
    const prior = readPromotionIntentAt(topology, terminal);
    if (canonicalJsonSha256(prior) !== canonicalJsonSha256(intent)) {
      throw new Error("candidate promotion terminal conflicts");
    }
    syncFileAndParent(terminal, durabilityHooks);
    return;
  }
  atomicCreateJsonSync(terminal, intent);
}

export function blockPromotionReconciliation(
  topology: PromotionTopology,
  intent: CandidatePromotionIntentV1,
  failure: unknown,
): never {
  const message = failure instanceof Error ? failure.message : String(failure);
  atomicWriteJsonSync(topology.reconciliationPath, {
    ...intent,
    phase: "reconciliation-required",
    failures: [...intent.failures, message],
  });
  throw new Error(
    `candidate promotion requires reconciliation: ${message}`,
    { cause: failure },
  );
}
