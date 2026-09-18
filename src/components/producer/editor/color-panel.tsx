"use client";
import type { EditPlan } from "@/lib/producer/edit-plan";
import ColorSourceControls from "./color-source-controls";
import ColorResult from "./color-result";
import { useColorDiagnostic } from "./use-color-diagnostic";
import { colorResultMatchesContexts } from "@/lib/producer/color-diagnostic-client";

export default function ColorPanel({ dir, plan }: { dir: string; plan: EditPlan }) {
  const state = useColorDiagnostic(dir, plan.cutTrack);
  const blocked = state.loading || state.busy || state.unresolved || state.storageBlocked || !state.savedCutMatches || !!state.descriptor?.blockers.length || !state.descriptor;
  return <div className="space-y-4 p-3 text-xs">
    <div className="space-y-2">
      <h3 className="font-medium text-neutral-200">Source color check</h3>
      <p className="text-neutral-400">Screen sampled retained footage across the saved timeline. This does not grade or change your video.</p>
      <p className="text-[10px] text-amber-200">Only positively identified limited-range 8-bit BT.709 frames can be measured. Unknown, Log, HDR, or conflicting frame metadata will not be transformed.</p>
      <p className="text-[10px] text-neutral-500">Primary footage only. B-roll, graphics, skin tones, shot matching, and final delivery color are not qualified by this diagnostic.</p>
    </div>
    <button disabled={state.busy || state.loading} onClick={() => void state.refresh()}
      className="rounded border border-neutral-700 px-2 py-1 text-neutral-300 disabled:opacity-40">{state.loading ? "Loading saved sources…" : "Refresh saved sources"}</button>
    {state.error && <p role="alert" className="break-words text-red-300">{state.error}</p>}
    {state.activeId && <button onClick={() => void state.recheck()} className="rounded border border-neutral-700 px-2 py-1 text-neutral-300">Recheck retained job</button>}
    {!state.loading && !state.savedCutMatches && <p className="text-amber-200">Save your timeline changes, then refresh saved sources before checking color.</p>}
    {state.descriptor?.blockers.map((item, i) => <p key={i} role="alert" className="text-amber-200">{item}</p>)}
    {state.descriptor?.sources.map((source, index) => state.contexts[index] && <ColorSourceControls key={source.id}
      source={source} value={state.contexts[index]} disabled={state.busy}
      onChange={value => state.setContexts(rows => rows.map((row, i) => i === index ? value : row))} />)}
    {!!state.descriptor?.projectHistory.length && <details><summary className="cursor-pointer text-neutral-400">Project processing history</summary>
      <p className="mt-1 text-[10px] text-neutral-500">Provenance notes, not verified color transform history.</p>
      {state.descriptor.projectHistory.map((row, i) => <p key={i} className="break-words text-[10px] text-neutral-500">{row.stage} · {row.at}</p>)}
    </details>}
    <button disabled={blocked} onClick={() => void state.start()} className="w-full rounded border border-emerald-600 bg-emerald-900/30 px-3 py-2 text-emerald-200 disabled:cursor-not-allowed disabled:opacity-40">
      {state.busy ? "Checking color — worker owned…" : "Run private color check"}
    </button>
    {state.busy && <p role="status" className="text-neutral-400">No queue. Closing this panel does not abandon the bounded worker; reopen to view its status. Other project writes wait until cleanup completes.</p>}
    {state.job && <ColorResult job={state.job} contextsCurrent={colorResultMatchesContexts(state.job, state.contexts)} />}
  </div>;
}
