"use client";

import type { Dispatch, SetStateAction } from "react";
import type { Preflight } from "./use-palmier-status";
import type { PalmierView } from "./palmier-bar";
import type { PushState } from "./use-palmier-sync";
import CandidateQcControls from "./candidate-qc-controls";
import LiveBuildControls from "./live-build-controls";

interface Chip {
  cls: string;
  text: string;
}

export interface ToolbarState {
  chip: Chip;
  pre: Preflight | null;
  showParity: boolean;
  parityLabel: string;
  parityFullyEditable: boolean;
  parityIssues: number;
  mirrorReady: boolean;
  pushState: PushState;
  pushMessage: string;
  pushBlocked: string | null;
  palmierExportCurrent: boolean;
  renderExists: boolean;
  liveBuildDisabled: boolean;
}

interface ToolbarProps {
  dir: string;
  state: ToolbarState;
  project?: string | null;
  view: PalmierView;
  mode?: "short" | "longform";
  setShowParity: Dispatch<SetStateAction<boolean>>;
  sync: () => Promise<void>;
  onChanged: () => void;
  onViewChange: (view: PalmierView) => void;
}

function ParityButton(props: ToolbarProps) {
  const { pre, showParity, parityIssues, mirrorReady } = props.state;
  if (!pre) return null;
  const label = showParity ? "Hide Palmier check" : props.state.parityFullyEditable
    ? "Palmier controls · all native"
    : mirrorReady ? `Palmier controls · ${parityIssues} limited`
      : `Palmier mirror · ${parityIssues} blockers`;
  return (
    <button type="button" onClick={() => props.setShowParity((shown) => !shown)}
      className="rounded border border-neutral-800 px-2 py-0.5 text-neutral-400 hover:border-neutral-600 hover:text-neutral-200">
      {label}
    </button>
  );
}

function MirrorButton(props: ToolbarProps) {
  const { pre, mirrorReady, pushState, pushBlocked } = props.state;
  const label = pushState === "running" ? "Working…" : pre?.managedWorkspace
    ? "Palmier is current" : mirrorReady ? "Update Palmier mirror" : "Mirror blocked";
  return (
    <button type="button" disabled={pushState === "running" || pushBlocked != null}
      onClick={() => void props.sync()}
      title={pushBlocked ?? "plan_lint → approved visual master → verified Palmier shadow → exact mirror publication"}
      className="rounded border border-neutral-700 px-2 py-0.5 text-neutral-300 transition-colors hover:border-neutral-500 disabled:cursor-not-allowed disabled:opacity-40">
      {label}
    </button>
  );
}

function ViewToggle(props: ToolbarProps) {
  const { pre, palmierExportCurrent, renderExists } = props.state;
  return (
    <div className="ml-auto flex overflow-hidden rounded border border-neutral-800">
      {(["internal", "palmier"] as const).map((candidate) => (
        <button key={candidate} type="button" aria-pressed={props.view === candidate}
          disabled={candidate === "palmier" && !palmierExportCurrent}
          onClick={() => props.onViewChange(candidate)}
          title={candidate === "palmier"
            ? palmierExportCurrent ? `play the verified final.palmier.mp4 export · ${props.state.parityLabel}`
              : pre?.managedWorkspace ? "Palmier owns this fork; its live manual timeline may differ from the last verified mirror"
                : renderExists ? "Palmier export is behind this disk plan — Sync to refresh"
                  : "no verified Palmier export yet"
            : "play the in-house render (final.mp4)"}
          className={`px-2 py-0.5 transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
            props.view === candidate ? "bg-neutral-800 text-neutral-200" : "text-neutral-500 hover:text-neutral-300"
          }`}>
          {candidate === "internal" ? "Sniper preview" : "Last verified Palmier export"}
        </button>
      ))}
    </div>
  );
}

export default function PalmierBarControls(props: ToolbarProps) {
  const { state } = props;
  return (
    <div className="flex items-center gap-2 px-4 py-1.5">
      <span className={`rounded-full border px-2 py-0.5 ${state.chip.cls}`}
        title={props.project ? `active project: ${props.project}` : undefined}>
        {state.chip.text}
      </span>
      <ParityButton {...props} />
      <MirrorButton {...props} />
      {state.pre && <LiveBuildControls dir={props.dir}
        disabled={state.liveBuildDisabled || state.pushState === "running"}
        onChanged={props.onChanged} />}
      {state.pre && <CandidateQcControls dir={props.dir}
        disabled={state.pushState === "running"} mode={props.mode} onChanged={props.onChanged} />}
      {(state.pushMessage || state.pushState === "error") && (
        <span role={state.pushState === "error" ? "alert" : "status"}
          aria-live={state.pushState === "error" ? "assertive" : "polite"}
          className={state.pushState === "error" ? "text-red-400" : "text-neutral-500"}>
          {state.pushMessage}
        </span>
      )}
      {props.view === "palmier" && (
        <span className="text-neutral-400">Watching Palmier export · describe a change below</span>
      )}
      <ViewToggle {...props} />
    </div>
  );
}
