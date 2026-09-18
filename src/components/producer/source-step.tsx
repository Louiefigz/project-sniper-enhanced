"use client";

import { useEffect, useRef, useState } from "react";
import { Clapperboard, FolderOpen, FileVideo, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { readEventStream, summarizeEvent, logStamp } from "@/lib/producer/sse";
import type { AssetManifest, LogLine, LogKind } from "@/lib/producer/types";
import type { IntentCapabilityDecision } from "@/lib/producer/intent-capabilities";
import {
  INTENT_PRESETS,
  presetToIntent,
  type ProjectIntent,
  type ReferenceIntent,
} from "@/lib/producer/intent-presets";
import { dlog, derror } from "@/lib/debug";
import StreamLog from "./stream-log";
import IntentCard from "./intent-card";
import { applyReferenceChange, intentForReference } from "./reference-intent";
import type { NativePickerKind } from "@/lib/producer/native-media-picker";
import { briefModeConflict, intentSelectionReady } from "@/lib/producer/brief-intent-conflict";
import { PickButton, ReferenceSelection } from "./source-step-parts";

interface Props {
  referenceIntent?: ReferenceIntent | null;
  onReferenceCleared?: () => void;
  onIngested: (args: {
    inputPath: string;
    manifestPath: string;
    outDir: string;
    manifest: AssetManifest;
    requestedIntent: ProjectIntent;
    intent: ProjectIntent;
    intentDecisions: IntentCapabilityDecision[];
  }) => void;
}

export default function SourceStep({ onIngested, referenceIntent, onReferenceCleared }: Props) {
  const [inputPath, setInputPath] = useState<string | null>(null);
  const [inputName, setInputName] = useState<string | null>(null);
  const [isDir, setIsDir] = useState(false);
  const [brief, setBrief] = useState("");
  // A draft makes the card explain its options, but ingest stays disabled until
  // the operator explicitly confirms both format and editing level.
  const [intent, setIntent] = useState<ProjectIntent>(() => referenceIntent
    ? intentForReference(referenceIntent)
    : presetToIntent(INTENT_PRESETS[0], "short"));
  const [intentSelection, setIntentSelection] = useState(() => ({
    format: referenceIntent != null,
    style: referenceIntent != null,
  }));
  const [picking, setPicking] = useState(false);
  const [running, setRunning] = useState(false);
  const [copyPercent, setCopyPercent] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lines, setLines] = useState<LogLine[]>([]);
  const abortRef = useRef<AbortController | null>(null);
  const briefConflict = briefModeConflict(brief, intent.mode);
  const intentReady = intentSelectionReady(intentSelection, brief, intent.mode);

  useEffect(() => () => abortRef.current?.abort(), []);

  useEffect(() => {
    if (referenceIntent) {
      setIntent(intentForReference(referenceIntent));
      setIntentSelection({ format: true, style: true });
      return;
    }
    setIntent((current) => {
      if (!current.reference) return current;
      const clean = { ...current };
      delete clean.reference;
      return clean;
    });
  }, [referenceIntent]);

  const changeIntent = (next: ProjectIntent) => {
    if (!referenceIntent) return setIntent(next);
    const applied = applyReferenceChange(next, referenceIntent);
    setIntent(applied.intent);
    if (applied.cleared) onReferenceCleared?.();
  };

  const push = (kind: LogKind, text: string) =>
    setLines((prev) => [...prev, { t: logStamp(), kind, text }]);

  const pick = async (kind: NativePickerKind) => {
    setPicking(true);
    setError(null);
    try {
      const res = await fetch("/api/producer/pick-file", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind }),
      });
      const data = await res.json();
      if (data.canceled) return;
      if (data.error) throw new Error(data.error);
      setInputPath(data.path);
      setInputName(data.name);
      setIsDir(data.kind === "folder");
      dlog("producer:pick", "picked → page", { name: data.name, kind: data.kind });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to pick");
    } finally {
      setPicking(false);
    }
  };

  const runIngest = async () => {
    if (!inputPath || !intentReady) return;
    const requestedIntent: ProjectIntent = {
      ...intent,
      ...(brief.trim() ? { brief: brief.trim() } : {}),
    };
    setRunning(true);
    setCopyPercent(null);
    setError(null);
    setLines([]);
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    dlog("producer:ingest", "start", { inputPath, intent: requestedIntent, referenceId: referenceIntent?.id });
    try {
      const res = await fetch("/api/producer/ingest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ inputPath, noTranscribe: false, intent: requestedIntent }),
        signal: ctrl.signal,
      });
      await readEventStream(
        res,
        (ev) => {
          if (ev.event === "source_copy_progress") {
            const percent = Number(ev.percent);
            setCopyPercent(Number.isFinite(percent) ? percent : null);
            push("event", `Copying source media · ${percent}%`);
            return;
          }
          if (ev.event === "manifest") {
            push("info", "✓ manifest built");
            onIngested({
              inputPath,
              manifestPath: ev.manifestPath as string,
              outDir: ev.outDir as string,
              manifest: ev.manifest as AssetManifest,
              requestedIntent: (ev.requestedIntent as ProjectIntent | null) ?? requestedIntent,
              intent: (ev.intent as ProjectIntent | null) ?? requestedIntent,
              intentDecisions: (ev.intentDecisions as IntentCapabilityDecision[] | null) ?? [],
            });
            return;
          }
          if (ev.event === "error") {
            push("error", `✗ ${ev.message}`);
            setError(String(ev.message));
            throw new Error(String(ev.message));
          }
          push(ev.event === "log" ? "stderr" : "event", summarizeEvent(ev));
        },
        ctrl.signal,
        "manifest",
      );
    } catch (e) {
      if ((e as Error).name === "AbortError") return;
      derror("producer:ingest", "stream failed", e);
      const msg = e instanceof Error ? e.message : "Ingest failed";
      setError(msg);
      push("error", `✗ ${msg}`);
    } finally {
      setRunning(false);
    }
  };

  return (
    <div id="producer-source" className="rise-in scroll-mt-20">
      <div className="mb-8 flex items-center gap-3">
        <Clapperboard className="size-5 text-signal" strokeWidth={2} />
        <div>
          <h1 className="font-display text-2xl font-bold tracking-tight">Create or edit a video</h1>
          <p className="text-sm text-muted-foreground">
            Choose footage → describe the edit → create a finished MP4 you can revise.
          </p>
        </div>
      </div>

      {referenceIntent && <ReferenceSelection intent={referenceIntent} />}

      <div className="mb-3">
        <h2 className="text-sm font-medium text-foreground">Choose your source media</h2>
        <p className="mt-1 text-xs text-muted-foreground">
          For multiple clips, choose one structured project folder. Nothing is uploaded by this picker.
        </p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <PickButton
          icon={<FolderOpen className="size-6" />}
          label={picking ? "Opening…" : "Project folder"}
          description="Multiple clips, plus optional cutaways and music"
          disabled={picking || running}
          onClick={() => pick("folder")}
        />
        <PickButton
          icon={<FileVideo className="size-6" />}
          label={picking ? "Opening…" : "Single media file"}
          description="Create a new edit from one existing video or audio file"
          disabled={picking || running}
          onClick={() => pick("file")}
        />
      </div>
      <details className="mt-2 text-xs text-muted-foreground/70">
        <summary className="cursor-pointer">Advanced folder setup</summary>
        <p className="mt-2">
          Put primary clips at the folder root, cutaways in <span className="font-mono">broll/</span>,
          and background tracks in <span className="font-mono">music/</span>.
        </p>
      </details>

      {error && <p className="mt-4 text-sm text-destructive">{error}</p>}

      {inputPath && (
        <div className="mt-6 space-y-4">
          <div className="flex items-center gap-3 rounded-lg border border-border bg-card/60 px-4 py-3">
            {isDir ? (
              <FolderOpen className="size-4 shrink-0 text-signal" />
            ) : (
              <FileVideo className="size-4 shrink-0 text-signal" />
            )}
            <div className="min-w-0">
              <div className="truncate text-sm text-foreground">{inputName}</div>
              <div className="truncate font-mono text-[11px] text-muted-foreground/60">{inputPath}</div>
            </div>
          </div>

          <div className="rounded-lg border border-signal/35 bg-signal/5 p-4">
            <label htmlFor="producer-brief" className="text-sm font-semibold text-foreground">
              Describe the video you want
              <span className="ml-2 text-xs font-normal text-signal">Recommended</span>
            </label>
            <p id="producer-brief-help" className="mt-1 text-xs leading-relaxed text-muted-foreground">
              Tell the editor the goal, audience, length, must-keep moments, and anything to remove.
              Format and style controls below handle the technical details.
            </p>
            <textarea
              id="producer-brief"
              aria-describedby="producer-brief-help"
              value={brief}
              maxLength={1200}
              onChange={(event) => setBrief(event.target.value)}
              disabled={running}
              rows={4}
              placeholder="Create a 60-second vertical video. Open with the revenue result, remove setup chatter, keep the three steps, and end on the call to action."
              className="mt-3 w-full resize-y rounded-md border border-border bg-background/80 px-3 py-2 text-sm text-foreground outline-none placeholder:text-muted-foreground/60 focus:border-signal disabled:opacity-60"
            />
            <div className="mt-1 text-right text-[11px] text-muted-foreground/60">{brief.length}/1200</div>
          </div>

          <IntentCard
            value={intent}
            onChange={changeIntent}
            disabled={running}
            formatConfirmed={intentSelection.format}
            styleConfirmed={intentSelection.style}
            onFormatConfirmed={() => setIntentSelection((state) => ({ ...state, format: true }))}
            onStyleConfirmed={() => setIntentSelection((state) => ({ ...state, style: true }))}
            onStyleInvalidated={() => setIntentSelection((state) => ({ ...state, style: false }))}
          />

          {(!intentSelection.format || !intentSelection.style) && (
            <p role="status" className="text-xs text-amber-300">
              Choose {intentSelection.format ? "an editing level" : intentSelection.style ? "a format" : "a format and editing level"} before preparing media.
            </p>
          )}
          {briefConflict && (
            <p role="alert" className="text-xs text-amber-300">
              {briefConflict} Update the description or choose the matching format.
            </p>
          )}

          <Button
            onClick={runIngest}
            disabled={running || !intentReady}
          >
            {running ? <Loader2 className="size-4 animate-spin" /> : null}
            {running && copyPercent != null ? `Copying source · ${copyPercent}%` : running ? "Preparing media…" : "Prepare media →"}
          </Button>
          {running && copyPercent != null && <p role="status" className="text-xs text-muted-foreground">Source copy progress: {copyPercent}%</p>}
          {!running && (
            <p className="text-xs text-muted-foreground">Next: confirm the detected media, then choose Create first edit.</p>
          )}
        </div>
      )}

      {(running || lines.length > 0) && (
        <div className="mt-6">
          <StreamLog title="Ingest" lines={lines} />
        </div>
      )}
    </div>
  );
}
