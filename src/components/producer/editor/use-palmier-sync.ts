"use client";

import { useCallback, useState } from "react";
import { readEventStream } from "@/lib/producer/sse";
import type { StreamEvent } from "@/lib/producer/types";

export type PushState = "idle" | "running" | "error";

interface SyncInput {
  dir: string;
  markRenderExists: () => void;
  refreshPreflight: () => Promise<unknown>;
  onPushed: () => void;
  onWarningEvent: (event: StreamEvent) => void;
}

interface Progress {
  waiting: boolean;
  upToDate: boolean;
}

const PUSH_MESSAGES: Record<string, string> = {
  shadow_created: "building shadow timeline…",
  mirror_placed: "exact visual master placed…",
  cuts_placed: "cuts placed…",
  overlays_placed: "graphics placed…",
  export_started: "Palmier is rendering…",
  exported: "verifying export…",
  media_reused: "reusing imported media…",
  media_adopted: "reusing imported media…",
  timeline_restored: "human timeline restored…",
};

async function pushResponse(dir: string): Promise<Response> {
  const response = await fetch("/api/producer/palmier/push", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ dir }),
  });
  if (response.ok) return response;
  const detail = (await response.json().catch(() => ({}))) as {
    error?: string;
    errors?: string[];
  };
  const message = detail.errors?.length
    ? `${detail.error} — ${detail.errors[0]}` : detail.error || `sync ${response.status}`;
  throw new Error(message);
}

function handleProgress(
  event: StreamEvent,
  progress: Progress,
  setMessage: (message: string) => void,
  onWarning: (event: StreamEvent) => void,
): void {
  const status = typeof event.status === "string" ? event.status : "";
  if (event.event === "error") throw new Error(String(event.message));
  if (event.error) throw new Error(String(event.error));
  if (event.event === "waiting" || status === "waiting" || status === "queued") {
    progress.waiting = true;
    setMessage(String(event.reason ?? event.message ?? "waiting for Palmier"));
  }
  if (status === "warning") onWarning(event);
  if (status === "up_to_date") {
    progress.upToDate = true;
    setMessage("already in sync");
  } else if (status === "imported") {
    setMessage(`importing media (${String(event.key)})…`);
  } else if (status && PUSH_MESSAGES[status]) {
    setMessage(PUSH_MESSAGES[status]);
  }
}

export function usePalmierSync(input: SyncInput) {
  const [state, setState] = useState<PushState>("idle");
  const [message, setMessage] = useState("");
  const { dir, markRenderExists, refreshPreflight, onPushed, onWarningEvent } = input;
  const sync = useCallback(async () => {
    setState("running");
    setMessage("lint gate…");
    const progress: Progress = { upToDate: false, waiting: false };
    try {
      const response = await pushResponse(dir);
      await readEventStream(response, (event) => handleProgress(
        event, progress, setMessage, onWarningEvent,
      ));
      setState("idle");
      if (progress.waiting) return;
      await refreshPreflight();
      if (progress.upToDate) return;
      markRenderExists();
      setMessage("Palmier export ready — compare when you want");
      onPushed();
    } catch (error) {
      setState("error");
      setMessage(error instanceof Error ? error.message : "Palmier sync failed");
    }
  }, [dir, markRenderExists, onPushed, onWarningEvent, refreshPreflight]);
  return { state, message, sync };
}
