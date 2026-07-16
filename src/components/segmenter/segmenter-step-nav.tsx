"use client";

import { Button } from "@/components/ui/button";

export type SegmenterPageStep = "browse" | "edit" | "export";

interface Props {
  step: SegmenterPageStep;
  hasResults: boolean;
  onBackToReview: () => void;
  onChangeFiles: () => void;
  onStartOver: () => void;
}

const STEPS: ReadonlyArray<{ id: SegmenterPageStep; label: string }> = [
  { id: "browse", label: "Add files" },
  { id: "edit", label: "Review clips" },
  { id: "export", label: "Choose output" },
];

function StepMarker({ id, label, current }: {
  id: SegmenterPageStep;
  label: string;
  current: SegmenterPageStep;
}) {
  const index = STEPS.findIndex((item) => item.id === id);
  const currentIndex = STEPS.findIndex((item) => item.id === current);
  const active = id === current;
  const complete = index < currentIndex;
  return (
    <li aria-current={active ? "step" : undefined} className={`flex flex-1 items-center gap-2 ${active ? "text-cyan-200" : complete ? "text-emerald-300" : "text-neutral-600"}`}>
      <span className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full border text-xs font-semibold ${
        active ? "border-cyan-400 bg-cyan-950" : complete ? "border-emerald-500 bg-emerald-950/40" : "border-neutral-700"
      }`}>
        {complete ? "✓" : index + 1}
      </span>
      <span className="text-xs font-medium sm:text-sm">{label}</span>
    </li>
  );
}

export default function SegmenterStepNav(props: Props) {
  return (
    <div className="mb-8 border-b border-neutral-800 pb-5">
      <ol aria-label="Segmenter progress" className="flex gap-3">
        {STEPS.map((item) => <StepMarker key={item.id} {...item} current={props.step} />)}
      </ol>
      {props.step === "browse" && props.hasResults && (
        <div className="mt-4 flex flex-wrap gap-2">
          <Button type="button" variant="outline" onClick={props.onBackToReview}>← Return to existing clip review</Button>
          <Button type="button" variant="ghost" onClick={props.onStartOver} className="text-neutral-500 hover:text-red-300">Start over</Button>
        </div>
      )}
      {props.step !== "browse" && (
        <div className="mt-4 flex flex-wrap gap-2">
          {props.step === "export" && (
            <Button type="button" variant="outline" onClick={props.onBackToReview}>← Back to clip review</Button>
          )}
          <Button type="button" variant="outline" onClick={props.onChangeFiles}>Change files or instructions</Button>
          <Button type="button" variant="ghost" onClick={props.onStartOver} className="text-neutral-500 hover:text-red-300">Start over</Button>
        </div>
      )}
    </div>
  );
}
