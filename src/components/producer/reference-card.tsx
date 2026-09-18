"use client";

import { AlertTriangle, BookOpenCheck, Loader2, Play, Sparkles, Trash2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import ReferenceDecisionForm from "./reference-decision";
import {
  formatDuration,
  referenceIntent,
  suggestedMode,
  type ReferenceDecision,
  type ReferenceEntry,
  type ReferenceIntent,
  type StudyActivity,
} from "./reference-types";

interface Props {
  reference: ReferenceEntry;
  activity?: StudyActivity;
  saving: boolean;
  selected: boolean;
  onStudy: () => void;
  onSave: (decision: ReferenceDecision) => Promise<ReferenceEntry | null>;
  onUse: (intent: ReferenceIntent) => void;
  onRemove: () => void;
}

function stateOf(reference: ReferenceEntry): string {
  return typeof reference.status === "string" ? reference.status : reference.status.state;
}

function ready(reference: ReferenceEntry): boolean {
  return stateOf(reference) === "ready" && reference.studied && Boolean(reference.profile) && Boolean(reference.decision);
}

function StatusBadge({ reference, activity }: { reference: ReferenceEntry; activity?: StudyActivity }) {
  if (activity?.running) return <Badge variant="outline" className="border-signal/40 text-signal"><Loader2 className="animate-spin" /> Studying</Badge>;
  if (stateOf(reference) === "invalid") return <Badge variant="destructive">Invalid study</Badge>;
  if (ready(reference)) return <Badge variant="outline" className="border-emerald-500/40 text-emerald-400">Ready</Badge>;
  if (reference.studied || stateOf(reference) === "needs-decision") {
    return <Badge variant="outline" className="border-amber-500/40 text-amber-400">Needs decision</Badge>;
  }
  return <Badge variant="outline" className="text-muted-foreground">Not studied</Badge>;
}

function StudyProgress({ activity }: { activity: StudyActivity }) {
  return (
    <div className="space-y-1.5 rounded-md border border-signal/20 bg-signal/5 p-2.5">
      <div className="flex items-center gap-2 font-mono text-[10px] text-signal">
        {activity.running && <Loader2 className="size-3 animate-spin" />}
        {activity.label}
      </div>
      {typeof activity.percent === "number" && <Progress value={activity.percent} className="h-1.5" />}
    </div>
  );
}

function ProfileSummary({ reference }: { reference: ReferenceEntry }) {
  const source = reference.profile?.source ?? reference.metadata ?? {};
  const duration = formatDuration(source.durationS);
  const dimensions = source.width && source.height ? `${source.width}×${source.height}` : null;
  const mode = suggestedMode(reference);
  const known = reference.profile?.suggestedKnownStyle;
  const facts = [dimensions, duration, source.fps ? `${source.fps.toFixed(2)} fps` : null].filter(Boolean);
  const mechanics = reference.profile?.mechanics;
  const eventCount = Object.values(mechanics?.eventCounts ?? {}).reduce((sum, count) => sum + count, 0);
  const measured = [
    typeof mechanics?.cutsPerMin === "number" ? `${mechanics.cutsPerMin.toFixed(1)} cuts/min` : null,
    typeof mechanics?.shotMedianS === "number" ? `${mechanics.shotMedianS.toFixed(1)}s median shot` : null,
    eventCount > 0 ? `${eventCount} measured events` : null,
    mechanics?.captions?.detected === true ? "captions detected" : null,
    mechanics?.audio?.musicLabel ? `music ${mechanics.audio.musicLabel}` : null,
  ].filter(Boolean);
  return (
    <div className="space-y-1.5 rounded-md border border-border/60 bg-background/30 p-2.5">
      <div className="flex flex-wrap items-center gap-1.5 text-[10px] text-muted-foreground">
        {facts.map((fact) => <span key={fact} className="rounded bg-card px-1.5 py-0.5 font-mono">{fact}</span>)}
      </div>
      {measured.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 text-[10px] text-muted-foreground">
          {measured.map((fact) => <span key={fact} className="rounded border border-border/60 px-1.5 py-0.5">{fact}</span>)}
        </div>
      )}
      <p className="text-[11px] text-muted-foreground">
        {mode ? <>Study suggests <span className="font-medium text-foreground">{mode === "short" ? "Short" : "Long"}</span>. You still confirm it below.</> : "The study could not make a format suggestion; choose explicitly below."}
        {known && <> Closest measured grammar: <span className="font-medium text-foreground">{known === "punch" ? "Punch" : known[0].toUpperCase() + known.slice(1)}</span>.</>}
      </p>
    </div>
  );
}

