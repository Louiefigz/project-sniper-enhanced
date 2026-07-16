"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { SCOPES, type Mode, type Scope } from "@/lib/producer/intent-presets";
import { ActionShell, Spinner, type SseState } from "./stage-action-status";

interface Props {
  dir: string;
  state: SseState;
  run: (operation: SseState["operation"], task: () => Promise<void>) => void;
  primary?: boolean;
}

async function persistIntent(dir: string, mode: Mode, scope: Scope): Promise<void> {
  const response = await fetch("/api/producer/intent", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ dir, intent: { mode, scope, lanes: {}, music: false } }),
  });
  if (response.ok) return;
  const detail = await response.json().catch(() => null) as { error?: string } | null;
  throw new Error(detail?.error || `intent update → ${response.status}`);
}

/** Explicit recovery for projects created before persisted intent existed. */
export default function MissingIntentAction({ dir, state, run, primary = false }: Props) {
  const [mode, setMode] = useState<Mode | "">("");
  const [scope, setScope] = useState<Scope | "">("");
  const save = () => {
    if (!mode || !scope) return;
    run("intent", () => persistIntent(dir, mode, scope));
  };
  return (
    <ActionShell state={state}>
      <select value={mode} onChange={(event) => setMode(event.target.value as Mode | "")}
        className="rounded border border-border bg-background px-1 py-0.5 text-[10px]" aria-label="Video format">
        <option value="">Format…</option><option value="short">Short</option><option value="longform">Long</option>
      </select>
      <select value={scope} onChange={(event) => setScope(event.target.value as Scope | "")}
        className="rounded border border-border bg-background px-1 py-0.5 text-[10px]" aria-label="Edit level">
        <option value="">Edit level…</option>
        {SCOPES.map((value) => <option key={value} value={value}>{value}</option>)}
      </select>
      <Button variant={primary ? "default" : "ghost"} size="xs" disabled={!mode || !scope || state.running} onClick={save}>
        <Spinner on={state.running} /> Save request
      </Button>
    </ActionShell>
  );
}
