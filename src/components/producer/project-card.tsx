"use client";

import { useState } from "react";
import { Check, ChevronDown, ExternalLink, Loader2, Pencil, Trash2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { canOpenProject } from "@/lib/producer/project-state";
import { projectCardPresentation } from "@/lib/producer/project-card-state";
import { guidedCheckpointOpenLabel, isGuidedCheckpoint } from "@/lib/producer/guided-checkpoint-state";
import { StageActionButton, type IngestedPayload } from "./stage-actions";
import { CutawayDecision, ProjectDetails, SegmentRows } from "./project-card-details";
import ProjectPalmierButton, { ProjectCandidateQcButton } from "./project-palmier-button";
import type { ProjectStatus } from "./use-project-status";
export interface Listing {
  dir: string;
  title: string;
  exists: boolean;
  mtime: number | null;
}
export function relTime(ms: number): string {
  const mins = Math.max(0, Math.round((Date.now() - ms) / 60000));
  if (mins < 60) return `${mins}m ago`;
  if (mins < 60 * 24) return `${Math.round(mins / 60)}h ago`;
  return `${Math.round(mins / (60 * 24))}d ago`;
}

interface RenameTitleProps {
  title: string;
  onRename: (title: string) => Promise<void>;
  onCancel: () => void;
}

function RenameTitle({ title, onRename, onCancel }: RenameTitleProps) {
  const [value, setValue] = useState(title);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const save = async () => {
    const next = value.trim();
    if (!next) return;
    setSaving(true);
    setError("");
    try {
      await onRename(next);
      onCancel();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Rename failed");
    } finally {
      setSaving(false);
    }
  };
  return (
    <span className="flex flex-col gap-1">
      <span className="flex items-center gap-1">
        <input
          autoFocus value={value} disabled={saving} onChange={(event) => setValue(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") void save();
            if (event.key === "Escape") onCancel();
          }}
          className="min-w-0 rounded border border-signal/50 bg-background px-2 py-1 text-sm text-foreground"
          aria-label="Project display name"
        />
        <Button variant="ghost" size="icon-xs" disabled={saving || !value.trim()} onClick={() => void save()} title="Save name">
          {saving ? <Loader2 className="size-3 animate-spin" /> : <Check className="size-3" />}
        </Button>
        <Button variant="ghost" size="icon-xs" disabled={saving} onClick={onCancel} title="Cancel rename">
          <X className="size-3" />
        </Button>
      </span>
      {error && <span className="text-[10px] text-destructive">{error}</span>}
    </span>
  );
}

interface HeaderProps {
  p: Listing;
  status: ProjectStatus | null;
  renaming: boolean;
  openable: boolean;
  onOpenProject: () => void;
  onRename: (title: string) => Promise<void>;
  onRenameToggle: (value: boolean) => void;
}

function TitleBlock(props: HeaderProps) {
  const { p, status, renaming, openable } = props;
  return (
    <div className="min-w-0 flex-1">
      {renaming ? (
        <RenameTitle title={p.title} onRename={props.onRename} onCancel={() => props.onRenameToggle(false)} />
      ) : (
        <span className="flex items-center gap-1">
          <button type="button" disabled={!p.exists} onClick={props.onOpenProject}
            title={openable ? "Open this project in the Sniper editor" : "View this project's current state"}
            className={`min-w-0 truncate text-left text-sm underline-offset-4 hover:underline ${p.exists ? "text-foreground" : "text-muted-foreground line-through"}`}>
            {p.title}
          </button>
          {p.exists && (
            <Button variant="ghost" size="xs" onClick={() => props.onRenameToggle(true)} title="Rename project in this list">
              <Pencil className="size-3" /> Rename
            </Button>
          )}
        </span>
      )}
      <div className="truncate font-mono text-[11px] text-muted-foreground/60" title={p.dir}>
        {status?.projectRoot?.split("/").pop() ?? p.dir.split("/").pop()}
        {p.mtime != null && <span className="ml-2">updated {relTime(p.mtime)}</span>}
        {!p.exists && <span className="ml-2 text-destructive/80">missing</span>}
      </div>
    </div>
  );
}

interface ActionBlockProps {
  p: Listing;
  status: ProjectStatus | null;
  statusError: string | null;
  openable: boolean;
  onOpen: (dir: string, displayName?: string) => void;
  onPalmierMessage: (message: string) => void;
  onRevealClipper: () => void;
  onRemove: (dir: string) => void;
  onRefresh: () => void;
  onIngested?: (payload: IngestedPayload) => void;
}

function ActionBlock(props: ActionBlockProps) {
  const { p, status, openable } = props;
  if (!p.exists) return <Button variant="default" size="xs" onClick={() => props.onRemove(p.dir)}><Trash2 className="size-3" /> Remove missing project</Button>;
  if (!status) return props.statusError ? (
    <div className="flex gap-1.5">
      <Button variant="default" size="xs" onClick={props.onRefresh}>Try status again</Button>
      <Button variant="ghost" size="xs" onClick={() => props.onRemove(p.dir)}><Trash2 className="size-3" /> Remove from list</Button>
    </div>
  ) : null;
  const running = status.run?.status === "running";
  const cutCheckpoint = isGuidedCheckpoint(status.run);
  const presentation = projectCardPresentation({
    origin: status.origin, intent: status.intent, stages: status.stages,
    run: status.run, palmier: status.palmier, finalArtifact: status.finalArtifact,
    segmentCount: status.segments.length, clipperFileCount: status.clipperFiles.length,
  });
  const openButton = openable ? (
    <Button
      variant={presentation.primary === "open_sniper" ? "default" : "ghost"}
      size="xs"
      onClick={() => props.onOpen(status.producerDir, p.title)}
    >
      {cutCheckpoint ? guidedCheckpointOpenLabel(status.run)
        : running ? "Open Sniper progress" : status.stages.final
        ? "Open approved Sniper video" : status.finalArtifact.state === "unapproved"
          ? "Inspect unapproved render" : "Inspect Sniper draft"}
    </Button>
  ) : null;
  return (
    <div className="flex flex-wrap items-start justify-end gap-1.5">
      {!cutCheckpoint && <ProjectPalmierButton status={status} title={p.title} onMessage={props.onPalmierMessage}
        onChanged={props.onRefresh}
        primary={presentation.primary === "open_palmier"} />}
      {!cutCheckpoint && <ProjectCandidateQcButton status={status} onMessage={props.onPalmierMessage}
        onChanged={props.onRefresh} />}
      {running && openButton}
      {presentation.primary !== "choose_segment" && presentation.primary !== "reveal_clipper"
        && (cutCheckpoint || status.palmier.state !== "approved_working_head") && (
        <StageActionButton status={status} onIngested={props.onIngested} onRefresh={props.onRefresh}
          primary={presentation.primary === "stage"} />
      )}
      {!running && openButton}
      {(status.clipperFiles?.length ?? 0) > 0 && <Button
        variant={presentation.primary === "reveal_clipper" ? "default" : "ghost"}
        size="xs" onClick={props.onRevealClipper}
      ><ExternalLink className="size-3" /> Reveal Final Cut timeline</Button>}
    </div>
  );
}

interface BodyProps {
  status: ProjectStatus;
  openable: boolean;
  expanded: boolean;
  palmierMessage: string;
  onExpanded: () => void;
  onRevealSource: () => void;
  onIngested?: (payload: IngestedPayload) => void;
}

function CardBody(props: BodyProps) {
  const { status, expanded } = props;
  const summary = projectCardPresentation({
    origin: status.origin, intent: status.intent, stages: status.stages,
    run: status.run, palmier: status.palmier, finalArtifact: status.finalArtifact,
    segmentCount: status.segments.length, clipperFileCount: status.clipperFiles.length,
  });
  const running = status.run?.status === "running";
  const cutCheckpoint = isGuidedCheckpoint(status.run);
  return (
    <div className="mt-2 space-y-1.5">
      <p className="text-sm font-medium text-foreground">{summary.label}</p>
      <div className="grid gap-1 rounded-md border border-border/60 bg-background/25 p-2.5 text-xs text-muted-foreground sm:grid-cols-[6.5rem_1fr]">
        <span className="font-medium text-foreground">Available now</span><span>{summary.available}</span>
        <span className="font-medium text-foreground">Working now</span><span>{summary.working}</span>
        <span className="font-medium text-foreground">What&apos;s next</span><span>{summary.next}</span>
        <span className="font-medium text-foreground">Safe actions</span><span>{summary.safe}</span>
      </div>
      {!cutCheckpoint && status.intentDecisions
        .filter((decision) => decision.lane === "broll" && decision.status === "resolved")
        .map((decision) => (
          <CutawayDecision
            key={decision.code}
            decision={decision}
            status={status}
            onRevealSource={props.onRevealSource}
            onIngested={props.onIngested}
          />
        ))}
      {props.palmierMessage && <p className="text-[10px] text-signal">{props.palmierMessage}</p>}
      {status.segments.length > 0 && (
        <SegmentRows
          segments={status.segments}
          projectRoot={status.projectRoot}
          runActive={running}
          primaryFirst={summary.primary === "choose_segment"}
          onIngested={props.onIngested}
        />
      )}
      <button type="button" onClick={props.onExpanded} className="flex items-center gap-1 text-[10px] text-muted-foreground hover:text-foreground">
        <ChevronDown className={`size-3 transition-transform ${expanded ? "rotate-180" : ""}`} />
        {expanded ? "Hide details" : "View details"}
      </button>
      {expanded && <ProjectDetails status={status} />}
    </div>
  );
}

interface ProjectCardProps {
  p: Listing;
  status: ProjectStatus | null;
  statusError: string | null;
  onOpen: (dir: string, displayName?: string) => void;
  onRemove: (dir: string) => void;
  onRename: (dir: string, title: string) => Promise<void>;
  onRefresh: () => void;
  onIngested?: (payload: IngestedPayload) => void;
}

async function revealPath(input: { path?: string; pending: string; complete: string; onMessage: (value: string) => void }) {
  if (!input.path) return;
  input.onMessage(input.pending);
  try {
    const response = await fetch("/api/producer/reveal", { method: "POST",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify({ path: input.path }) });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof result.error === "string" ? result.error : `Reveal failed (${response.status})`);
    input.onMessage(input.complete);
  } catch (error) { input.onMessage(error instanceof Error ? error.message : "Reveal failed"); }
}

