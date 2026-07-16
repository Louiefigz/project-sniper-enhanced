"use client";

import { Button } from "@/components/ui/button";
import { formatDuration } from "./video-editor-utils";

interface ToolbarProps {
  exportDuration: number;
  selectedCount: number;
  selectionHasRemoved: boolean;
  canExport: boolean;
  onCut: () => void;
  onRestore: () => void;
  onDebugDownload: () => void;
  onContinue: () => void;
}

interface ShortcutHintProps {
  keys: string;
  label: string;
  keyClassName: string;
}

function ShortcutHint({ keys, label, keyClassName }: ShortcutHintProps) {
  return (
    <span className="flex items-center gap-1 text-xs text-neutral-600">
      <kbd className={`px-1.5 py-0.5 rounded bg-neutral-800 border border-neutral-700 font-sans ${keyClassName}`}>
        {keys}
      </kbd>
      <span>{label}</span>
    </span>
  );
}

function ShortcutHints() {
  return (
    <>
      <ShortcutHint keys="⌫" label="Delete" keyClassName="text-red-400" />
      <ShortcutHint keys="R" label="Restore" keyClassName="text-green-400" />
      <ShortcutHint keys="Speaker" label="Toggle line" keyClassName="text-green-400" />
      <span className="flex items-center gap-1 text-xs text-neutral-600">
        <span>click word +</span>
        <kbd className="px-1.5 py-0.5 rounded bg-neutral-800 border border-neutral-700 font-sans text-neutral-400">
          Space
        </kbd>
        <span>= play from that point</span>
      </span>
    </>
  );
}

function SelectionActions(props: Pick<ToolbarProps, "selectedCount" | "selectionHasRemoved" | "onCut" | "onRestore">) {
  if (!props.selectedCount) return null;
  return (
    <>
      <span className="text-neutral-700">·</span>
      <button onMouseDown={(event) => event.preventDefault()} onClick={props.onCut}
        className="text-sm text-red-400 hover:text-red-300 transition-colors">
        Delete
      </button>
      {props.selectionHasRemoved && (
        <button onMouseDown={(event) => event.preventDefault()} onClick={props.onRestore}
          className="text-sm text-green-400 hover:text-green-300 transition-colors">
          Restore
        </button>
      )}
    </>
  );
}

function ExportActions(props: Pick<ToolbarProps, "canExport" | "onDebugDownload" | "onContinue">) {
  const exportTitle = props.canExport
    ? "Continue to Final Cut Pro timeline export"
    : "Restore at least one word before exporting";
  return (
    <div className="flex items-center gap-2 shrink-0">
      <Button variant="outline" onClick={props.onDebugDownload}
        className="border-neutral-700 text-neutral-400 hover:text-white text-xs px-3"
        title="Download word-level debug transcript">
        ↓ Debug TXT
      </Button>
      <Button onClick={props.onContinue} disabled={!props.canExport} title={exportTitle}
        className="bg-amber-600 text-white hover:bg-amber-500 font-semibold disabled:opacity-30 disabled:cursor-not-allowed">
        Continue to FCPXML export →
      </Button>
    </div>
  );
}

export function EditorToolbar(props: ToolbarProps) {
  return (
    <div className="flex items-center justify-between mb-3">
      <div className="flex items-center gap-3 flex-wrap">
        <span className="text-sm text-neutral-400">Duration: ~{formatDuration(props.exportDuration)}</span>
        <span className="text-neutral-700">·</span>
        <ShortcutHints />
        <SelectionActions {...props} />
      </div>
      <ExportActions {...props} />
    </div>
  );
}

export function EmptyEditAlert() {
  return (
    <div role="alert" className="mb-3 rounded-lg border border-red-800/50 bg-red-950/25 px-3 py-2 text-sm text-red-300">
      Nothing remains in the edit. Restore at least one word before continuing to export.
    </div>
  );
}
