"use client";

import { useState } from "react";
import { DEFAULT_CONFIG, FrameioStep, ReviewConfig } from "@/lib/frameio/types";
import { dlog } from "@/lib/debug";
import FileBrowser from "@/components/frameio-review/file-browser";
import ConfigStep from "@/components/frameio-review/config-step";
import ReviewWorkspace from "@/components/frameio-review/review-workspace";

export default function FrameioReviewPage() {
  const [step, setStep] = useState<FrameioStep>("select");
  const [filePath, setFilePath] = useState<string | null>(null);
  const [fileName, setFileName] = useState<string | null>(null);
  const [config, setConfig] = useState<ReviewConfig>(DEFAULT_CONFIG);
  // Bump to force a fresh ReviewWorkspace (and a new run) on re-entry.
  const [runKey, setRunKey] = useState(0);

  const goBack = () => {
    setStep((s) => (s === "review" ? "configure" : s === "configure" ? "select" : "select"));
    dlog("frameio:nav", "back");
  };

  return (
    <main className="reticle-field grain min-h-screen bg-background text-foreground">
      <div className="mx-auto max-w-5xl px-6 py-8">
        {step !== "select" && (
          <button
            onClick={goBack}
            className="mb-4 text-sm text-neutral-400 transition-colors hover:text-neutral-200"
          >
            ← Back
          </button>
        )}

        {step === "select" && (
          <FileBrowser
            filePath={filePath}
            fileName={fileName}
            onPicked={(path, name) => {
              setFilePath(path);
              setFileName(name);
            }}
            onContinue={() => setStep("configure")}
          />
        )}

        {step === "configure" && (
          <ConfigStep
            fileName={fileName}
            config={config}
            onChange={setConfig}
            onRun={() => {
              setRunKey((k) => k + 1);
              setStep("review");
            }}
          />
        )}

        {step === "review" && filePath && (
          <ReviewWorkspace key={runKey} filePath={filePath} fileName={fileName} config={config} />
        )}
      </div>
    </main>
  );
}
