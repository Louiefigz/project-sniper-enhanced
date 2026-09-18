"use client";

import { useState } from "react";
import { dlog } from "@/lib/debug";
import type { SegmentGroup } from "@/lib/types";
import FileBrowser from "@/components/segmenter/file-browser";
import SegmentExportStep from "@/components/segmenter/segment-export-step";
import SegmenterStepNav, { type SegmenterPageStep } from "@/components/segmenter/segmenter-step-nav";
import TranscriptSegmentEditor from "@/components/segmenter/transcript-segment-editor";
import type { SegmenterFlowResult } from "@/components/segmenter/use-segmenter-flow";

interface PageState {
  step: SegmenterPageStep;
  browserKey: number;
  exportReady: boolean;
  result: SegmenterFlowResult | null;
}

const INITIAL_STATE: PageState = {
  step: "browse",
  browserKey: 0,
  exportReady: false,
  result: null,
};

function useSegmenterPage() {
  const [state, setState] = useState<PageState>(INITIAL_STATE);
  const complete = (result: SegmenterFlowResult, browserKey: number) => {
    dlog("segmenter:browse", "transcribe+segment complete → edit step", {
      transcriptLines: result.transcript.length,
      segments: result.segments.length,
      ...result.paths,
    });
    setState((current) => current.browserKey === browserKey
      ? { ...current, step: "edit", exportReady: false, result }
      : current);
  };
  const updateSegments = (segments: SegmentGroup[]) => setState((current) => (
    current.result ? { ...current, result: { ...current.result, segments } } : current
  ));
  const openExport = () => setState((current) => {
    dlog("segmenter:edit", "continue → export step", {
      segments: current.result?.segments.length ?? 0,
      filePath: current.result?.paths.video ?? "",
    });
    return { ...current, step: "export", exportReady: true };
  });
  const startOver = () => {
    const confirmed = window.confirm("Start over? This clears the selected files and the clips you already reviewed.");
    if (!confirmed) return;
    setState((current) => ({ ...INITIAL_STATE, browserKey: current.browserKey + 1 }));
  };
  const go = (step: SegmenterPageStep) => setState((current) => ({ ...current, step }));
  return { state, complete, updateSegments, openExport, startOver, go };
}

export default function Home() {
  const page = useSegmenterPage();
  const { state } = page;
  const result = state.result;
  return (
    <main className="reticle-field grain min-h-screen bg-background text-foreground">
      <div className="max-w-5xl mx-auto px-6 py-8">
        <SegmenterStepNav
          step={state.step}
          hasResults={!!result}
          onBackToReview={() => page.go("edit")}
          onChangeFiles={() => page.go("browse")}
          onStartOver={page.startOver}
        />
        <div hidden={state.step !== "browse"}>
          <FileBrowser
            key={state.browserKey}
            onComplete={(nextResult) => page.complete(nextResult, state.browserKey)}
          />
        </div>
        {result && (
          <div hidden={state.step !== "edit"}>
            <TranscriptSegmentEditor
              transcript={result.transcript}
              segments={result.segments}
              onChange={page.updateSegments}
              onContinue={page.openExport}
            />
          </div>
        )}
        {result && state.exportReady && (
          <div hidden={state.step !== "export"}>
            <SegmentExportStep
              segments={result.segments}
              filePath={result.paths.video}
              bcamPath={result.paths.bcam}
              ccamPath={result.paths.ccam}
              lav1Path={result.paths.lav1}
              lav2Path={result.paths.lav2}
            />
          </div>
        )}
      </div>
    </main>
  );
}
