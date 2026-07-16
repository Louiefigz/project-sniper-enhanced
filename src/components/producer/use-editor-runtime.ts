"use client";

import { useEffect, useState } from "react";

interface RuntimeStatus {
  brain: { provider: "legacy" | "codex"; model: string; reasoning: string | null };
}

type EditMode = "short" | "longform";

export function editorBrainLabel(status: RuntimeStatus | null): string {
  // Match the server's Claude-default contract immediately; /api/runtime
  // replaces this label when an explicit Codex override is configured.
  if (!status) return "Claude Code · sonnet";
  if (status.brain.provider === "legacy") return `Claude Code · ${status.brain.model}`;
  const model = status.brain.model.replace("gpt-", "GPT ").toUpperCase();
  return status.brain.reasoning
    ? `Codex · ${model} · ${status.brain.reasoning.toUpperCase()}`
    : `Codex · ${model}`;
}

export function useEditorRuntime(): RuntimeStatus | null {
  const [status, setStatus] = useState<RuntimeStatus | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/runtime", { cache: "no-store", signal: controller.signal })
      .then((response) => response.ok ? response.json() : null)
      .then((value) => setStatus(value as RuntimeStatus | null))
      .catch(() => setStatus(null));
    return () => controller.abort();
  }, []);
  return status;
}

async function post(
  url: string,
  body: Record<string, unknown>,
  signal?: AbortSignal,
): Promise<Response> {
  return fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
}

/** Palmier is the visible workbench, so establish it before editing starts. */
export async function openPalmierWorkbench(
  dir: string,
  mode?: EditMode,
  signal?: AbortSignal,
): Promise<void> {
  const viewed = await post("/api/producer/palmier/view", { dir }, signal);
  if (viewed.ok) return;
  const viewBody = await viewed.json().catch(() => ({})) as { error?: string };
  const missingWorkspace = viewed.status === 409
    && /No managed Palmier workspace exists/i.test(viewBody.error ?? "");
  if (!missingWorkspace) {
    throw new Error(viewBody.error || `Palmier view ${viewed.status}`);
  }
  const created = await post(
    "/api/producer/palmier/workspace",
    mode ? { dir, mode } : { dir },
    signal,
  );
  if (created.ok) return;
  const body = await created.json().catch(() => ({})) as { error?: string };
  throw new Error(body.error || `Palmier workspace ${created.status}`);
}

interface AutoEditLaunch {
  dir: string;
  mode?: EditMode;
  request: Record<string, unknown>;
  signal?: AbortSignal;
}

/**
 * The only browser-side Producer auto-edit launcher. Palmier must be visible
 * before the controller receives the job, so a failed open never starts work.
 */
export async function launchAutoEditFromPalmier(input: AutoEditLaunch): Promise<Response> {
  await openPalmierWorkbench(input.dir, input.mode, input.signal);
  input.signal?.throwIfAborted();
  return post("/api/producer/auto-edit", input.request, input.signal);
}
