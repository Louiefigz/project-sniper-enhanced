import { readFileSync, renameSync, rmSync, statSync, writeFileSync, type Stats } from "fs";
import { createHash, randomUUID } from "crypto";
import type { AutoEditAuthoritySnapshot } from "./auto-edit-authority-snapshot";

interface AuthorityDependencies {
  exists: (filePath: string) => boolean;
  hashFile: (filePath: string) => string | undefined;
}

interface AuthorityProof {
  authorityHash?: unknown;
  planHash?: unknown;
  inputAuthorityDigest?: unknown;
  qualityPolicyVersion?: unknown;
}

function canonicalJson(value: unknown): string {
  if (value === null) return "null";
  if (typeof value === "string") return JSON.stringify(value);
  if (typeof value === "number") {
    if (!Number.isFinite(value)
        || (Number.isInteger(value) && !Number.isSafeInteger(value))) {
      throw new Error("plan number is outside the cross-runtime domain");
    }
    return JSON.stringify(value);
  }
  if (typeof value === "boolean") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(", ")}]`;
  if (typeof value !== "object" || value === undefined) {
    throw new Error("plan value is outside the JSON domain");
  }
  const entries = Object.entries(value as Record<string, unknown>)
    .sort(([left], [right]) => left < right ? -1 : left > right ? 1 : 0)
    .map(([key, item]) => `${JSON.stringify(key)}: ${canonicalJson(item)}`);
  return `{${entries.join(", ")}}`;
}

function renderedPlanContent(plan: Record<string, unknown>): Record<string, unknown> {
  const elementTracks = new Set([
    "cutTrack", "graphicsTrack", "punchIns", "transitions", "audioGain",
    "titleCards", "brollTrack", "treatmentMap", "chapters", "sfxTrack",
  ]);
  const metadata = new Set([
    "id", "generation", "version", "sourceAnchor", "dependencies",
    "confidence", "evidence", "rationale", "reason", "semanticBeatId",
    "trigger",
  ]);
  const content = Object.fromEntries(
    Object.entries(plan).filter(([key]) => key !== "planVersion"
      && key !== "graphicsDecisions" && key !== "persistentText"
      && key !== "cutDecisions"
      && key !== "cutRepairPicturePlanAuthority" && key !== "ending"
      && key !== "transitionRationale" && key !== "treatmentMap"
      && !key.startsWith("_")),
  );
  return Object.fromEntries(Object.entries(content).map(([lane, value]) => {
    if (!elementTracks.has(lane) || !Array.isArray(value)) return [lane, value];
    const rows = value.map((row) => {
      if (!row || typeof row !== "object" || Array.isArray(row)) return row;
      return Object.fromEntries(Object.entries(row).filter(
        ([key]) => !metadata.has(key)));
    });
    return [lane, rows];
  }));
}

/** Exact object-value counterpart of fingerprints.py plan_content_hash. */
export function planObjectContentHash(value: unknown): string | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
  try {
    const canonical = canonicalJson(
      renderedPlanContent(value as Record<string, unknown>));
    return createHash("sha256").update(canonical).digest("hex");
  } catch {
    return undefined;
  }
}

/** Exact TypeScript counterpart of fingerprints.py plan_content_hash. */
export function planContentHash(planPath: string): string | undefined {
  try {
    return planObjectContentHash(JSON.parse(readFileSync(planPath, "utf8")));
  } catch {
    return undefined;
  }
}

function readProof(finalPath: string): AuthorityProof | undefined {
  try {
    return JSON.parse(readFileSync(`${finalPath}.assembled.json`, "utf8")) as AuthorityProof;
  } catch {
    return undefined;
  }
}

export function verifiedAuthorityHash(
  finalPath: string,
  expectedPlanHash: string | undefined,
  deps: AuthorityDependencies,
  expectedAuthorityDigest?: string,
): string | undefined {
  const proofPath = `${finalPath}.assembled.json`;
  if (!expectedPlanHash || !deps.exists(finalPath) || !deps.exists(proofPath)) return undefined;
  if (statSync(finalPath).size <= 0) return undefined;
  const proof = readProof(finalPath);
  const actual = deps.hashFile(finalPath);
  const authorityMatches = !expectedAuthorityDigest
    || (proof?.inputAuthorityDigest === expectedAuthorityDigest && proof.qualityPolicyVersion === 1);
  return proof?.planHash === expectedPlanHash && proof.authorityHash === actual && authorityMatches
    ? actual
    : undefined;
}

/** Add the controller's full input+pipeline authority to an already-verified assembly proof. */
export function bindAuthorityProof(
  finalPath: string,
  snapshot: AutoEditAuthoritySnapshot,
  deps: AuthorityDependencies,
): void {
  const proofPath = `${finalPath}.assembled.json`;
  const proof = readProof(finalPath);
  const actual = deps.hashFile(finalPath);
  if (!proof || proof.planHash !== snapshot.planContentHash || proof.authorityHash !== actual) {
    throw new Error("cannot bind input authority to an unverified assembly proof");
  }
  const temporary = `${proofPath}.${randomUUID()}.tmp`;
  try {
    writeFileSync(temporary, `${JSON.stringify({
      ...proof,
      inputAuthorityDigest: snapshot.digest,
      qualityPolicyVersion: snapshot.qualityPolicyVersion,
    }, null, 2)}\n`, { flag: "wx", mode: 0o600 });
    renameSync(temporary, proofPath);
  } finally {
    rmSync(temporary, { force: true });
  }
}

export function requireFreshAuthority(
  finalPath: string,
  expectedPlanHash: string | undefined,
  previousProof: Pick<Stats, "ino" | "mtimeMs"> | null,
  deps: AuthorityDependencies,
): string {
  const proofPath = `${finalPath}.assembled.json`;
  if (!deps.exists(proofPath)) throw new Error("assemble exited 0 without writing fresh final.mp4 authority proof");
  const current = statSync(proofPath);
  const replaced = !previousProof || current.ino !== previousProof.ino
    || current.mtimeMs > previousProof.mtimeMs;
  if (!replaced) throw new Error("assemble reused stale final.mp4 authority proof");
  const proof = readProof(finalPath);
  if (!expectedPlanHash || proof?.planHash !== expectedPlanHash) {
    throw new Error("assembled final.mp4 authority proof belongs to a different edit plan");
  }
  const verified = verifiedAuthorityHash(finalPath, expectedPlanHash, deps);
  if (!verified) throw new Error("assembled final.mp4 bytes do not match their authority proof");
  return verified;
}
