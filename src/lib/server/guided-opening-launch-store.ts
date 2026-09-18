import path from "node:path";
import { lstatSync, realpathSync, accessSync, constants } from "node:fs";
import { exactKeys, objectValue, sha256, uuid } from "@/lib/producer/contracts/validation";
import type { PrepareGuidedOpeningV1 } from "@/lib/producer/contracts/guided-opening-v1";
import { parsePrepareGuidedOpeningRequest, type PrepareGuidedOpeningV2 } from "@/lib/producer/contracts/guided-source-color-v1";
import { readCutPreviewObject, assertCutPreviewDirectory } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { atomicCreateFileSync } from "./atomic-file";
import { canonicalJson, canonicalJsonSha256 } from "./auto-edit-hash";
import { humanCutDirectory } from "./human-cut-acceptance-store";
import { strictGuidedTimestamp } from "./guided-cut-v2-store";
import { captureProcessIdentity, type ProcessIdentity } from "./process-liveness";
import { parseOpeningClockHandoff, type OpeningClockHandoff } from "./opening-handoff-clock";
import { pinnedProposalFile } from "./guided-proposal-evidence";
import type { OpeningReadiness } from "./guided-opening-authority";
import { GUIDED_SOURCE_COLOR_TS_FILES } from "./guided-source-color-staging";

const CONTROLLER_FILES = ["guided-opening-launch-store.ts", "guided-opening-launcher.ts", "guided-opening-controller.ts",
  "guided-opening-execution.ts", "opening-handoff-clock.ts"].map((name) => `src/lib/server/${name}`);

interface OpeningLaunchIntentBase {
  kind: "guided-opening-launch-intent"; dir: string; launchId: string; receivedAt: string;
  origin: { clockHash: string; startedAt: string }; controllerFiles: Array<{ path: string; sha256: string }>;
}
export type OpeningLaunchIntent = OpeningLaunchIntentBase & (
  | { schemaVersion: 1; submission: PrepareGuidedOpeningV1 }
  | { schemaVersion: 2; submission: PrepareGuidedOpeningV2 }
);
export interface OpeningLaunchActivation {
  schemaVersion: 1; kind: "guided-opening-controller-activation"; intentHash: string;
  owner: ProcessIdentity; handoff: OpeningClockHandoff;
}

/** Optional means ENOENT only. Permissions, symlinks and malformed records never become absence. */
export function optionalLaunchRecord(file: string) {
  try { lstatSync(file); }
  catch (error) { if ((error as NodeJS.ErrnoException).code === "ENOENT") return null; throw error; }
  return readCutPreviewObject(file);
}

export function openingLaunchDirectory(dir: string, journalHash: string, create = false) {
  sha256(journalHash, "opening launch journal");
  if (!create) return path.join(dir, "guided-opening-launches", journalHash);
  return humanCutDirectory(humanCutDirectory(dir, "guided-opening-launches"), journalHash);
}

/** Exclusive publication is the spawn fence: identical pre-existing bytes still throw EEXIST. */
export function createOpeningLaunchRecord(root: string, name: string, value: unknown) {
  if (!["intent.json", "activation.json", "released.json", "controller-started.json", "outcome.json"].includes(name)) {
    throw new Error("Unknown opening controller record");
  }
  assertCutPreviewDirectory(root);
  atomicCreateFileSync(path.join(root, name), canonicalJson(value));
  return readCutPreviewObject(path.join(root, name)).sha256;
}

function controllerNames(version: 1 | 2): string[] {
  if (version === 1) return CONTROLLER_FILES;
  if (version !== 2) throw new Error("Unsupported opening launch intent version");
  return [...new Set([...CONTROLLER_FILES, ...GUIDED_SOURCE_COLOR_TS_FILES])];
}

/** New controller modules must explicitly exist in the original source snapshot.
 * V2 adds source-color metadata code, not a public launcher or execution capability. */
export function openingControllerFiles(proposal: OpeningReadiness, version: 1 | 2 = 1) {
  return controllerNames(version).map((name) => ({ path: name,
    sha256: pinnedProposalFile({ ...proposal, receipt: proposal.cutReceipt }, name, true).sha256 }));
}

/** Sealed rendering requires explicit host tool pins; discover a missing setup before the spawn fence.
 * Runtime hashing, version and media qualification still belong to the existing renderer. */
