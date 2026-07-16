import { createHash, randomUUID } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import type { AutoEditCtx, AutoEditIntent } from "../auto-edit/stream";
import type {
  PalmierNativeAuthority,
  PalmierNativeDraft,
  PalmierNativeResult,
} from "./palmier-native-contract";
import type { PalmierNativePromptInput } from "./palmier-native-prompt";
import { doctrinePaths } from "./doctrine";
import { findManifest } from "../palmier/_lib";
import { readProjectJson } from "../../_lib/workspace";
import { captureAutoEditDoctrine } from "@/lib/server/auto-edit-doctrine";
import { captureAutoEditPipeline } from "@/lib/server/auto-edit-pipeline-authority";
import { atomicWriteJsonSync } from "@/lib/server/atomic-file";
import { PALMIER_CANDIDATE_FILE } from "@/lib/server/palmier-candidate-qc";

export interface PalmierNativeQcAuthority {
  schemaVersion: 1;
  requestHash: string;
  captureId: string;
  nativeInput: {
    path: string;
    hash: string;
    requestTextHash: string;
    lanes: string[];
    parent: NativeParentIdentity;
    nativePlanHash: string;
  };
  ctx: AutoEditCtx;
}

export interface PalmierNativeQcCapture {
  schemaVersion: 1;
  requestHash: string;
  captureId: string;
  nativeInputPath: string;
  ctx: AutoEditCtx;
}

export interface PalmierNativePlan extends PalmierNativeDraft {
  requestHash: string;
  parent: NativeParentIdentity;
}

interface NativeParentIdentity {
  projectId: string;
  timelineId: string;
  fingerprint: string;
}

function projectIntent(dir: string): { scope: AutoEditCtx["scope"]; intent?: AutoEditIntent } {
  const project = readProjectJson(path.dirname(dir));
  const selected = project?.resolvedIntent ?? project?.intent;
  const scope = selected?.scope ?? "produced";
  if (!selected) return { scope };
  const { preset: _preset, scope: _scope, ...intent } = selected;
  void _preset;
  void _scope;
  return { scope, intent: intent as AutoEditIntent };
}

function baseContext(input: PalmierNativePromptInput, planPath: string): AutoEditCtx {
  const manifestPath = findManifest(input.dir);
  if (!manifestPath) throw new Error("Governed Palmier QC requires the project's source manifest.");
  const selected = projectIntent(input.dir);
  return {
    dir: input.dir,
    scope: selected.scope,
    intent: selected.intent,
    planPath,
    manifestPath,
    transcriptsDir: path.dirname(manifestPath),
  };
}

function relativeDoctrine(input: PalmierNativePromptInput): string[] {
  const root = path.resolve(process.cwd());
  return doctrinePaths(input.scope).map((item) => path.relative(root, item))
    .filter((item) => item && !item.startsWith("..") && !path.isAbsolute(item));
}

/** Capture native-candidate authority after parent reconcile and before any writer starts. */
export function capturePalmierNativeQcAuthority(
  input: PalmierNativePromptInput,
  parent: PalmierNativeAuthority,
  requestHash: string,
): PalmierNativeQcCapture {
  const captureId = `native-${requestHash.slice(0, 16)}-${randomUUID()}`;
  const nativeInputPath = path.join(
    input.dir, ".sniper-learning", "runs", captureId, "native-input.json",
  );
  const base = baseContext(input, nativeInputPath);
  const doctrine = captureAutoEditDoctrine(
    base, captureId, process.cwd(), relativeDoctrine(input),
  );
  const pipeline = captureAutoEditPipeline(base, captureId);
  if (parent.timelineId === "" || parent.fingerprint === "") {
    throw new Error("Palmier native QC requires a fresh complete parent authority.");
  }
  return {
    schemaVersion: 1, requestHash, captureId, nativeInputPath,
    ctx: { ...base, doctrine, pipeline },
  };
}

function stableValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(stableValue);
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(Object.entries(value as Record<string, unknown>)
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([key, item]) => [key, stableValue(item)]));
}

function hashJson(value: unknown): string {
  return createHash("sha256").update(JSON.stringify(stableValue(value))).digest("hex");
}

function hashText(value: string): string {
  return createHash("sha256").update(value, "utf8").digest("hex");
}

function parentIdentity(parent: PalmierNativeAuthority): NativeParentIdentity {
  return {
    projectId: parent.projectId,
    timelineId: parent.timelineId,
    fingerprint: parent.fingerprint,
  };
}

/** Write the exact request, controller scope, parent, and validated plan once. */
export function finalizePalmierNativeQcAuthority(
  capture: PalmierNativeQcCapture,
  input: PalmierNativePromptInput,
  parent: PalmierNativeAuthority,
  nativePlan: PalmierNativePlan,
): PalmierNativeQcAuthority {
  const requestTextHash = hashText(input.request);
  const expectedParent = parentIdentity(parent);
  const coherent = capture.requestHash === requestTextHash
    && JSON.stringify(nativePlan.lanes) === JSON.stringify(input.scope.lanes)
    && nativePlan.requestHash === requestTextHash
    && JSON.stringify(nativePlan.parent) === JSON.stringify(expectedParent);
  if (!coherent || existsSync(capture.nativeInputPath)) {
    throw new Error("Palmier native input authority is stale or was already written.");
  }
  const artifact = {
    schemaVersion: 1,
    kind: "palmier-native-candidate-input",
    request: { text: input.request, hash: requestTextHash },
    controller: { lanes: [...input.scope.lanes] },
    parent,
    nativePlan,
  } as const;
  atomicWriteJsonSync(capture.nativeInputPath, artifact);
  const hash = createHash("sha256").update(readFileSync(capture.nativeInputPath)).digest("hex");
  return {
    schemaVersion: 1,
    requestHash: requestTextHash,
    captureId: capture.captureId,
    nativeInput: {
      path: capture.nativeInputPath,
      hash,
      requestTextHash,
      lanes: [...input.scope.lanes],
      parent: expectedParent,
      nativePlanHash: hashJson(nativePlan),
    },
    ctx: capture.ctx,
  };
}

function readCandidate(dir: string): Record<string, unknown> {
  const candidatePath = path.join(dir, PALMIER_CANDIDATE_FILE);
  const value = JSON.parse(readFileSync(candidatePath, "utf8")) as unknown;
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("Palmier candidate receipt disappeared before authority binding.");
  }
  return value as Record<string, unknown>;
}

/** Bind a successful candidate to its independently restorable QC authority. */
export function bindPalmierNativeQcAuthority(
  dir: string,
  result: PalmierNativeResult,
  parent: PalmierNativeAuthority,
  authority: PalmierNativeQcAuthority,
): void {
  const candidate = readCandidate(dir);
  const base = candidate.base as Record<string, unknown> | undefined;
  if (candidate.timelineId !== result.timelineId || candidate.fingerprint !== result.fingerprint
      || candidate.requestHash !== authority.requestHash || base?.timelineId !== parent.timelineId
      || base?.fingerprint !== parent.fingerprint) {
    throw new Error("Palmier candidate changed before its QC authority could be bound.");
  }
  atomicWriteJsonSync(path.join(dir, PALMIER_CANDIDATE_FILE), {
    ...candidate,
    nativeAuthority: authority,
  });
}