function QualityNotes({ reference }: { reference: ReferenceEntry }) {
  const quality = reference.profile?.quality ?? reference.quality;
  if (!quality) return null;
  const warnings = Array.isArray(quality.warnings) ? quality.warnings : [];
  const unclassified = typeof quality.unclassifiedRuns === "number" ? quality.unclassifiedRuns : 0;
  if (!warnings.length && unclassified === 0 && quality.wordLockAvailable !== false) return null;
  return (
    <div className="rounded-md border border-amber-500/25 bg-amber-500/5 px-2.5 py-2 text-[10px] text-amber-200/80">
      <p className="flex items-center gap-1 font-medium"><AlertTriangle className="size-3" /> Study caveats</p>
      {unclassified > 0 && <p>{unclassified} motion run{unclassified === 1 ? " was" : "s were"} not classified.</p>}
      {quality.wordLockAvailable === false && <p>No word-timed transcript was available; word-lock evidence is missing.</p>}
      {warnings.map((warning) => <p key={warning}>{warning}</p>)}
    </div>
  );
}

function CardActions({ reference, selected, studying, onStudy, onUse, onRemove }: {
  reference: ReferenceEntry;
  selected: boolean;
  studying: boolean;
  onStudy: () => void;
  onUse: (intent: ReferenceIntent) => void;
  onRemove: () => void;
}) {
  const intent = ready(reference) ? referenceIntent(reference) : null;
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border/60 pt-3">
      <div className="flex items-center gap-1.5">
        <Button variant="ghost" size="xs" disabled={studying} onClick={onStudy}>
          {studying ? <Loader2 className="animate-spin" /> : <Play />} {reference.studied ? "Run study again" : "Run study"}
        </Button>
        <Button variant="ghost" size="xs" onClick={onRemove} title="Hide from the reference library; files remain on disk">
          <Trash2 /> Hide
        </Button>
      </div>
      <Button size="sm" disabled={!intent || studying} onClick={() => intent && onUse(intent)}>
        {selected ? <BookOpenCheck /> : <Sparkles />}
        {selected ? "Selected for next edit" : "Use for next edit"}
      </Button>
    </div>
  );
}

export default function ReferenceCard(props: Props) {
  const state = stateOf(props.reference);
  const studied = state === "needs-decision" || state === "ready" || state === "studied";
  return (
    <article className={`space-y-3 rounded-lg border p-3.5 transition-colors ${props.selected ? "border-signal/60 bg-signal/5" : "border-border bg-card/35"}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="truncate text-sm font-medium text-foreground" title={props.reference.title}>{props.reference.title}</h3>
          <p className="truncate font-mono text-[9px] text-muted-foreground/50" title={props.reference.video ?? props.reference.dir}>{props.reference.video ?? props.reference.dir}</p>
        </div>
        <StatusBadge reference={props.reference} activity={props.activity} />
      </div>
      {props.activity && <StudyProgress activity={props.activity} />}
      {studied && <ProfileSummary reference={props.reference} />}
      {studied && <QualityNotes reference={props.reference} />}
      {studied && (
        <ReferenceDecisionForm
          key={`${props.reference.id}:${JSON.stringify(props.reference.decision)}:${props.reference.profile?.suggestedKnownStyle ?? ""}`}
          reference={props.reference}
          saving={props.saving}
          onSave={props.onSave}
        />
      )}
      {!studied && !props.activity?.running && (
        <p className="text-[11px] text-muted-foreground">The automatic study did not finish. Run it again before choosing format and style direction.</p>
      )}
      <CardActions
        reference={props.reference}
        selected={props.selected}
        studying={props.activity?.running === true}
        onStudy={props.onStudy}
        onUse={props.onUse}
        onRemove={props.onRemove}
      />
    </article>
  );
}
