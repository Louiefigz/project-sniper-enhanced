"use client";

import { useCallback, useState } from "react";
import type { LineDecision, SpeakerMap, TranscriptEntry } from "@/lib/clipper/types";
import { parseIndexedDecisions } from "@/lib/clipper/llm";
import { Button } from "@/components/ui/button";
import { buildEditPrompt, DEFAULT_EDIT_REQUEST } from "@/prompts/clipper/default-edit";
import { derror, dlog } from "@/lib/debug";

interface Props {
  transcript: TranscriptEntry[];
  speakerMap?: SpeakerMap;
  editRequest: string;
  onEditRequestChange: (value: string) => void;
  onComplete: (decisions: LineDecision[]) => void;
  onReturnToCurrentEdit?: () => void;
}

type PreviewView = "decisions" | "transcript" | "edited";

function getLabel(entry: TranscriptEntry, speakerMap?: SpeakerMap): string {
  const counts = new Map<number, number>();
  for (const word of entry.words ?? []) {
    if (word.speaker != null) counts.set(word.speaker, (counts.get(word.speaker) ?? 0) + 1);
  }
  if (!counts.size) return "Speaker";
  const id = [...counts.entries()].sort((a, b) => b[1] - a[1])[0][0];
  return speakerMap?.[id] ?? `Speaker ${id}`;
}

function formatDecisions(raw: string, total: number, streaming: boolean): string {
  const trimmed = raw.trim();
  if (!trimmed) return "";
  if (!trimmed.startsWith("{")) return raw;
  try {
    const parsed = JSON.parse(trimmed) as {
      decisions?: { index: number; action: string; trimmed_text?: string }[];
    };
    if (!Array.isArray(parsed.decisions)) return raw;
    return parsed.decisions.map((decision) => {
      const action = decision.action.toUpperCase();
      return action === "TRIM" && decision.trimmed_text
        ? `[${decision.index}] TRIM: ${decision.trimmed_text}`
        : `[${decision.index}] ${action}`;
    }).join("\n");
  } catch {
    const count = trimmed.match(/"index"\s*:\s*\d+/g)?.length ?? 0;
    return streaming ? `Creating decisions… (${count}/${total} transcript sections)` : raw;
  }
}

function editedPreview(
  raw: string,
  transcript: TranscriptEntry[],
  speakerMap: SpeakerMap | undefined,
  generating: boolean,
): string {
  try {
    const { decisions } = parseIndexedDecisions(raw, transcript.length, 0);
    const byIndex = new Map(decisions.map((decision) => [decision.index, decision]));
    return transcript.map((entry, index) => {
      const decision = byIndex.get(index);
      if (decision?.action === "remove") return null;
      const text = decision?.action === "trim" && decision.text
        ? decision.text : entry.text.trim();
      return `${getLabel(entry, speakerMap)}: ${text}`;
    }).filter(Boolean).join("\n\n");
  } catch {
    return generating ? "Creating edited preview…" : "Preview unavailable. See What AI changed for details.";
  }
}

async function requestError(response: Response): Promise<Error> {
  const body = (await response.text()).trim();
  try {
    const parsed = JSON.parse(body) as { error?: unknown };
    if (typeof parsed.error === "string") return new Error(parsed.error);
  } catch { /* use the plain response body */ }
  return new Error(body || `AI edit request failed (${response.status})`);
}

interface RequestPanelProps {
  value: string;
  generating: boolean;
  hasOutput: boolean;
  revising: boolean;
  onChange: (value: string) => void;
  onReset: () => void;
  onGenerate: () => void;
  onReturn?: () => void;
}

function RequestPanel(props: RequestPanelProps) {
  const canGenerate = props.value.trim().length > 0 && !props.generating;
  return <section className="rounded-xl border border-amber-700/50 bg-amber-950/15 p-5 mb-6">
    <div className="flex items-start justify-between gap-4 mb-2">
      <div><h2 className="text-2xl font-bold">How should this clip be edited?</h2>
        <p className="text-sm text-neutral-400 mt-1">Describe the result you want in plain language before AI makes any cuts.</p></div>
      <button type="button" onClick={props.onReset} disabled={props.generating}
        className="shrink-0 text-xs text-amber-300 hover:text-amber-100 disabled:opacity-40">
        Reset example
      </button>
    </div>
    <textarea value={props.value} onChange={(event) => props.onChange(event.target.value)}
      disabled={props.generating} rows={6} maxLength={4000} aria-label="How should this clip be edited?"
      className="w-full rounded-lg border border-neutral-700 bg-neutral-950 px-4 py-3 text-sm leading-relaxed text-neutral-100 focus:border-amber-500 focus:outline-none disabled:opacity-60" />
    <p className="text-xs text-neutral-500 mt-2">Clipper can remove or shorten spoken words. It does not add footage, rewrite dialogue, synchronize recordings, or render an MP4.</p>
    {props.revising && <p className="text-xs text-amber-300/90 mt-2">Your current word edit stays intact until you generate again. Generating again replaces it.</p>}
    <div className="flex flex-wrap gap-3 mt-4">
      <Button type="button" onClick={props.onGenerate} disabled={!canGenerate}
        className="bg-amber-600 text-white hover:bg-amber-500 disabled:opacity-30">
        {props.generating ? "Creating AI edit…" : props.hasOutput ? "Regenerate with these instructions" : "Create AI edit →"}
      </Button>
      {props.onReturn && <Button type="button" variant="outline" onClick={props.onReturn}
        className="border-neutral-700 text-neutral-300 hover:text-white">Keep current word edit</Button>}
    </div>
  </section>;
}

