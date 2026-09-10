import fs, { existsSync } from "fs";
import path from "path";
import {
  approvalPath,
  previewAuthorityInvalidated,
  readApproval,
} from "@/lib/server/auto-edit-quality-artifacts";
import { autoEditAuthoritySnapshot } from "@/lib/server/auto-edit-authority-snapshot";
import {
  qualityPolicyRequirement,
  readQualityPolicyMarker,
} from "@/lib/server/auto-edit-quality-policy";
import { lookupProducerManifest } from "@/lib/server/producer-manifest";
import { templateUsageApprovalRequired } from "@/lib/server/template-usage-approval";

import { producerRunActive } from "@/lib/server/producer-run-registry";

// Shared helpers for the /api/producer/palmier/* routes. Before handoff,
// Sniper's reviewed plan builds the managed Palmier workspace. After handoff,
// Palmier's current timeline is canonical: governed AI edits read that working
// head and stage a separate candidate instead of replaying a stale Sniper plan.

export const PALMIER_MCP_URL = "http://127.0.0.1:19789/mcp";

/** The Palmier render's fixed landing spot inside a producer out dir. */
export function palmierRenderPath(dir: string): string {
  return path.join(dir, "final.palmier.mp4");
}

export function palmierMetaPath(dir: string): string {
  return path.join(dir, "final.palmier.meta.json");
}

export function palmierStatePath(dir: string): string {
  return path.join(dir, "palmier.sync.json");
}

/** Provenance checkpoint for the in-house audio authority. */
export function producerAuthorityPath(dir: string): string {
  return path.join(dir, "final.mp4.assembled.json");
}

export interface AutoEditQcApproval {
  required: boolean;
  approved: boolean;
  reason: string | null;
}

/** New deterministic Auto Edit jobs may sync only after final QC promotion. */
export function autoEditQcApproval(dir: string): AutoEditQcApproval {
  const policy = qualityPolicyRequirement(dir);
  if (previewAuthorityInvalidated(dir)) {
    return {
      required: !policy.legacy,
      approved: false,
      reason: "The preview was invalidated by a newer edit request; finish deterministic QC again.",
    };
  }
  if (policy.legacy) return legacyQcApproval(dir);
  if (!policy.valid) return { required: true, approved: false, reason: policy.reason };
  const marker = readQualityPolicyMarker(dir);
  const approval = readApproval(dir);
  const authority = marker?.mode === "managed" ? autoEditAuthoritySnapshot(marker.ctx) : null;
  const approved = !!approval && !!authority && marker?.mode === "managed" && marker.ctx.dir === dir
    && approval.planHash === authority.planHash
    && approval.manifestHash === authority.manifestHash
    && approval.authorityDigest === authority.digest;
  return {
    required: true,
    approved,
    reason: approved ? null
      : `Palmier sync requires the current plan to finish deterministic and visual QC (${approvalPath(dir)}).`,
  };
}

function legacyQcApproval(dir: string): AutoEditQcApproval {
  try {
    if (!templateUsageApprovalRequired(dir)) {
      return { required: false, approved: true, reason: null };
    }
  } catch {}
  return {
    required: true,
    approved: false,
    reason: "Legacy produced/full edits must run Review saved timeline before Palmier delivery.",
  };
}

export function readJsonObject(filePath: string): Record<string, unknown> | null {
  try {
    const value = JSON.parse(fs.readFileSync(filePath, "utf-8")) as unknown;
    return value && typeof value === "object" && !Array.isArray(value)
      ? (value as Record<string, unknown>)
      : null;
  } catch {
    return null;
  }
}

/**
 * Resolve the project's asset manifest for a producer out dir — the same
 * scan project-status runs: any `<project>/source/*.json` with a `sources`
 * array (transcript jsons excluded), else `<dir>/asset_manifest.json`.
 */
export function findManifest(dir: string): string | null {
  return lookupProducerManifest(dir).path;
}

/**
 * One MCP JSON-RPC exchange against the local Palmier app (SSE response body,
 * session id via header). Throws on transport failure; the status route turns
 * that into {up:false}.
 */
export async function palmierRpc(
  method: string,
  params: Record<string, unknown>,
  sessionId: string | null,
  id: number | null, // null = notification (no response expected)
  timeoutMs = 2000,
): Promise<{ result?: unknown; sessionId: string | null }> {
  const body: Record<string, unknown> = { jsonrpc: "2.0", method, params };
  if (id != null) body.id = id;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Accept: "application/json, text/event-stream",
  };
  if (sessionId) headers["Mcp-Session-Id"] = sessionId;
  const res = await fetch(PALMIER_MCP_URL, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(timeoutMs),
  });
  const sid = res.headers.get("Mcp-Session-Id") || sessionId;
  if (id == null) return { sessionId: sid };
  const text = await res.text();
  for (const line of text.split("\n")) {
    const payload = line.startsWith("data:") ? line.slice(5).trim() : line.trim();
    if (!payload.startsWith("{")) continue;
    let obj: { result?: unknown; error?: unknown };
    try {
      obj = JSON.parse(payload) as { result?: unknown; error?: unknown };
    } catch {
      continue;
    }
    if ("error" in obj) throw new Error(`Palmier JSON-RPC error: ${JSON.stringify(obj.error)}`);
    if ("result" in obj) return { result: obj.result, sessionId: sid };
  }
  throw new Error(`Palmier returned no JSON-RPC response for ${method}`);
}

export interface Handoff {
  projectPath: string;
  timelineId: string;
  planHash: string;
  ownership: "sniper" | "palmier";
}

interface HandoffError {
  error: string;
  status: number;
}

/** Ownership may not move while Sniper is still changing the managed project. */
export function activePalmierHandoffBlock(dir: string): string | null {
  return producerRunActive(dir)
    ? "Sniper is still working on this project. Stop and keep its checkpoint before taking control in Palmier."
    : null;
}

export function loadHandoff(dir: string): Handoff | HandoffError {
  const state = readJsonObject(palmierStatePath(dir));
  const projectPath = typeof state?.projectPath === "string" && existsSync(state.projectPath)
    ? state.projectPath
    : null;
  const timelineId = typeof state?.latestTimelineId === "string" ? state.latestTimelineId : null;
  const planHash = typeof state?.lastPushPlanHash === "string" ? state.lastPushPlanHash : null;
  const ownership = state?.ownership === "palmier" ? "palmier" : "sniper";
  if (!projectPath || !timelineId || !planHash) {
    return { error: "No verified Palmier handoff exists for this project yet.", status: 409 };
  }
  const parity = asObject(state?.parity);
  const verification = asObject(state?.verification);
  const proofMatches = verification?.planHash === planHash
    && verification?.timelineId === timelineId;
  if (state?.schemaVersion !== 4 || state?.mirrorMode !== "visual-master"
      || parity?.mirrorReady !== true || verification?.ok !== true || !proofMatches) {
    return {
      error: "Palmier mirror proof is incomplete. Update the mirror before opening it.",
      status: 409,
    };
  }
  return { projectPath, timelineId, planHash, ownership };
}

function asObject(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}
