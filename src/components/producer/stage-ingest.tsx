"use client";

import { Button } from "@/components/ui/button";
import { dlog } from "@/lib/debug";
import type { IntentCapabilityDecision } from "@/lib/producer/intent-capabilities";
import type { ProjectIntent } from "@/lib/producer/intent-presets";
import { readEventStream } from "@/lib/producer/sse";
import type { AssetManifest } from "@/lib/producer/types";
import { ActionShell, Spinner, type SseState } from "./stage-action-status";
import type { ProjectStatus } from "./use-project-status";

export interface IngestedPayload {
  inputPath: string;
  manifestPath: string;
  outDir: string;
  manifest: AssetManifest;
  requestedIntent?: ProjectIntent;
  intent?: ProjectIntent;
  intentDecisions?: IntentCapabilityDecision[];
}

/** Prepare one source file/directory and return its persisted manifest. */
export async function ingestInto(
  inputPath: string,
  projectRoot: string | null,
  onIngested?: (payload: IngestedPayload) => void,
  onEvent: (event: Record<string, unknown>) => void = () => {},
): Promise<void> {
  dlog("producer:stage-action", "ingest", { inputPath, projectRoot });
  const response = await fetch("/api/producer/ingest", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(projectRoot ? { inputPath, projectRoot } : { inputPath }),
  });
  await readEventStream(response, (event) => {
    onEvent(event as Record<string, unknown>);
    if (event.event === "error") throw new Error(String(event.message ?? "stream error"));
    if (event.event !== "manifest" || !onIngested) return;
    onIngested({
      inputPath,
      manifestPath: event.manifestPath as string,
      outDir: event.outDir as string,
      manifest: event.manifest as AssetManifest,
      requestedIntent: (event.requestedIntent as ProjectIntent | null) ?? undefined,
      intent: (event.intent as ProjectIntent | null) ?? undefined,
      intentDecisions: (event.intentDecisions as IntentCapabilityDecision[] | null) ?? [],
    });
  }, undefined, "manifest");
}

interface IngestActionProps {
  status: ProjectStatus;
  state: SseState;
  run: (operation: SseState["operation"], action: () => Promise<void>) => void;
  onEvent: (event: Record<string, unknown>) => void;
  primary: boolean;
  reingest: boolean;
  onIngested?: (payload: IngestedPayload) => void;
}

export function IngestAction(props: IngestActionProps) {
  const source = props.status.sourceDir;
  if (!source) return null;
  const title = props.reingest
    ? "Prepare this media again and create its missing transcript"
    : "Prepare this media for video creation";
  return (
    <ActionShell state={props.state}>
      <Button variant={props.primary ? "default" : "ghost"} size="xs"
        disabled={props.state.running} title={title}
        onClick={() => props.run("ingest", () => ingestInto(
          source, props.status.projectRoot, props.onIngested, props.onEvent,
        ))}>
        <Spinner on={props.state.running} /> {props.reingest ? "Analyze speech" : "Prepare media"}
      </Button>
    </ActionShell>
  );
}