interface DecisionPanelProps {
  raw: string;
  transcript: TranscriptEntry[];
  speakerMap?: SpeakerMap;
  generating: boolean;
  view: PreviewView;
  onView: (view: PreviewView) => void;
}

function DecisionPanel(props: DecisionPanelProps) {
  const labels: [PreviewView, string][] = [
    ["decisions", "What AI changed"], ["transcript", "Original transcript"], ["edited", "Edited preview"],
  ];
  const content = props.view === "decisions"
    ? formatDecisions(props.raw, props.transcript.length, props.generating)
    : props.view === "transcript"
      ? props.transcript.map((entry, index) => `[${index}] ${getLabel(entry, props.speakerMap)}: ${entry.text.trim()}`).join("\n")
      : editedPreview(props.raw, props.transcript, props.speakerMap, props.generating);
  return <section className="rounded-xl border border-neutral-800 bg-neutral-950 overflow-hidden mb-5">
    <div className="flex items-center justify-between px-3 py-2 border-b border-neutral-800 bg-neutral-900">
      <div className="flex flex-wrap gap-2">{labels.map(([id, label]) => <button key={id}
        onClick={() => props.onView(id)} className={`text-xs font-medium px-2 py-1 rounded ${props.view === id
          ? "bg-amber-600 text-white" : "text-neutral-400 hover:text-neutral-200"}`}>{label}</button>)}</div>
      {props.generating && <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />}
    </div>
    <pre className="p-3 text-xs text-neutral-300 font-mono overflow-y-auto whitespace-pre-wrap" style={{ maxHeight: "480px" }}>{content}</pre>
  </section>;
}

export default function PromptStep(props: Props) {
  const [generating, setGenerating] = useState(false);
  const [rawOutput, setRawOutput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<PreviewView>("edited");

  const handleGenerate = useCallback(async () => {
    const prompt = buildEditPrompt(props.editRequest);
    setError(null); setRawOutput(""); setGenerating(true);
    dlog("clipper:prompt", "generate edit decisions", { utterances: props.transcript.length, promptChars: prompt.length });
    try {
      const response = await fetch("/api/clipper/clip-preview", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ transcript: props.transcript, prompt, speakerMap: props.speakerMap }),
      });
      if (!response.ok) throw await requestError(response);
      if (!response.body) throw new Error("AI edit response had no stream");
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let accumulated = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        accumulated += decoder.decode(value, { stream: true });
        setRawOutput(accumulated);
      }
      accumulated += decoder.decode();
      setRawOutput(accumulated);
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : "AI edit failed";
      setError(message); derror("clipper:prompt", "generate failed", cause);
    } finally { setGenerating(false); }
  }, [props.editRequest, props.speakerMap, props.transcript]);

  const handleContinue = useCallback(() => {
    try {
      const { decisions } = parseIndexedDecisions(rawOutput, props.transcript.length, 0);
      props.onComplete(decisions);
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : "Failed to read AI edit";
      setError(message); derror("clipper:prompt", "parse decisions failed", cause);
    }
  }, [props, rawOutput]);

  const resetExample = () => {
    if (props.editRequest === DEFAULT_EDIT_REQUEST
      || window.confirm("Replace your current instructions with the example?")) {
      props.onEditRequestChange(DEFAULT_EDIT_REQUEST);
    }
  };

  return <div>
    <RequestPanel value={props.editRequest} generating={generating} hasOutput={!!rawOutput}
      revising={!!props.onReturnToCurrentEdit} onChange={props.onEditRequestChange}
      onReset={resetExample} onGenerate={() => void handleGenerate()} onReturn={props.onReturnToCurrentEdit} />
    {rawOutput && <DecisionPanel raw={rawOutput} transcript={props.transcript} speakerMap={props.speakerMap}
      generating={generating} view={view} onView={setView} />}
    {!rawOutput && generating && <p className="text-sm text-neutral-400 mb-5">Reading the transcript and creating a first cut…</p>}
    {error && <p role="alert" className="text-sm text-red-400 mb-4 p-3 bg-red-950/20 border border-red-900/30 rounded-lg">{error}</p>}
    {!generating && rawOutput && <Button onClick={handleContinue} className="px-6">Review and fine-tune words →</Button>}
  </div>;
}
