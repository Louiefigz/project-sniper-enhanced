"use client";

import { useState } from "react";
import AskClaudeBar from "./ask-claude-bar";
import EditorHeader from "./editor-header";
import EditorLockOverlay from "./editor-lock-overlay";
import GraphicPreview from "./graphic-preview";
import GraphicProperties from "./graphic-properties";
import PalmierBar from "./palmier-bar";
import PlayerPane from "./player-pane";
import RightRail from "./right-rail";
import Timeline from "./timeline";
import TranscriptPanel from "./transcript-panel";
import WarningsStrip from "./warnings-strip";
import type { EditorController } from "./use-editor-controller";

interface SurfaceProps {
  editor: EditorController;
  title?: string;
  onBack?: () => void;
  onProjectStatusChanged?: () => void;
}

export function confirmedBack(onBack: (() => void) | undefined, dirty: boolean,
  confirmDiscard = () => window.confirm("Discard unsaved timeline changes and return to projects?")) {
  if (!onBack) return undefined;
  return () => {
    if (!dirty || confirmDiscard()) onBack();
  };
}

function EditorHeaderSection({ editor, title, onBack, onProjectStatusChanged }: SurfaceProps) {
  const {
    history, actions, undo, redo, saveBlocked,
    externalLockReason, palmierLockReason, mutationLockReason,
  } = editor.planState;
  const palmier = editor.ui.palmierView === "palmier";
  const previewAuthority = palmier ? "current" : actions.previewAuthority;
  const unapproved = !palmier && actions.previewAuthority === "unapproved";
  const lockReason = mutationLockReason ?? (editor.ui.aiBusy
    ? "The editor is applying your request to the timeline."
    : actions.reState === "running" ? "The updated video is rendering." : null);
  return (
    <>
      <EditorLockOverlay
        reason={lockReason}
        palmierPrimary={externalLockReason == null && palmierLockReason != null}
      />
      <EditorHeader
        title={title}
        producerDir={editor.paths.base}
        onBack={confirmedBack(onBack, history.dirty)}
        reState={actions.reState}
        reMsg={actions.reMsg}
        saveState={actions.saveState}
        dirty={history.dirty}
        previewAuthority={previewAuthority}
        canUndo={!editor.planState.editingLocked && history.canUndo}
        canRedo={!editor.planState.editingLocked && history.canRedo}
        saveBlocked={saveBlocked}
        reBlocked={mutationLockReason
          ?? (editor.ui.aiBusy ? "AI editor is editing the plan — re-render when it finishes" : null)}
        snapshotCount={actions.snapshotCount}
        onUndo={undo}
        onRedo={redo}
        onSave={actions.save}
        onReRender={actions.reRender}
        onStudioDraftInvalidated={actions.invalidatePreviewAuthority}
        onStudioDraftChanged={async () => {
          actions.invalidatePreviewAuthority();
          editor.ui.setPalmierView("internal");
          const reloaded = await actions.reloadPlan(true);
          if (!reloaded) actions.addWarningEvent({ status: "warning",
            message: "Studio may have saved a newer draft, but reload failed. Reopen the editor before editing; the preview remains out of date." });
          onProjectStatusChanged?.();
          return reloaded;
        }}
        revealLabel={palmier ? "Show Palmier export" : unapproved ? "Show review copy" : "Show Sniper final"}
        revealTitle={palmier
          ? "opens Finder at the last verified Palmier export"
          : unapproved ? "opens Finder at the unapproved Sniper review copy"
          : "opens Finder at the approved Sniper deliverable"}
        onReveal={() => void actions.revealFinal(palmier ? "palmier" : "sniper")}
      />
    </>
  );
}

