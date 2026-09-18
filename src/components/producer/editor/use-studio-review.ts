"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { requestStudioReview, type StudioReviewStatus } from "@/lib/producer/studio-review-client";

interface ReviewState {
  open: boolean;
  loading: boolean;
  status: StudioReviewStatus | null;
  error: string | null;
  elapsedMs: number | null;
}

const INITIAL: ReviewState = { open: false, loading: false, status: null, error: null, elapsedMs: null };

/** Keep access state scoped to this project and suppress stale async responses. */
export function useStudioReview(dir: string) {
  const [state, setState] = useState<ReviewState>(INITIAL);
  const active = useRef<AbortController | null>(null);
  useEffect(() => {
    setState(INITIAL);
    return () => { active.current?.abort(); active.current = null; };
  }, [dir]);
  const request = useCallback(async (action: "open" | "status") => {
    active.current?.abort();
    const controller = new AbortController();
    active.current = controller;
    const started = performance.now();
    setState((prior) => ({ ...prior, open: true, loading: true, error: null,
      ...(action === "open" ? { status: null } : {}) }));
    try {
      const status = await requestStudioReview(dir, action, controller.signal);
      if (active.current === controller) setState((prior) => ({ ...prior, status }));
    } catch (error) {
      if (active.current === controller && !controller.signal.aborted) {
        setState((prior) => ({ ...prior, error: error instanceof Error ? error.message : "Studio failed" }));
      }
    } finally {
      if (active.current === controller) {
        setState((prior) => ({ ...prior, loading: false, elapsedMs: performance.now() - started }));
      }
    }
  }, [dir]);
  const close = useCallback(() => {
    active.current?.abort();
    active.current = null;
    setState((prior) => ({ ...prior, open: false, loading: false }));
  }, []);
  return { ...state, request, close };
}
