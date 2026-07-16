"use client";

import { useState } from "react";
import {
  DEFAULT_SEGMENT_PROMPT,
  segmentPromptForTemplate,
  type SegmentPromptTemplateId,
} from "@/lib/segmenter/file-browser-helpers";
import { FileSelectionPanel } from "./file-selection-panel";
import { FlowProgress } from "./flow-progress";
import { useFileSelection } from "./use-file-selection";
import {
  useSegmenterFlow,
  type CompleteHandler,
} from "./use-segmenter-flow";

interface Props {
  onComplete: CompleteHandler;
}

export default function FileBrowser({ onComplete }: Props) {
  const [prompt, setPrompt] = useState(DEFAULT_SEGMENT_PROMPT);
  const [promptTemplate, setPromptTemplate] = useState<SegmentPromptTemplateId>("topics");
  const selection = useFileSelection();
  const flow = useSegmenterFlow({
    files: selection.slots,
    prompt,
    onComplete,
  });

  if (flow.state.phase !== "browse") {
    return (
      <div className="mx-auto max-w-2xl">
        <FlowProgress
          state={flow.state}
          videoName={selection.slots.a?.name ?? "Selected source"}
          onRetryTranscription={flow.startTranscription}
          onRetrySegmentation={flow.retrySegmentation}
          onBack={flow.backToBrowse}
        />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-2xl">
      <FileSelectionPanel
        files={selection.slots}
        picker={{
          slot: selection.pickingSlot,
          multiple: selection.pickingMulti,
          error: selection.pickError,
          notice: selection.autoNotice,
        }}
        instructions={{
          value: prompt,
          template: promptTemplate,
          onChange: setPrompt,
          onSelectTemplate: (template) => {
            setPromptTemplate(template);
            setPrompt(segmentPromptForTemplate(template));
          },
          onReset: () => setPrompt(segmentPromptForTemplate(promptTemplate)),
        }}
        actions={{
          onPick: selection.pickFileFor,
          onPickMultiple: selection.pickMultiple,
          onClear: selection.clearSlot,
          onStart: flow.startTranscription,
        }}
      />
    </div>
  );
}
