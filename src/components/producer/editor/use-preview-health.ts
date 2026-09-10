"use client";

import { useCallback, useEffect, useMemo, useState, type RefObject } from "react";

export interface PreviewHealth {
  ready: boolean;
  error: string | null;
}
interface BoundHealth extends PreviewHealth { html: string }
const STARTUP_LIMIT_MS = 10_000;

/** Validate only the small preview protocol, not arbitrary child message text. */
export function parsePreviewHealth(value: unknown, token: string): PreviewHealth | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const message = value as Record<string, unknown>;
  if (message.type !== "hf-preview-health" || message.token !== token
      || typeof message.ready !== "boolean") return null;
  if (message.ready && message.error === null) return { ready: true, error: null };
  if (!message.ready && typeof message.error === "string" && message.error.trim()) {
    return { ready: false, error: message.error.slice(0, 400) };
  }
  return null;
}

/** Asset/runtime errors from this opaque iframe only; never weaken its sandbox. */
export function usePreviewHealth(
  iframeRef: RefObject<HTMLIFrameElement | null>,
  html: string | null,
) {
  const [health, setHealth] = useState<BoundHealth | null>(null);
  const token = useMemo(() => html ? crypto.randomUUID() : "", [html]);
  const requestHealth = useCallback(() => {
    iframeRef.current?.contentWindow?.postMessage({ type: "hf-preview-status", token }, "*");
  }, [iframeRef, token]);
  useEffect(() => {
    if (!html) return;
    const receive = (event: MessageEvent) => {
      if (!iframeRef.current?.contentWindow || event.source !== iframeRef.current.contentWindow) return;
      const parsed = parsePreviewHealth(event.data, token);
      if (parsed) setHealth({ html, ...parsed });
    };
    window.addEventListener("message", receive);
    requestHealth();
    const timeout = window.setTimeout(() => setHealth((current) => current?.html === html ? current : {
      html, ready: false, error: "Preview did not initialize within 10 seconds. Close and reopen to retry.",
    }), STARTUP_LIMIT_MS);
    return () => { window.removeEventListener("message", receive); window.clearTimeout(timeout); };
  }, [html, iframeRef, requestHealth, token]);
  const current = health?.html === html ? health : null;
  return { ready: current?.ready ?? false, error: current?.error ?? null, requestHealth };
}
