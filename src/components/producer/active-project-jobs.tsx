"use client";

import { ExternalLink, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { canOpenProject } from "@/lib/producer/project-state";
import { RunProgress, StopRunControl } from "./stage-action-status";
import type { Listing } from "./project-card";
import type { ProjectStatusEntry } from "./use-project-status";

interface ActiveProjectJobsProps {
  projects: Listing[];
  entries: Record<string, ProjectStatusEntry>;
  onOpen: (dir: string, displayName?: string) => void;
  onRefresh: (dir: string) => void;
}

export default function ActiveProjectJobs(props: ActiveProjectJobsProps) {
  const active = props.projects.flatMap((project) => {
    const status = props.entries[project.dir]?.status;
    return status?.run?.status === "running" ? [{ project, status, run: status.run }] : [];
  });
  if (!active.length) return null;
  return (
    <aside className="my-8 rounded-lg border border-signal/40 bg-signal/5 p-4" aria-labelledby="active-project-jobs-title">
      <div className="flex items-center gap-2">
        <Loader2 className="size-4 animate-spin text-signal" />
        <h2 id="active-project-jobs-title" className="text-sm font-semibold text-foreground">
          {active.length === 1 ? "1 project is running" : `${active.length} projects are running`}
        </h2>
      </div>
      <p className="mt-1 text-xs text-muted-foreground">
        These jobs keep running if you leave this page or start another project.
      </p>
      <ul className="mt-3 space-y-2">
        {active.map(({ project, status, run }) => (
          <li key={project.dir} className="flex flex-col gap-2 rounded border border-border/70 bg-background/50 p-3 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0">
              <p className="truncate text-xs font-medium text-foreground">{project.title}</p>
              <p className="truncate font-mono text-[10px] text-muted-foreground/60" title={project.dir}>
                {status.projectRoot?.split("/").pop() ?? project.dir.split("/").pop()}
              </p>
              <RunProgress run={run} align="left" />
            </div>
            <div className="flex flex-wrap items-start justify-end gap-1.5">
              {canOpenProject(status.stages) && (
                <Button variant="outline" size="xs" onClick={() => props.onOpen(status.producerDir, project.title)}>
                  <ExternalLink className="size-3" /> View saved timeline
                </Button>
              )}
              {run.kind === "auto_edit" && (
                <StopRunControl run={run} dir={status.producerDir} onStopped={() => props.onRefresh(project.dir)} />
              )}
            </div>
          </li>
        ))}
      </ul>
    </aside>
  );
}