function PalmierSection({
  editor, onProjectStatusChanged,
}: Pick<SurfaceProps, "editor" | "onProjectStatusChanged">) {
  const { history, actions, externalLockReason } = editor.planState;
  const [expanded, setExpanded] = useState(false);
  const legacyActive = editor.ui.palmierView === "palmier" || editor.planState.palmierLockReason != null;
  const busyBlocked = externalLockReason ?? (actions.reState === "running"
    ? "re-render is running — push when it finishes"
    : editor.ui.aiBusy ? "AI editor is editing the plan — push when it finishes" : null);
  return (
    <>
      <details open={expanded || legacyActive} onToggle={(event) => setExpanded(event.currentTarget.open)}
        className="border-b border-neutral-800 px-4 py-1 text-xs text-neutral-400">
      <summary className="cursor-pointer">Legacy Palmier tools</summary>
      {(expanded || legacyActive) && <PalmierBar
        dir={editor.paths.base}
        dirty={history.dirty}
        sniperPreviewCurrent={actions.previewAuthority === "current"}
        plan={history.plan}
        busyBlocked={busyBlocked}
        view={editor.ui.palmierView}
        onViewChange={editor.ui.setPalmierView}
        onPushed={() => {
          editor.ui.setPalmierVersion((version) => version + 1);
          onProjectStatusChanged?.();
        }}
        onProjectStatusChanged={onProjectStatusChanged}
        onWarningEvent={actions.addWarningEvent}
      />}
      </details>
      <WarningsStrip warnings={actions.warnings} onDismiss={actions.dismissWarnings} />
    </>
  );
}

function TranscriptPane({ editor }: Pick<SurfaceProps, "editor">) {
  const { plan } = editor.planState.history;
  return (
    <aside className="flex w-[34%] min-h-0 shrink-0 flex-col border-r border-neutral-800 p-4 text-sm">
      <TranscriptPanel
        srtPath={editor.paths.srtPath}
        dir={editor.paths.base}
        cutTrack={plan.cutTrack ?? []}
        currentTime={editor.playback.currentTime}
        onSeek={editor.playback.seek}
        onCutRanges={editor.graphics.cutRanges}
        onRestoreRanges={editor.graphics.restoreRanges}
        onApplyCutTrack={editor.graphics.applyCutTrack}
        onWarning={editor.planState.actions.addWarningEvent}
        locked={editor.planState.editingLocked}
      />
    </aside>
  );
}

function PreviewPane({ editor }: Pick<SurfaceProps, "editor">) {
  const palmier = editor.ui.palmierView === "palmier";
  const palmierPath = `${editor.paths.base}/final.palmier.mp4`;
  const videoPath = palmier ? palmierPath : editor.paths.videoPath;
  const proxyPath = palmier ? palmierPath : editor.paths.proxyPath;
  const version = palmier ? 1_000_000 + editor.ui.palmierVersion : editor.planState.actions.vVersion;
  const previewAuthority = palmier ? "current" : editor.planState.actions.previewAuthority;
  return (
    <PlayerPane
      videoRef={editor.playback.videoRef}
      videoPath={videoPath}
      proxyPath={proxyPath}
      vVersion={version}
      previewAuthority={previewAuthority}
      onTime={editor.playback.onTime}
      onDuration={(duration) => editor.playback.setDuration((previous) => duration || previous)}
    >
      {editor.selectedGraphicLive && (
        <GraphicPreview
          key={editor.ui.selected}
          graphic={editor.selectedGraphicLive}
          currentTime={editor.playback.currentTime}
          videoRef={editor.playback.videoRef}
          forced={editor.ui.previewForced}
          onCommitPlacement={editor.commitPlacement}
        />
      )}
    </PlayerPane>
  );
}

function EditorWorkspace({ editor }: Pick<SurfaceProps, "editor">) {
  return (
    <div className="flex min-h-72 flex-1">
      <TranscriptPane editor={editor} />
      <PreviewPane editor={editor} />
      <RightRail
        plan={editor.planState.history.plan}
        dir={editor.paths.base}
        playhead={editor.playback.currentTime}
        onMutate={editor.planState.history.mutatePlan}
        onAddGraphic={editor.graphics.addGraphic}
        openRequest={editor.ui.railRequest}
        pendingInsert={editor.graphics.pendingInsert}
        onClearPending={() => editor.graphics.setPendingInsert(null)}
        locked={editor.planState.editingLocked}
        lockedReason={editor.planState.mutationLockReason}
      />
    </div>
  );
}