export default function ProjectCard({ p, status, statusError, onOpen, onRemove, onRename, onRefresh, onIngested }: ProjectCardProps) {
  const [renaming, setRenaming] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [palmierMessage, setPalmierMessage] = useState("");
  const openable = status ? canOpenProject(status.stages) : false;
  const openProject = () => {
    if (status && openable) onOpen(status.producerDir, p.title);
    else setExpanded((value) => !value);
  };
  const revealClipper = () => revealPath({ path: status?.clipperFiles?.[0]?.path, onMessage: setPalmierMessage,
    pending: "Showing the Final Cut Pro timeline in Finder…", complete: "Final Cut Pro timeline shown in Finder." });
  const revealSource = () => revealPath({ path: status?.sourceDir ?? undefined, onMessage: setPalmierMessage,
    pending: "Showing the source folder in Finder…", complete: "Source folder shown in Finder." });

  return (
    <li className="rounded-md border border-border/60 bg-background/20 p-3">
      <div className="flex items-start gap-3">
        <TitleBlock p={p} status={status} renaming={renaming} openable={openable}
          onOpenProject={openProject} onRename={(title) => onRename(p.dir, title)} onRenameToggle={setRenaming} />
        <ActionBlock p={p} status={status} statusError={statusError} openable={openable} onOpen={onOpen}
          onRevealClipper={() => void revealClipper()}
          onPalmierMessage={setPalmierMessage}
          onRemove={onRemove} onRefresh={onRefresh} onIngested={onIngested} />
      </div>

      {statusError && <p className="mt-2 text-[10px] text-destructive" title={statusError}>Status unavailable. The saved project record could not be read.</p>}
      {p.exists && !status && !statusError && <p className="mt-2 text-[10px] text-muted-foreground">Checking project state…</p>}
      {p.exists && status && <CardBody status={status} openable={openable} expanded={expanded}
        palmierMessage={palmierMessage} onExpanded={() => setExpanded((value) => !value)}
        onRevealSource={() => void revealSource()} onIngested={onIngested} />}
    </li>
  );
}
