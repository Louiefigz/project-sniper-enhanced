import type { ColorContext, ColorDescriptor, ColorJob, ColorStart } from "./color-diagnostic";
const SHA = /^[0-9a-f]{64}$/u;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/u;
function row(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Invalid private color response");
  return value as Record<string, unknown>;
}
function text(value: unknown, maximum = 2000): value is string { return typeof value === "string" && value.length <= maximum; }
function finite(value: unknown): value is number { return typeof value === "number" && Number.isFinite(value) && value >= 0; }
function strings(value: unknown): boolean { return Array.isArray(value) && value.length <= 100 && value.every(item => text(item)); }
export function parseColorDescriptor(value: unknown): ColorDescriptor {
  const item = row(value);
  if (item.ok !== true || item.kind !== "descriptor" || ![item.planHash, item.manifestHash, item.cutHash].every(hash => text(hash) && SHA.test(hash))
      || !Array.isArray(item.sources) || !item.sources.length || item.sources.length > 8 || !strings(item.blockers)
      || !Array.isArray(item.projectHistory) || item.projectHistory.length > 40) throw new Error("Invalid color source descriptor");
  for (const value of item.sources) {
    const source = row(value);
    if (!text(source.id, 200) || !source.id || !text(source.label, 200) || !finite(source.duration) || source.duration <= 0
        || !(source.sha256 === null || text(source.sha256) && SHA.test(source.sha256))) throw new Error("Invalid color source");
  }
  return item as unknown as ColorDescriptor;
}
export function parseColorJob(value: unknown): ColorJob {
  const item = row(value);
  if (item.ok !== true || item.kind !== "job" || !text(item.jobId) || !UUID.test(item.jobId)
      || !["running", "complete", "partial", "failed", "interrupted"].includes(String(item.state))
      || ![item.planHash, item.manifestHash].every(hash => text(hash) && SHA.test(hash))
      || !finite(item.elapsedMs) || item.queueMs !== 0 || !text(item.startedAt) || !Number.isFinite(Date.parse(item.startedAt))
      || [item.cleanupVerified, item.inputsRevalidated, item.parentsCurrent].some(flag => typeof flag !== "boolean")
      || item.reviewState !== "unreviewed" || item.deliveryApproved !== false || item.qualityQualified !== false || item.writesGrade !== false
      || !Array.isArray(item.groups) || item.groups.length > 8 || !Array.isArray(item.timings) || item.timings.length > 8
      || !strings(item.caveats) || !(item.error === null || text(item.error))) throw new Error("Invalid private color result or authority claim");
  if (["running", "failed", "interrupted"].includes(String(item.state)) && item.groups.length) throw new Error("Incomplete color job cannot carry screening suggestions");
  for (const value of item.groups) {
    const group = row(value);
    if (!text(group.sourceId, 200) || !text(group.groupId, 64) || !strings(group.warnings)
        || !Array.isArray(group.observations) || group.observations.length > 64
        || !Array.isArray(group.retainedIntervals) || !Array.isArray(group.unsampledIntervalIndices)
        || !Array.isArray(group.screeningOffsets) || group.screeningOffsets.length > 1
        || group.screeningOffsets.some(n => typeof n !== "number" || !Number.isFinite(n) || Math.abs(n) > 0.04)) throw new Error("Invalid color group result");
  }
  return item as unknown as ColorJob;
}
async function readResponse(response: Response): Promise<unknown> {
  const reader = response.body?.getReader();
  if (!reader) throw new Error("Color response was empty");
  let textValue = "", size = 0; const decoder = new TextDecoder("utf-8", { fatal: true });
  try {
    while (true) {
      const { done, value } = await reader.read(); if (done) break;
      size += value.length; if (size > 2 * 1024 * 1024) throw new Error("Color response exceeds its bound");
      textValue += decoder.decode(value, { stream: true });
    }
    const value = JSON.parse(textValue + decoder.decode());
    if (!response.ok) throw new Error(text(value?.error) ? value.error : `Color request failed (${response.status})`);
    return value;
  } finally { void reader.cancel().catch(() => {}); }
}
export async function colorDescriptor(dir: string): Promise<ColorDescriptor> {
  return parseColorDescriptor(await readResponse(await fetch(`/api/producer/color-diagnostic?${new URLSearchParams({ dir })}`, { cache: "no-store", signal: AbortSignal.timeout(10_000) })));
}
export async function colorStatus(dir: string, jobId: string): Promise<ColorJob> {
  if (!UUID.test(jobId)) throw new Error("Invalid color token");
  return parseColorJob(await readResponse(await fetch(`/api/producer/color-diagnostic?${new URLSearchParams({ dir, jobId })}`, { cache: "no-store", signal: AbortSignal.timeout(10_000) })));
}
/** Deliberately no abort-on-unmount: the server retains bounded worker ownership. */
export async function startColorDiagnostic(input: ColorStart): Promise<ColorJob> {
  return parseColorJob(await readResponse(await fetch("/api/producer/color-diagnostic", { method: "POST", cache: "no-store",
    signal: AbortSignal.timeout(300_000),
    headers: { "Content-Type": "application/json" }, body: JSON.stringify(input) })));
}
export async function colorCutHash(cut: unknown): Promise<string> {
  const bytes = new TextEncoder().encode(JSON.stringify(cut ?? []));
  const hash = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(hash), byte => byte.toString(16).padStart(2, "0")).join("");
}

function contextIdentity(value: ColorContext): string {
  return JSON.stringify([value.sourceId, value.sourceProfile, value.cameraProfile,
    value.historyState, value.transformHistory, value.lightingGroups.map(group =>
      [group.id, group.start, group.end, group.intent, group.description])]);
}

/** Edited declarations cannot silently relabel observations from an older run. */
export function colorResultMatchesContexts(job: ColorJob, contexts: ColorContext[]): boolean {
  if (!job.groups.length || job.groups.length !== contexts.length
      || new Set(contexts.map(item => item.sourceId)).size !== contexts.length
      || new Set(job.groups.map(item => item.sourceId)).size !== job.groups.length) return false;
  try {
    return job.groups.every(group => {
      const current = contexts.find(item => item.sourceId === group.sourceId);
      return !!current && contextIdentity(current) === contextIdentity(group.context);
    });
  } catch { return false; }
}
