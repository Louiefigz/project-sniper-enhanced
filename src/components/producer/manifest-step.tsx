"use client";

import { useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, FileVideo, Info, Loader2, Music, Images } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import {
  summarizeManifestMusic,
  type AssetManifest,
  type LintVerdict,
} from "@/lib/producer/types";
import type { IntentCapabilityDecision } from "@/lib/producer/intent-capabilities";
import type { ProjectIntent } from "@/lib/producer/intent-presets";
import { buildStarterPlan } from "@/lib/producer/intent-flow";
import { dlog } from "@/lib/debug";
import AutoEditLaunch from "./auto-edit-launch";

export default function ManifestStep({
  manifest,
  manifestPath,
  outDir,
  intent,
  intentDecisions = [],
  onAutoEditDone,
  onRender,
}: {
  manifest: AssetManifest;
  manifestPath: string;
  outDir: string;
  intent?: ProjectIntent;
  intentDecisions?: IntentCapabilityDecision[];
  onAutoEditDone: () => void;
  onRender: (planText: string) => void;
}) {
  const [planText, setPlanText] = useState(() => (
    intent ? JSON.stringify(buildStarterPlan(manifest, intent), null, 2) : ""
  ));
  const [verdict, setVerdict] = useState<LintVerdict | null>(null);
  const [linting, setLinting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const lint = async () => {
    setLinting(true);
    setError(null);
    setVerdict(null);
    dlog("producer:lint", "run", { manifestPath });
    try {
      const res = await fetch("/api/producer/lint", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ planJson: planText, manifestPath }),
      });
      const data = await res.json();
      if (data.error && data.ok === undefined) throw new Error(data.error);
      setVerdict(data as LintVerdict);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Lint failed");
    } finally {
      setLinting(false);
    }
  };

  const sources = manifest.sources ?? [];
  const summary = useMemo(() => ({
    sources: sources.length,
    broll: manifest.broll?.length ?? 0,
    music: summarizeManifestMusic(manifest.music),
  }), [manifest.broll, manifest.music, sources.length]);

  return (
    <div className="rise-in space-y-6">
      <div>
        <h1 className="font-display text-2xl font-bold tracking-tight">Your media is ready</h1>
        <p className="mt-1 text-sm text-muted-foreground">Review the summary, then create the finished video.</p>
      </div>

      <div className="flex flex-wrap gap-3">
        <Stat icon={<FileVideo className="size-4" />} n={summary.sources} label="sources" />
        <Stat icon={<Images className="size-4" />} n={summary.broll} label="b-roll" />
        <Stat icon={<Music className="size-4" />} n={summary.music.project} label="project music" />
      </div>

      {summary.music.available > 0 && (
        <MusicAvailability
          project={summary.music.project}
          bundled={summary.music.bundled}
          enabled={intent?.music}
        />
      )}

      {intentDecisions.map((decision) => (
        <div
          key={decision.code}
          role="status"
          className={decision.status === "blocked"
            ? "flex items-start gap-2 rounded-md border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-xs text-amber-200"
            : "flex items-start gap-2 rounded-md border border-border bg-card/30 px-3 py-2 text-xs text-muted-foreground"}
        >
          {decision.status === "blocked"
            ? <AlertTriangle className="mt-0.5 size-4 shrink-0" />
            : <Info className="mt-0.5 size-4 shrink-0" />}
          <p>{decision.message}</p>
        </div>
      ))}

      <AutoEditLaunch dir={outDir} intent={intent} onDone={onAutoEditDone} />

      <details className="rounded-lg border border-border bg-card/30 p-4">
        <summary className="cursor-pointer text-sm font-medium text-foreground">Advanced: media details and edit plan JSON</summary>
        <div className="mt-4 space-y-4 border-t border-border pt-4">
          <p className="break-all font-mono text-[11px] text-muted-foreground/60">{manifestPath}</p>
          {!intent && (
            <p className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
              This project has no stored edit intent. Choose Short or Long and an edit level before creating a plan.
            </p>
          )}
          {sources.length > 0 && <ul className="space-y-1.5">
            {sources.map((source) => <li key={source.id} className="flex flex-wrap gap-3 rounded-md border border-border px-3 py-2 text-xs text-muted-foreground">
              <span className="font-mono text-signal">{source.id}</span>
              <span>{source.duration.toFixed(1)}s</span>
              <span>{source.resolution?.join("×")}</span>
              <span>{source.fps}fps</span>
              <span>{source.transcriptPath ? "Transcript ready" : "No transcript"}</span>
            </li>)}
          </ul>}
        <div>
          <div className="label text-foreground">Edit plan (JSON)</div>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Advanced/manual path: paste or edit a plan directly. Lint checks it against the
            manifest before rendering.
          </p>
        </div>
        <Textarea
          value={planText}
          onChange={(e) => { setPlanText(e.target.value); setVerdict(null); }}
          spellCheck={false}
          className="min-h-72 font-mono text-xs"
        />

        <div className="flex flex-wrap items-center gap-3">
          <Button variant="outline" onClick={lint} disabled={linting || !intent || !planText.trim()}>
            {linting ? <Loader2 className="size-4 animate-spin" /> : null}
            {linting ? "Checking…" : "Check plan"}
          </Button>
          <Button onClick={() => onRender(planText)} disabled={!intent || !verdict?.ok}>
            Render manual plan →
          </Button>
          {verdict?.ok && (
            <span className="flex items-center gap-1.5 text-sm text-emerald-400/90">
              <CheckCircle2 className="size-4" /> Plan is renderable
            </span>
          )}
        </div>

        {error && <p className="text-sm text-destructive">{error}</p>}

        {verdict && !verdict.ok && (
          <Findings kind="error" title="Errors — plan rejected" items={verdict.errors} />
        )}
        {verdict && verdict.warnings.length > 0 && (
          <Findings kind="warn" title="Warnings — still renderable" items={verdict.warnings} />
        )}
        </div>
      </details>
    </div>
  );
}