export function assertOpeningControllerTools(environment: NodeJS.ProcessEnv = process.env): void {
  for (const name of ["SNIPER_NODE_PATH", "HYPERFRAMES_BROWSER_PATH", "HYPERFRAMES_FFMPEG_PATH", "HYPERFRAMES_FFPROBE_PATH"]) {
    const value = environment[name];
    if (!value || value !== value.trim() || !path.isAbsolute(value)) throw new Error(`Opening requires explicit ${name}; no sealed-runtime discovery fallback`);
    const file = realpathSync(value);
    if (!lstatSync(file).isFile()) throw new Error(`Opening tool ${name} is not a regular executable`);
    accessSync(file, constants.X_OK);
  }
}

export function readOpeningLaunchIntent(dir: string, journalHash: string) {
  const root = openingLaunchDirectory(dir, journalHash), held = optionalLaunchRecord(path.join(root, "intent.json"));
  if (!held) return null;
  const row = held.value, keys = ["schemaVersion", "kind", "dir", "launchId", "submission", "receivedAt", "origin", "controllerFiles"];
  exactKeys(row, keys, keys, "opening launch intent");
  if (row.schemaVersion !== 1 && row.schemaVersion !== 2) throw new Error("Unsupported opening launch intent version");
  const submission = parsePrepareGuidedOpeningRequest(row.submission), origin = objectValue(row.origin, "opening launch origin");
  const names = controllerNames(row.schemaVersion);
  exactKeys(origin, ["clockHash", "startedAt"], ["clockHash", "startedAt"], "opening launch origin");
  uuid(row.launchId, "launchId"); sha256(origin.clockHash, "clockHash");
  strictGuidedTimestamp(origin.startedAt); strictGuidedTimestamp(row.receivedAt);
  if (row.schemaVersion !== submission.schemaVersion || row.kind !== "guided-opening-launch-intent" || row.dir !== dir
      || submission.expectedJournalHash !== journalHash || String(row.receivedAt) < String(origin.startedAt)
      || !Array.isArray(row.controllerFiles) || row.controllerFiles.length !== names.length) {
    throw new Error("Opening launch intent lost its exact project, journal or source binding");
  }
  row.controllerFiles.forEach((value, index) => {
    const file = objectValue(value, "controller source");
    exactKeys(file, ["path", "sha256"], ["path", "sha256"], "controller source");
    if (file.path !== names[index]) throw new Error("Opening controller source inventory changed");
    sha256(file.sha256, "controller source hash");
  });
  return { root, hash: held.sha256, intent: row as unknown as OpeningLaunchIntent };
}

/** This new handshake requires complete identity, never the older PID/heartbeat fallback. */
export function strictOpeningControllerIdentity(value: unknown): ProcessIdentity {
  const row = objectValue(value, "opening controller identity"), keys = ["pid", "bootSession", "startToken"];
  exactKeys(row, keys, keys, "opening controller identity");
  if (!Number.isSafeInteger(row.pid) || Number(row.pid) < 2 || typeof row.bootSession !== "string"
      || !row.bootSession || row.bootSession.length > 256 || typeof row.startToken !== "string"
      || !row.startToken || row.startToken.length > 256) throw new Error("Exact controller process identity is unavailable");
  return row as unknown as ProcessIdentity;
}

export function readOpeningLaunchActivation(held: NonNullable<ReturnType<typeof readOpeningLaunchIntent>>) {
  const file = optionalLaunchRecord(path.join(held.root, "activation.json"));
  if (!file) return null;
  const row = file.value, keys = ["schemaVersion", "kind", "intentHash", "owner", "handoff"];
  exactKeys(row, keys, keys, "opening controller activation");
  const owner = strictOpeningControllerIdentity(row.owner), handoff = parseOpeningClockHandoff(row.handoff, held.intent.origin);
  if (row.schemaVersion !== 1 || row.kind !== "guided-opening-controller-activation" || row.intentHash !== held.hash
      || handoff.receivedAt !== held.intent.receivedAt) throw new Error("Opening controller activation is not bound to this launch");
  return { hash: file.sha256, activation: { ...row, owner, handoff } as unknown as OpeningLaunchActivation };
}

/** A launch acknowledgement is not liveness, resource absence, media or approval. */
export function assertOpeningControllerSelf(activation: OpeningLaunchActivation) {
  const self = strictOpeningControllerIdentity(captureProcessIdentity(process.pid));
  if (canonicalJsonSha256(self) !== canonicalJsonSha256(activation.owner)) throw new Error("Opening activation belongs to a different process identity");
}
