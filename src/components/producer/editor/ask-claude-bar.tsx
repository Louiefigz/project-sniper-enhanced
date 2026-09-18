"use client";

import { useEffect, useRef, useState } from "react";
import { readEventStream } from "@/lib/producer/sse";
import { inferSurgicalEditScope } from "@/lib/producer/surgical-edit";
import { planRefitProgressMessage } from "@/lib/producer/auto-edit-progress";

interface Props {
  dir: string;
  blocked?: string | null; // concurrency guard — why Send is disabled (e.g. re-render running)
  prefill?: { text: string; nonce: number } | null; // ruler range → "[mm:ss.s–mm:ss.s] " + focus
  onBusyChange?: (busy: boolean) => void; // lets the editor block Save/Re-render while the CLI edits the plan
  onInvalidateAuthority: () => void; // synchronous: hide stale Sniper/Palmier A/B before any async work
  onBeforeRun: () => Promise<boolean>; // persist unsaved in-memory edits; false = abort
  onPlanChanged: () => Promise<boolean>; // reload edit_plan.json into the timeline (undo-ably)
}

// Subscription-brain edit bar. The Producer route uses the configured brain;
// Claude Code receives the explicit runtime model and stripped app secrets.
export default function AskClaudeBar({
  dir, blocked, prefill, onBusyChange, onInvalidateAuthority, onBeforeRun, onPlanChanged,
}: Props) {
  const [text, setText] = useState("");
  const [state, setState] = useState<"idle" | "running" | "error">("idle");
  const [msg, setMsg] = useState("");
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Ruler "Ask editor": load the range prefix (render-adjust on a new nonce)
  // and focus the input so typing continues the prompt.
  const [seenPrefill, setSeenPrefill] = useState<number | null>(null);
  if (prefill && prefill.nonce !== seenPrefill) {
    setSeenPrefill(prefill.nonce);
    setText(prefill.text);
  }
  useEffect(() => {
    if (prefill) inputRef.current?.focus();
  }, [prefill]);
  const setRunState = (s: "idle" | "running" | "error") => {
    setState(s);
    onBusyChange?.(s === "running");
  };

  const askClaude = async () => {
    const request = text.trim();
    if (!request || state === "running" || blocked) return;
    const scope = inferSurgicalEditScope(request);
    if (!scope) {
      setRunState("error");
      setMsg("Name the kind of change: cuts, graphics, motion, captions, b-roll, audio, music, or framing.");
      return;
    }
    setRunState("running");
    setMsg(`Applying a governed ${scope.lanes.join(" + ")} edit…`);
    // The CLI edits the DISK plan and the reload replaces memory — unsaved
    // in-memory edits would be silently discarded. Persist them first (mirrors
    // reRender's dirty guard); abort loudly if the save fails.
    if (!(await onBeforeRun())) {
      setRunState("error");
      setMsg("save failed — unsaved edits would be lost; fix the save, then retry");
      return;
    }
    try {
      let refitReceipt = "";
      let palmierCandidate = false;
      const res = await fetch("/api/producer/ai-edit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ dir, request, scope }),
      });
      if (!res.ok) {
        const e = await res.json().catch(() => ({}));
        throw new Error(e.error || `ai-edit ${res.status}`);
      }
      const editMode = res.headers.get("X-Sniper-Edit-Mode");
      if (editMode !== "palmier-native") onInvalidateAuthority();
      await readEventStream(res, (ev) => {
        if (ev.event === "error") throw new Error(String(ev.message));
        if (ev.event === "ai_done") return;
        if (ev.event === "palmier_native_started") {
          setMsg("Reading the current Palmier timeline and planning a non-destructive candidate…");
          return;
        }
        if (ev.event === "palmier_candidate_ready") {
          palmierCandidate = true;
          setMsg("Review-only Palmier candidate created. The preserved parent was restored; review it, then choose Run candidate QC.");
          return;
        }
        if (ev.event === "plan_refit_receipt") {
          refitReceipt = planRefitProgressMessage(ev) ?? "";
          setMsg(refitReceipt);
          return;
        }
        if (ev.event === "surgical_review_started") {
          setMsg("Plan written. Running deterministic validation and a fresh craft critic…");
          return;
        }
        if (ev.event === "surgical_review") {
          setMsg("Edit passed deterministic validation and an independent craft review.");
          return;
        }
        if (ev.type === "assistant") {
          const m = ev.message as { content?: Array<{ type: string; text?: string }> } | undefined;
          const txt = m?.content?.find((c) => c.type === "text");
          if (txt?.text) setMsg(txt.text.slice(0, 200));
        } else if (ev.type === "result" && typeof ev.result === "string") {
          setMsg(ev.result.slice(0, 200));
        }
      }, undefined, "ai_done");
      if (!palmierCandidate && !(await onPlanChanged())) {
        throw new Error("The edit finished, but the updated timeline could not be loaded. Reopen the project before making another change.");
      }
      setRunState("idle");
      setMsg(palmierCandidate
        ? "Palmier candidate ready for manual review only. Opening it does not accept it; the preserved parent remains canonical."
        : refitReceipt
        ? `Governed change added. ${refitReceipt}`
        : "Governed change added. It passed lane scope, plan validation, and an independent critic.");
      setText("");
    } catch (e) {
      setRunState("error");
      setMsg(e instanceof Error ? e.message : "AI edit failed");
    }
  };

  return (
    <section id="revision-request" className="border-y border-emerald-500/20 bg-emerald-950/10 px-4 py-3">
      <div className="flex flex-col gap-3 min-[520px]:flex-row min-[520px]:items-start">
        <div className="shrink-0 min-[520px]:w-44 lg:w-56">
          <label htmlFor="editor-change-request" className="text-sm font-semibold text-emerald-200">
            Tell the editor what to change
          </label>
          <p className="mt-1 text-xs leading-relaxed text-neutral-400">
            Use plain language or a time range. Press ⌘/Ctrl + Enter to apply.
          </p>
        </div>
        <textarea
          id="editor-change-request"
          ref={inputRef}
          value={text}
          rows={2}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) void askClaude();
          }}
          placeholder="Examples: Remove 0:18–0:26. Add a title card at 0:45. Make the first 10 seconds faster."
          disabled={state === "running" || !!blocked}
          title={blocked ?? undefined}
          className="min-h-16 min-w-0 flex-1 resize-y rounded-md border border-neutral-700 bg-neutral-950 px-3 py-2 text-sm text-neutral-100 outline-none placeholder:text-neutral-600 focus:border-emerald-500 disabled:opacity-60"
        />
        <button
          type="button"
          onClick={() => void askClaude()}
          disabled={state === "running" || !text.trim() || !!blocked}
          title={blocked ?? undefined}
          className="shrink-0 rounded-md bg-emerald-500 px-4 py-2 text-sm font-semibold text-neutral-950 enabled:hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {state === "running" ? "Applying edit…" : "Apply edit"}
        </button>
      </div>
      {msg && (
        <p
          role={state === "error" ? "alert" : "status"}
          aria-live="polite"
          className={`mt-2 text-xs ${state === "error" ? "text-rose-400" : "text-neutral-300"}`}
        >
          {msg}
        </p>
      )}
    </section>
  );
}
