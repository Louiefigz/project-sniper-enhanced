"use client";

import { useMemo } from "react";
import { Button } from "@/components/ui/button";
import ProjectCard, { type Listing } from "./project-card";
import type { IngestedPayload } from "./stage-actions";
import { useProjectStatuses } from "./use-project-status";
import ActiveProjectJobs from "./active-project-jobs";
import { useRecentProjects } from "./use-recent-projects";

// PROJECT BROWSER — the "Recent edits" card above the producer select step.
// Lists the ~/.project-sniper registry; each entry renders a ProjectCard with
// the disk-derived pipeline-checkmarks strip, the first-missing-stage action,
// and (segmenter projects) the per-segment "Ingest → edit" rows. Missing dirs
// render struck-through with a remove control (registry-only — nothing on
// disk is touched).

export default function RecentProjects({
  onOpen,
  onIngested,
}: {
  onOpen: (dir: string, displayName?: string) => void;
  onIngested?: (payload: IngestedPayload) => void;
}) {
  const registry = useRecentProjects();
  const visibleProjects = useMemo(
    () => registry.projects.slice(0, registry.visibleCount),
    [registry.projects, registry.visibleCount],
  );
  const statusDirs = useMemo(
    () => registry.projects.filter((project) => project.exists).map((project) => project.dir),
    [registry.projects],
  );
  const projectStatuses = useProjectStatuses(statusDirs);
  const loadNotice = registry.error ? (
    <ProjectLoadNotice error={registry.error} hasProjects={registry.projects.length > 0} onRetry={registry.refresh} />
  ) : null;
  if (registry.error && registry.projects.length === 0) return loadNotice;
  if (registry.projects.length === 0) return null;

  return (<>
    {loadNotice}
    <ActiveProjectJobs
      projects={registry.projects}
      entries={projectStatuses.entries}
      onOpen={onOpen}
      onRefresh={projectStatuses.refresh}
    />
    <ProjectListSection
      projects={registry.projects}
      visibleProjects={visibleProjects}
      onMore={registry.showMore}
      onFewer={registry.showFewer}
      statuses={projectStatuses}
      onOpen={onOpen}
      onRemove={registry.remove}
      onRename={registry.rename}
      onIngested={onIngested}
    />
  </>);
}

interface ProjectListSectionProps {
  projects: Listing[];
  visibleProjects: Listing[];
  onMore: () => void;
  onFewer: () => void;
  statuses: ReturnType<typeof useProjectStatuses>;
  onOpen: (dir: string, displayName?: string) => void;
  onRemove: (dir: string) => void;
  onRename: (dir: string, title: string) => Promise<void>;
  onIngested?: (payload: IngestedPayload) => void;
}

export function ProjectListSection(props: ProjectListSectionProps) {
  const remaining = Math.min(5, props.projects.length - props.visibleProjects.length);
  return (
    <section className="my-8 rounded-lg border border-border bg-card/50 p-4" aria-labelledby="recent-projects-title">
      <div id="recent-projects-title" className="text-sm font-semibold text-foreground">Continue a project</div>
      <p className="mb-3 mt-1 text-xs text-muted-foreground">
        Continue from the exact saved stage. Each project shows whether the next step is editing, review, rendering, or QC.
      </p>
      <ul className="space-y-3">
        {props.visibleProjects.map((p) => (
          <ProjectCard
            key={p.dir}
            p={p}
            status={props.statuses.entries[p.dir]?.status ?? null}
            statusError={props.statuses.entries[p.dir]?.error ?? null}
            onOpen={props.onOpen}
            onRemove={props.onRemove}
            onRename={props.onRename}
            onRefresh={() => props.statuses.refresh(p.dir)}
            onIngested={props.onIngested}
          />
        ))}
      </ul>
      {props.visibleProjects.length < props.projects.length && (
        <button type="button" onClick={props.onMore} className="mr-4 mt-3 text-xs text-signal hover:underline">
          Show {remaining} more {remaining === 1 ? "project" : "projects"}
        </button>
      )}
      {props.visibleProjects.length > 3 && (
        <button type="button" onClick={props.onFewer} className="mt-3 text-xs text-signal hover:underline">
          Show fewer projects
        </button>
      )}
    </section>
  );
}

function ProjectLoadNotice({
  error,
  hasProjects,
  onRetry,
}: {
  error: string;
  hasProjects: boolean;
  onRetry: () => void;
}) {
  return (
    <div className="my-8 rounded-lg border border-signal/30 bg-signal/5 p-4" role="alert">
      <p className="text-sm font-medium text-signal">
        {hasProjects ? "Could not refresh saved projects; showing the last known list." : "Saved projects are temporarily unavailable."}
      </p>
      <p className="mt-1 text-xs text-muted-foreground">{error} Your projects are still on disk.</p>
      <Button variant="outline" size="sm" onClick={onRetry} className="mt-3">Try again</Button>
    </div>
  );
}