function Stat({ icon, n, label }: { icon: React.ReactNode; n: number; label: string }) {
  return (
    <div className="flex items-center gap-2 rounded-md border border-border bg-card/40 px-3 py-2">
      <span className="text-muted-foreground/60">{icon}</span>
      <span className="text-lg font-semibold tabular-nums text-foreground">{n}</span>
      <span className="label text-muted-foreground/70">{label}</span>
    </div>
  );
}

function MusicAvailability({
  project,
  bundled,
  enabled,
}: {
  project: number;
  bundled: number;
  enabled?: boolean;
}) {
  const useText = enabled
    ? "Music is enabled in the edit intent; auto-edit may select an available track."
    : "Music is off; available tracks will not be used unless you explicitly enable it.";
  return (
    <div className="flex items-start gap-2 rounded-md border border-border bg-card/30 px-3 py-2 text-xs text-muted-foreground">
      <Music className="mt-0.5 size-4 shrink-0 text-muted-foreground/60" />
      <div>
        {project > 0 && <p>{project} project audio track{project === 1 ? " was" : "s were"} detected.</p>}
        {bundled > 0 && (
          <p>{bundled} bundled bed{bundled === 1 ? " is" : "s are"} available—not uploaded or selected.</p>
        )}
        <p>{useText}</p>
      </div>
    </div>
  );
}

function Findings({ kind, title, items }: { kind: "error" | "warn"; title: string; items: string[] }) {
  const cls = kind === "error" ? "border-destructive/30 bg-destructive/5" : "border-amber-500/30 bg-amber-500/5";
  const iconCls = kind === "error" ? "text-destructive" : "text-amber-400";
  return (
    <div className={`rounded-md border p-3 ${cls}`}>
      <div className={`flex items-center gap-2 text-sm font-medium ${iconCls}`}>
        <AlertTriangle className="size-4" /> {title}
      </div>
      <ul className="mt-2 space-y-1 font-mono text-xs text-foreground/90">
        {items.map((it, i) => (
          <li key={i} className="break-words">• {it}</li>
        ))}
      </ul>
    </div>
  );
}
