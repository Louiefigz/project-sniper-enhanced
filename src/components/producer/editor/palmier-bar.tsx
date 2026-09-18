"use client";

import { useCallback, useEffect, useState } from "react";
import type { EditPlan } from "@/lib/producer/edit-plan";
import type { StreamEvent } from "@/lib/producer/types";
import PalmierBarControls, { type ToolbarState } from "./palmier-bar-controls";
import PalmierParityReport from "./palmier-parity-report";
import { palmierMirrorReady, palmierParityBlock,
  palmierParityIssueCount, palmierParityState } from "./palmier-parity";
import { usePalmierStatus, type Preflight } from "./use-palmier-status";
import { usePalmierSync } from "./use-palmier-sync";

export type PalmierView = "internal" | "palmier";

interface Props {
  dir: string;
  dirty: boolean;
  sniperPreviewCurrent: boolean;
  plan: EditPlan;
  busyBlocked: string | null;
  view: PalmierView;
  onViewChange: (view: PalmierView) => void;
  onPushed: () => void;
  onProjectStatusChanged?: () => void;
  onWarningEvent: (event: StreamEvent) => void;
}

interface DerivedInput {
  up: boolean | null;
  dirty: boolean;
  sniperPreviewCurrent: boolean;
  busyBlocked: string | null;
  projectPath: string | null;
  renderExists: boolean;
  pre: Preflight | null;
}

function derivedToolbar(input: DerivedInput, showParity: boolean): Omit<ToolbarState,
  "pushState" | "pushMessage"> {
  const { pre } = input;
  const projectMismatch = Boolean(
    pre?.targetProjectPath && input.projectPath && pre.targetProjectPath !== input.projectPath,
  );
  const parity = palmierParityState(pre?.parity);
  const mirrorReady = palmierMirrorReady(pre?.parity);
  const mismatch = projectMismatch
    ? `open ${pre?.targetProject ?? "the target project"} in Palmier first` : null;
  const pushBlocked = input.busyBlocked
    ?? (input.up === false ? "Palmier app is not running — open it with the target project" : null)
    ?? mismatch ?? (input.dirty ? "save first — sync reads the disk plan" : null)
    ?? (!input.sniperPreviewCurrent ? "render and approve the saved Sniper plan before mirroring it" : null)
    ?? (!pre ? "wait for the Palmier compatibility check" : null)
    ?? (pre?.managedWorkspace ? "Palmier is the working source of truth — edit there or use Ask AI" : null)
    ?? (pre && !pre.ok ? short(pre.blocked) ?? "plan not translatable" : null)
    ?? (pre ? palmierParityBlock(pre.parity) : null);
  return {
    chip: chipState({ up: input.up, dirty: input.dirty, pre, projectMismatch }),
    pre, showParity, parityLabel: parity.label, parityFullyEditable: parity.fullyEditable,
    parityIssues: palmierParityIssueCount(pre?.parity), mirrorReady, pushBlocked,
    renderExists: input.renderExists,
    liveBuildDisabled: input.busyBlocked != null || input.dirty || input.up !== true
      || projectMismatch || !pre?.managedWorkspace,
    palmierExportCurrent: Boolean(input.renderExists && pre?.exportVerified
      && pre.syncState === "in_sync" && !input.dirty && input.sniperPreviewCurrent),
  };
}

export default function PalmierBar(props: Props) {
  const [showParity, setShowParity] = useState(false);
  const palmier = usePalmierStatus({ dir: props.dir, plan: props.plan });
  const { onProjectStatusChanged, onViewChange, view } = props;
  const { refreshPreflight, refreshProbe } = palmier;
  const base = derivedToolbar({
    up: palmier.up, dirty: props.dirty, sniperPreviewCurrent: props.sniperPreviewCurrent,
    busyBlocked: props.busyBlocked, projectPath: palmier.projectPath,
    renderExists: palmier.renderExists, pre: palmier.pre,
  }, showParity);
  const sync = usePalmierSync({ dir: props.dir, markRenderExists: palmier.markRenderExists,
    refreshPreflight: palmier.refreshPreflight, onPushed: props.onPushed,
    onWarningEvent: props.onWarningEvent });
  const state: ToolbarState = { ...base, pushState: sync.state, pushMessage: sync.message };
  useEffect(() => {
    if (view === "palmier" && !state.palmierExportCurrent) onViewChange("internal");
  }, [onViewChange, state.palmierExportCurrent, view]);
  const onChanged = useCallback(() => {
    refreshProbe();
    void refreshPreflight();
    onProjectStatusChanged?.();
  }, [onProjectStatusChanged, refreshPreflight, refreshProbe]);
  const mode = props.plan.target?.mode === "short" ? "short"
    : props.plan.target?.mode === "longform" ? "longform" : undefined;
  return (
    <div className="border-b border-neutral-800 bg-neutral-900/50 text-[11px]">
      <PalmierBarControls dir={props.dir} state={state} project={palmier.project}
        view={props.view} mode={mode} setShowParity={setShowParity}
        sync={sync.sync} onChanged={onChanged} onViewChange={props.onViewChange} />
      {palmier.pre && showParity && <PalmierParityReport parity={palmier.pre.parity}
        notes={palmier.pre.warnings ?? []} blocked={palmier.pre.blocked}
        onClose={() => setShowParity(false)} />}
    </div>
  );
}

function chipState(input: {
  up: boolean | null;
  dirty: boolean;
  pre: Preflight | null;
  projectMismatch: boolean;
}) {
  const { up, dirty, pre, projectMismatch } = input;
  if (up === null) return { cls: "border-neutral-700 text-neutral-500", text: "Checking Palmier…" };
  if (!up) return { cls: "border-neutral-700 text-neutral-500", text: "Palmier is closed" };
  if (dirty) return { cls: "border-neutral-600 text-neutral-400", text: "Save changes before sending" };
  if (!pre) return { cls: "border-neutral-700 text-neutral-500", text: "Checking Palmier compatibility…" };
  if (pre.managedWorkspace) {
    return { cls: "border-emerald-800 text-emerald-300", text: "Palmier is the working source of truth" };
  }
  if (pre.error || (!pre.ok && !pre.blocked))
    return { cls: "border-red-800 text-red-400", text: `Palmier check failed: ${pre.error ?? "unknown error"}` };
  if (!pre.ok) return { cls: "border-red-800 text-red-400", text: `Cannot send: ${short(pre.blocked)}` };
  if (projectMismatch)
    return { cls: "border-amber-700 text-amber-400", text: "Open the matching Palmier project" };
  if (pre.syncState === "in_sync")
    return { cls: "border-emerald-800 text-emerald-400", text: "Palmier mirror is current and verified" };
  if (pre.syncState === "behind")
    return { cls: "border-amber-700 text-amber-400", text: "A newer edit is ready to send" };
  return { cls: "border-neutral-700 text-neutral-400", text: "Ready to mirror in Palmier" };
}

function short(message: string | undefined): string | undefined {
  if (!message) return undefined;
  return message.length > 90 ? `${message.slice(0, 87)}…` : message;
}
