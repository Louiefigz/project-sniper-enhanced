import { existsSync, lstatSync, readFileSync } from "node:fs";
import { palmierStatePath } from "../palmier/_lib";

export type PalmierWorkspaceClassification =
  | { state: "absent" }
  | {
    state: "managed";
    workspaceMode?: "managed-draft" | "verified-mirror";
    assetKind?: "source" | "saved-cut";
  }
  | { state: "invalid"; error: string };

function nonEmpty(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

type StateRead =
  | { kind: "absent" }
  | { kind: "invalid"; error: string }
  | { kind: "value"; value: unknown };

function readState(dir: string): StateRead {
  const statePath = palmierStatePath(dir);
  try {
    const stat = lstatSync(statePath);
    if (!stat.isFile() || stat.isSymbolicLink() || stat.nlink !== 1) {
      return {
        kind: "invalid",
        error: "Palmier workspace state is not one safe regular file.",
      };
    }
    return {
      kind: "value",
      value: JSON.parse(readFileSync(statePath, "utf8")) as unknown,
    };
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") {
      return { kind: "absent" };
    }
    return {
      kind: "invalid",
      error: `Palmier workspace state is unreadable: ${(error as Error).message}`,
    };
  }
}

/** Classify product authority without consulting the legacy writer-lease owner. */
export function classifyPalmierWorkspace(dir: string): PalmierWorkspaceClassification {
  const observed = readState(dir);
  if (observed.kind === "absent") return { state: "absent" };
  if (observed.kind === "invalid") {
    return { state: "invalid", error: observed.error };
  }
  const value = observed.value;
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return { state: "invalid", error: "Palmier workspace state is not a JSON object." };
  }
  const row = value as Record<string, unknown>;
  const managedMode = row.workspaceMode === "managed-draft"
    || row.workspaceMode === "verified-mirror" || row.mirrorMode === "visual-master";
  const ownerValid = row.ownership === undefined
    || row.ownership === "sniper" || row.ownership === "palmier";
  if (row.schemaVersion !== 4 || !managedMode || !ownerValid
      || !nonEmpty(row.projectId) || !nonEmpty(row.projectPath)
      || !existsSync(row.projectPath) || !nonEmpty(row.latestTimelineId)) {
    return {
      state: "invalid",
      error: "Palmier workspace state is incomplete or uses an unknown schema.",
    };
  }
  const draft = row.draft && typeof row.draft === "object" && !Array.isArray(row.draft)
    ? row.draft as Record<string, unknown> : null;
  const assetKind = draft?.assetKind === "source" || draft?.assetKind === "saved-cut"
    ? draft.assetKind : undefined;
  return {
    state: "managed",
    workspaceMode: row.workspaceMode === "managed-draft"
      ? "managed-draft" : "verified-mirror",
    ...(assetKind ? { assetKind } : {}),
  };
}

/** A Sniper-plan promotion is legal only while Palmier has no managed head. */
export function assertPalmierWorkspaceAbsent(dir: string): void {
  const workspace = classifyPalmierWorkspace(dir);
  if (workspace.state === "absent") return;
  const detail = workspace.state === "invalid"
    ? workspace.error
    : "A managed Palmier workspace is now the canonical editing authority.";
  throw new Error(`${detail} Refusing to promote an older Sniper plan.`);
}
