"use client";

import { EditorToolbar, EmptyEditAlert } from "./editor-toolbar";
import { TranscriptPanel } from "./transcript-panel";
import { VideoPreview } from "./video-preview";
import type { VideoEditorProps } from "./video-editor-types";
import { useVideoEditorModel } from "./use-video-editor-model";

export default function VideoEditor(props: VideoEditorProps) {
  const model = useVideoEditorModel(props);
  const { data, playback, selection } = model;
  return (
    <div className="flex flex-col select-none" style={{ height: "calc(100vh - 160px)" }}>
      <EditorToolbar exportDuration={data.exportDuration}
        selectedCount={selection.selectedIds.size}
        selectionHasRemoved={selection.selectionHasRemoved}
        canExport={data.canExport} onCut={selection.cutSelection}
        onRestore={selection.restoreSelection} onDebugDownload={model.onDebugDownload}
        onContinue={props.onContinue} />
      {!data.canExport && <EmptyEditAlert />}
      <div className="flex gap-4 flex-1 min-h-0">
        {props.videoSrc && (
          <VideoPreview videoSrc={props.videoSrc} videoRef={playback.videoRef}
            onPlay={playback.playCurrentSegment} onPause={playback.pause} />
        )}
        <TranscriptPanel groups={data.groups} selectedIds={selection.selectedIds}
          onSeek={playback.seekTo} onToggleGroup={model.onToggleGroup}
          onWordMouseDown={selection.onWordMouseDown}
          onWordMouseEnter={selection.onWordMouseEnter} />
      </div>
    </div>
  );
}
