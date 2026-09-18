import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import type { PalmierLiveBuildQcAuthority } from
  "../../live-build/authority";
import { closeLiveBuildJournal } from "../../live-build/journal";

interface LiveReviewAuthority {
  request: string;
  lanes: string[];
  plan: Record<string, unknown>;
  paths: string[];
}

function object(
  value: unknown,
  label: string,
): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`Candidate QC ${label} is not an object.`);
  }
  return value as Record<string, unknown>;
}

function hashBytes(filePath: string): string {
  return createHash("sha256").update(
    readFileSync(filePath)).digest("hex");
}

function hashText(value: string): string {
  return createHash("sha256").update(value, "utf8").digest("hex");
}

export function isLiveBuildQcAuthority(
  authority: unknown,
): authority is PalmierLiveBuildQcAuthority {
  const row = authority && typeof authority === "object"
    ? authority as Record<string, unknown> : {};
  return row.kind === "palmier-live-build-qc-authority";
}

/** Reparse and freeze the closed operation lifecycle before critic access. */
export function liveReviewAuthority(
  authority: PalmierLiveBuildQcAuthority): LiveReviewAuthority {
  const expected = authority.liveInput;
  if (!expected || hashBytes(expected.path) !== expected.hash) {
    throw new Error("Candidate QC live-build input bytes changed after capture.");
  }
  const artifact = object(JSON.parse(
    readFileSync(expected.path, "utf8")), "live input");
  const request = object(artifact.request, "live input request");
  const controller = object(artifact.controller, "live input controller");
  const planRef = object(artifact.plan, "live input plan");
  const journal = object(artifact.journal, "live input journal");
  const parent = object(artifact.parent, "live input parent");
  const lanes = controller.lanes;
  const plan = typeof planRef.path === "string" ? object(
    JSON.parse(readFileSync(planRef.path, "utf8")), "approved edit plan") : {};
  const closed = closeLiveBuildJournal(authority.ctx.dir, expected.headFingerprint);
  const exact = artifact.schemaVersion === 1
    && artifact.kind === "palmier-live-build-input"
    && artifact.captureId === authority.captureId
    && typeof request.text === "string"
    && request.hash === hashText(request.text)
    && request.hash === authority.requestHash
    && Array.isArray(lanes)
    && lanes.every((item) => typeof item === "string")
    && JSON.stringify(lanes) === JSON.stringify(expected.lanes)
    && typeof planRef.path === "string"
    && hashBytes(planRef.path) === expected.planHash
    && journal.path === closed.path
    && journal.hash === closed.hash
    && journal.operationCount === closed.operationCount
    && journal.lifecycleDigest === closed.lifecycleDigest
    && journal.headFingerprint === closed.headFingerprint
    && closed.hash === expected.journalHash
    && closed.lifecycleDigest === expected.journalLifecycleDigest
    && closed.headFingerprint === expected.headFingerprint
    && journal.operationCount === expected.operationCount
    && parent.timelineId === expected.parent.timelineId
    && parent.fingerprint === expected.parent.fingerprint;
  if (!exact) {
    throw new Error(
      "Candidate QC approved plan, journal, scope, or parent is stale.");
  }
  return {
    request: request.text as string,
    lanes: [...lanes] as string[],
    plan,
    paths: [expected.path, planRef.path as string, closed.path],
  };
}
