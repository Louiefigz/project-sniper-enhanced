"use client";

import { useState, useEffect, useRef, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import type { AssetManifest, ProducerStep } from "@/lib/producer/types";
import type { IntentCapabilityDecision } from "@/lib/producer/intent-capabilities";
import type { ProjectIntent, ReferenceIntent } from "@/lib/producer/intent-presets";
import { parsePlan, reconcileGraphicIds, type EditPlan } from "@/lib/producer/edit-plan";
import { dlog } from "@/lib/debug";
import SourceStep from "@/components/producer/source-step";
import ManifestStep from "@/components/producer/manifest-step";
import RenderStep from "@/components/producer/render-step";
import RecentProjects from "@/components/producer/recent-projects";
import ReferencesSection from "@/components/producer/references-section";
import EditorView from "@/components/producer/editor/editor-view";

interface IngestResult {
  inputPath: string;
  manifestPath: string;
  outDir: string;
  manifest: AssetManifest;
  requestedIntent?: ProjectIntent;
  intent?: ProjectIntent;
  intentDecisions?: IntentCapabilityDecision[];
}

interface EditorTarget {
  plan: EditPlan;
  dir: string;
  title: string;
}

async function loadEditorTarget(dir: string, displayName?: string, signal?: AbortSignal): Promise<EditorTarget> {
  const clean = dir.replace(/\/$/, "");
  const response = await fetch(`/api/producer/plan?path=${encodeURIComponent(`${clean}/edit_plan.json`)}`, { signal });
  if (!response.ok) throw new Error(String(response.status));
  const parsed = parsePlan(await response.text());
  if (!parsed) throw new Error("plan is not valid JSON");
  const plan = reconcileGraphicIds(parsed).plan;
  const parts = clean.split("/");
  const title = parts.at(-1) === "producer" ? parts.at(-2) : parts.at(-1);
  return { plan, dir: clean, title: displayName || title || "render" };
}

function openFailure(reason: unknown): string {
  return `Could not open project: ${reason instanceof Error ? reason.message : String(reason)}`;
}

// PRODUCER (Part 3) live-app surface. A thin UI over the ingest → lint → render
// Python stages; plan generation (the brain) stays in the `producer` skill. The
// `edit` step is the Phase 1 timeline-review editor (slice 1: read-only).
function ProducerPage() {
  const params = useSearchParams();
  const [step, setStep] = useState<ProducerStep>("select");
  const [ingest, setIngest] = useState<IngestResult | null>(null);
  const [planText, setPlanText] = useState<string>("");
  const [editor, setEditor] = useState<EditorTarget | null>(null);
  const [openError, setOpenError] = useState<string | null>(null);
  const [referenceIntent, setReferenceIntent] = useState<ReferenceIntent | null>(null);
  const openRequestRef = useRef<AbortController | null>(null);

  // Open a finished render dir in the editor (reads <dir>/edit_plan.json,
  // plays <dir>/final.mp4) — used by the ?open= deep-link AND Recent edits.
  const openRenderDir = (dir: string, displayName?: string) => {
    openRequestRef.current?.abort();
    const controller = new AbortController();
    openRequestRef.current = controller;
    setOpenError(null);
    loadEditorTarget(dir, displayName, controller.signal)
      .then((target) => {
        if (controller.signal.aborted || openRequestRef.current !== controller) return;
        setEditor(target);
        setStep("edit");
      })
      .catch((reason) => {
        if (controller.signal.aborted) return;
        const message = openFailure(reason);
        setOpenError(message);
        dlog("producer:open", "failed", { error: message });
      });
  };

  // Deep-link: /producer?open=<render out dir> reopens a finished render.
  const openDir = params.get("open");
  useEffect(() => {
    if (!openDir) return;
    const controller = new AbortController();
    loadEditorTarget(openDir, undefined, controller.signal)
      .then((target) => {
        if (controller.signal.aborted) return;
        setEditor(target);
        setStep("edit");
      })
      .catch((reason) => {
        if (controller.signal.aborted) return;
        setOpenError(openFailure(reason));
      });
    return () => controller.abort();
  }, [openDir]);

  const goBack = () => {
    openRequestRef.current?.abort();
    setStep((s) => (s === "edit" ? "render" : s === "render" ? "manifest" : "select"));
    dlog("producer:nav", "back");
  };

  const closeEditor = () => {
    if (ingest) return goBack();
    setEditor(null);
    setStep("select");
  };

  const selectReference = (intent: ReferenceIntent) => {
    setReferenceIntent(intent);
    dlog("producer:references", "selected for next edit", { id: intent.id, mode: intent.mode, strategy: intent.strategy });
    requestAnimationFrame(() => document.getElementById("producer-source")?.scrollIntoView({ behavior: "smooth", block: "start" }));
  };

  // The editor is a full-bleed app surface — render it outside the narrow column.
  if (step === "edit" && editor) {
    return (
      <EditorView
        plan={editor.plan}
        dir={editor.dir}
        title={editor.title}
        onBack={closeEditor}
      />
    );
  }

  return (
    <main className="reticle-field grain min-h-screen bg-background text-foreground">
      <div className="mx-auto max-w-3xl px-6 py-8">
        {step !== "select" && <div className="mb-4">
          <button onClick={goBack} className="text-sm text-neutral-400 transition-colors hover:text-neutral-200">
            ← Previous step
          </button>
        </div>}

        {step === "select" && (
          <>
            {openError && (
              <p className="mb-4 rounded border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
                {openError}
              </p>
            )}
            <SourceStep
              referenceIntent={referenceIntent}
              onReferenceCleared={() => setReferenceIntent(null)}
              onIngested={(res) => {
                setIngest(res);
                setReferenceIntent(null);
                setStep("manifest");
              }}
            />
            <RecentProjects
              onOpen={openRenderDir}
              onIngested={(res) => {
                setIngest(res);
                setReferenceIntent(null);
                setStep("manifest");
              }}
            />
            <ReferencesSection
              selectedId={referenceIntent?.id}
              onSelect={selectReference}
              onClearSelection={() => setReferenceIntent(null)}
            />
          </>
        )}

        {step === "manifest" && ingest && (
          <ManifestStep
            key={`${ingest.manifestPath}:${ingest.intent?.mode ?? "short"}:${ingest.intent?.music === true ? "music" : "silent"}`}
            manifest={ingest.manifest}
            manifestPath={ingest.manifestPath}
            outDir={ingest.outDir}
            intent={ingest.intent}
            intentDecisions={ingest.intentDecisions}
            onAutoEditDone={() => openRenderDir(ingest.outDir)}
            onRender={(text) => {
              setPlanText(text);
              setStep("render");
            }}
          />
        )}

        {step === "render" && ingest && (
          <RenderStep
            planText={planText}
            outDir={ingest.outDir}
            onOpenEditor={() => openRenderDir(ingest.outDir, ingest.inputPath.split("/").pop())}
          />
        )}
      </div>
    </main>
  );
}

export default function ProducerPageWrapper() {
  return (
    <Suspense fallback={<main className="min-h-[60vh] px-6 py-12 text-center text-sm text-muted-foreground" role="status">Loading your projects…</main>}>
      <ProducerPage />
    </Suspense>
  );
}
