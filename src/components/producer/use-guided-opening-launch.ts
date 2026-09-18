"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { clearConfirmedOpeningLaunch, fetchOpeningLaunchStatus, openingLaunchSubmission, readPendingOpeningLaunch,
  retainOpeningLaunch, submitOpeningLaunch, OPENING_LAUNCH_POLL_LIMIT, OPENING_LAUNCH_POLL_MS,
  type OpeningLaunchStatus } from "@/lib/producer/guided-opening-launch-client";
import type { PrepareGuidedOpeningV1 } from "@/lib/producer/contracts/guided-opening-v1";

interface ReadState { status: OpeningLaunchStatus | null; pending: PrepareGuidedOpeningV1 | null; error: string | null; paused: boolean }
const EMPTY: ReadState = { status: null, pending: null, error: null, paused: false };
const message = (error: unknown) => error instanceof Error ? error.message : "Opening request outcome is unknown";

function delay(signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const finish = () => { signal.removeEventListener("abort", abort); resolve(); };
    const timer = window.setTimeout(finish, OPENING_LAUNCH_POLL_MS);
    const abort = () => { window.clearTimeout(timer); signal.removeEventListener("abort", abort); reject(signal.reason); };
    signal.addEventListener("abort", abort, { once: true });
    if (signal.aborted) abort();
  });
}

async function pollingWindow<T>(action: () => Promise<T>, signal: AbortSignal, deadline: AbortSignal): Promise<{ value: T } | null> {
  try { return { value: await action() }; }
  catch (error) {
    if (deadline.aborted && !signal.aborted) return null;
    throw error;
  }
}

/** Polls only the cheap launch metadata, never sources/media, and never launches or retries work. */
async function watchLaunch(input: { dir: string; signal: AbortSignal; observe: (value: ReadState) => void; terminal: () => void }) {
  let recorded = false, previous = EMPTY;
  const deadline = AbortSignal.timeout(25 * 60_000), watching = AbortSignal.any([input.signal, deadline]);
  for (let count = 0; count < OPENING_LAUNCH_POLL_LIMIT; count++) {
    const timeout = AbortSignal.timeout(15_000), signal = AbortSignal.any([watching, timeout]);
    const observed = await pollingWindow(() => fetchOpeningLaunchStatus(input.dir, signal), input.signal, deadline);
    if (!observed) { input.observe({ ...previous, paused: true }); return; }
    const status = observed.value;
    input.signal.throwIfAborted();
    const pending = readPendingOpeningLaunch(input.dir, window.sessionStorage);
    const paused = status.state === "launch-recorded" && count === OPENING_LAUNCH_POLL_LIMIT - 1;
    previous = { status, pending, error: null, paused }; input.observe(previous);
    if (status.state !== "launch-recorded" && (recorded || status.state === "failed" || status.state === "unavailable")) input.terminal();
    if (status.state !== "launch-recorded") return;
    recorded = true;
    if (paused) return;
    const waited = await pollingWindow(() => delay(watching), input.signal, deadline);
    if (!waited) { input.observe({ ...previous, paused: true }); return; }
  }
}

function useLaunchMetadata(dir: string, onEvidenceRefresh: () => void) {
  const [revision, setRevision] = useState(0), [state, setState] = useState<{ dir: string; revision: number; read: ReadState } | null>(null);
  const notify = useRef(onEvidenceRefresh);
  useEffect(() => { notify.current = onEvidenceRefresh; }, [onEvidenceRefresh]);
  const refresh = useCallback(() => setRevision((value) => value + 1), []);
  useEffect(() => {
    const controller = new AbortController();
    const observe = (read: ReadState) => { if (!controller.signal.aborted) setState({ dir, revision, read }); };
    watchLaunch({ dir, signal: controller.signal, observe, terminal: () => notify.current() })
      .catch((error: unknown) => observe({ ...EMPTY, error: `${message(error)}. Recheck; no automatic render retry was sent.` }));
    return () => controller.abort();
  }, [dir, revision]);
  return { ...(state?.dir === dir && state.revision === revision ? state.read : EMPTY), refresh };
}

/** Synchronous duplicate-click fence plus persisted UUID. Leaving the panel aborts only the response, never server work. */
export function useGuidedOpeningLaunch(dir: string, onEvidenceRefresh: () => void) {
  const read = useLaunchMetadata(dir, onEvidenceRefresh), current = useRef<AbortController | null>(null);
  const [action, setAction] = useState({ busy: false, error: null as string | null, recorded: false });
  useEffect(() => () => { current.current?.abort(); current.current = null; }, [dir]);
  const submit = async () => {
    if (current.current || !read.status) return;
    const controller = new AbortController(); current.current = controller;
    const timer = window.setTimeout(() => controller.abort(new Error("Opening launch response timed out; server outcome is unknown")), 45_000);
    setAction({ busy: true, error: null, recorded: false });
    try {
      const pending = readPendingOpeningLaunch(dir, window.sessionStorage);
      const submission = openingLaunchSubmission(read.status, pending, () => crypto.randomUUID());
      retainOpeningLaunch(dir, submission, window.sessionStorage); controller.signal.throwIfAborted();
      await submitOpeningLaunch({ dir, submission, signal: controller.signal });
      if (current.current !== controller) return;
      try { clearConfirmedOpeningLaunch(dir, submission.idempotencyKey, window.sessionStorage); }
      catch { setAction({ busy: false, error: "Launch recorded, but the saved browser request could not be cleared. Recheck status; do not start a duplicate.", recorded: true }); return; }
      setAction({ busy: false, error: null, recorded: true });
    } catch (error) {
      if (current.current === controller) setAction({ busy: false, error: `${message(error)}. The saved request ID will be reused; a lost response is not cancellation.`, recorded: false });
    } finally {
      window.clearTimeout(timer);
      if (current.current === controller) { current.current = null; read.refresh(); onEvidenceRefresh(); }
    }
  };
  return { ...read, ...action, submit, readError: read.error };
}
