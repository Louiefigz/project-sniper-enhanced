"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { applyStudioImport, prepareStudioImport, type StudioImportProposal } from "@/lib/producer/studio-import-client";

interface Input {
  dir: string;
  blocked: string | null;
  invalidatePreview?: () => void;
  reloadDraft?: () => Promise<boolean>;
}
interface State {
  action: "prepare" | "apply" | null;
  proposal: StudioImportProposal | null;
  error: string | null;
  message: string | null;
  elapsedMs: number | null;
  warnings: string[];
}
const INITIAL: State = { action: null, proposal: null, error: null, message: null, elapsedMs: null, warnings: [] };

/** One explicit proposal at a time; retries retain exact server-issued authority. */
export function useStudioImport(input: Input) {
  const [state, setState] = useState<State>(INITIAL);
  const active = useRef<AbortController | null>(null);
  const current = useRef(input);
  current.current = input;
  useEffect(() => () => { active.current?.abort(); active.current = null; }, [input.dir]);
  const blocked = input.blocked ?? (!input.reloadDraft || !input.invalidatePreview
    ? "Draft reload is unavailable; reopen this project before importing Studio changes." : null);

  const prepare = useCallback(async () => {
    if (active.current || blocked) return;
    const controller = new AbortController();
    active.current = controller;
    const start = performance.now();
    setState({ ...INITIAL, action: "prepare" });
    try {
      const proposal = await prepareStudioImport(input.dir, controller.signal);
      if (active.current === controller) setState((prior) => ({ ...prior, proposal }));
    } catch (failure) {
      if (active.current === controller && !controller.signal.aborted) setState((prior) => ({ ...prior,
        error: failure instanceof Error ? failure.message : "Studio changes could not be inspected" }));
    } finally {
      if (active.current === controller) {
        active.current = null;
        setState((prior) => ({ ...prior, action: null, elapsedMs: performance.now() - start }));
      }
    }
  }, [input.dir, blocked]);

  const apply = useCallback(async () => {
    const callbacks = current.current;
    if (active.current || blocked || !state.proposal || !callbacks.reloadDraft || !callbacks.invalidatePreview) return;
    const controller = new AbortController();
    active.current = controller;
    const start = performance.now();
    setState((prior) => ({ ...prior, action: "apply", error: null, message: null }));
    try {
      const outcome = await applyStudioImport({ dir: input.dir, proposal: state.proposal,
        signal: controller.signal, invalidatePreview: callbacks.invalidatePreview, reloadDraft: callbacks.reloadDraft });
      if (active.current !== controller) return;
      setState((prior) => ({ ...prior,
        proposal: outcome.result ? null : prior.proposal,
        warnings: outcome.result?.warnings ?? [],
        error: outcome.error ? `${outcome.error} Recheck changes or retry this exact import; no render was started.` : null,
        message: !outcome.reloaded ? "Draft reload failed. Reopen the Sniper editor before editing; the import may already be saved."
          : outcome.result ? "Studio edits imported into the Sniper draft. Render updated video for full QC; the last approved video was not replaced."
          : "The disk draft was reloaded. The import outcome still needs confirmation." }));
    } catch (failure) {
      if (active.current === controller) setState((prior) => ({ ...prior,
        error: failure instanceof Error ? failure.message : "Studio import failed" }));
    } finally {
      if (active.current === controller) {
        active.current = null;
        setState((prior) => ({ ...prior, action: null, elapsedMs: performance.now() - start }));
      }
    }
  }, [input.dir, blocked, state.proposal]);

  const cancelPrepare = useCallback(() => {
    if (state.action === "apply") return;
    active.current?.abort();
    active.current = null;
    setState(INITIAL);
  }, [state.action]);
  return { ...state, blocked, prepare, apply, cancelPrepare, applying: state.action === "apply" };
}