function SelectedGraphicEditor({ editor }: Pick<SurfaceProps, "editor">) {
  if (!editor.selectedGraphic || editor.ui.selected == null) return null;
  return (
    <div className={editor.planState.editingLocked ? "pointer-events-none opacity-60" : undefined}>
      <GraphicProperties
        key={editor.ui.selected}
        graphic={editor.selectedGraphic}
        id={editor.ui.selected}
        duration={editor.playback.duration}
        onChange={editor.graphics.updateGraphic}
        onRemove={editor.graphics.removeGraphic}
        previewForced={editor.ui.previewForced}
        onTogglePreview={() => editor.ui.setPreviewForced((forced) => !forced)}
      />
    </div>
  );
}

function AskEditor({ editor }: Pick<SurfaceProps, "editor">) {
  const blocked = editor.planState.externalLockReason ?? (editor.planState.actions.reState === "running"
    ? "re-render is running — the AI editor would edit the plan mid-rewrite"
    : null);
  return (
    <AskClaudeBar
      dir={editor.paths.base}
      blocked={blocked}
      prefill={editor.ui.askPrefill}
      onBusyChange={editor.ui.setAiBusy}
      onInvalidateAuthority={() => {
        editor.planState.actions.invalidatePreviewAuthority();
        editor.ui.setPalmierView("internal");
      }}
      onBeforeRun={async () => editor.planState.palmierLockReason
        ? true
        : editor.planState.history.dirty ? editor.planState.actions.save() : true}
      onPlanChanged={() => editor.planState.actions.reloadPlan(true)}
    />
  );
}

function EditorTimeline({ editor }: Pick<SurfaceProps, "editor">) {
  const palmier = editor.ui.palmierView === "palmier";
  const palmierPrimary = editor.planState.palmierLockReason != null;
  const videoPath = palmier
    ? `${editor.paths.base}/final.palmier.mp4`
    : ["current", "unapproved"].includes(editor.planState.actions.previewAuthority)
      ? editor.paths.videoPath : undefined;
  const version = palmier
    ? 1_000_000 + editor.ui.palmierVersion
    : editor.planState.actions.vVersion;
  return (
    <Timeline
      plan={editor.planState.history.plan}
      duration={editor.playback.duration}
      currentTime={editor.playback.currentTime}
      onSeek={editor.playback.seek}
      selectedGraphic={editor.ui.selected}
      onSelectGraphic={editor.ui.setSelected}
      videoPath={videoPath}
      vVersion={version}
      artifactLabel={palmier ? "Last verified Palmier export"
        : palmierPrimary ? "Sniper reference preview · Palmier is current"
        : editor.planState.actions.previewAuthority === "unapproved"
          ? "Unapproved Sniper review copy" : "Sniper preview"}
      showPlanLanes={!palmier && !palmierPrimary}
      onCommitWindow={editor.graphics.commitGraphicWindow}
      onDragWindow={editor.ui.setDragWindow}
      onSplit={editor.graphics.splitAtPlayhead}
      onCutRange={editor.graphics.cutRange}
      onAskRange={editor.ranges.ask}
      onAddRange={editor.ranges.add}
      locked={editor.planState.editingLocked || palmier}
    />
  );
}

export default function EditorSurface(props: SurfaceProps) {
  return (
    <div className="relative flex min-h-screen flex-col bg-neutral-950 text-neutral-100">
      <EditorHeaderSection {...props} />
      <PalmierSection
        editor={props.editor}
        onProjectStatusChanged={props.onProjectStatusChanged}
      />
      <EditorWorkspace editor={props.editor} />
      <SelectedGraphicEditor editor={props.editor} />
      <AskEditor editor={props.editor} />
      <EditorTimeline editor={props.editor} />
    </div>
  );
}
