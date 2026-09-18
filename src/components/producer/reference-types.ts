import type { ReferenceIntent } from "@/lib/producer/intent-presets";

export type { ReferenceIntent };

export type ReferenceMode = ReferenceIntent["mode"];
export type ReferenceStrategy = ReferenceIntent["strategy"];
export type KnownReferenceStyle = NonNullable<ReferenceIntent["targetStyle"]>;

export interface ReferenceDecision {
  mode: ReferenceMode;
  strategy: ReferenceStrategy;
  targetStyle?: KnownReferenceStyle | null;
  candidateStyleName?: string | null;
}

export interface ReferenceSourceProfile {
  width?: number | null;
  height?: number | null;
  durationS?: number | null;
  fps?: number | null;
}

export interface ReferenceMetadata extends ReferenceSourceProfile {
  fileName?: string;
  bytes?: number;
  mtimeMs?: number;
  aspect?: number | string;
  orientation?: string;
  transcriptPath?: string | null;
}

export interface ReferenceProfile {
  schemaVersion?: number;
  referenceId?: string;
  title?: string;
  suggestedMode?: ReferenceMode | null;
  modeSuggestion?: ReferenceMode;
  suggestedKnownStyle?: KnownReferenceStyle | null;
  modeConfidence?: number;
  source?: ReferenceSourceProfile;
  width?: number;
  height?: number;
  durationS?: number;
  mechanics?: ReferenceMechanics;
  quality?: ReferenceQuality;
  representativeFrames?: string[];
}

export interface ReferenceMechanics {
  cutsPerMin?: number | null;
  shotMedianS?: number | null;
  eventCounts?: Record<string, number>;
  captions?: { detected?: boolean | null };
  audio?: { musicLabel?: string | null };
}

export interface ReferenceQuality {
  ready?: boolean;
  warnings?: string[];
  unclassifiedRuns?: number;
  wordLockAvailable?: boolean;
  [key: string]: unknown;
}

export interface ReferenceStatus {
  state: "not-studied" | "invalid" | "needs-decision" | "ready";
  deepStudyPath?: string | null;
  fingerprintPath?: string | null;
  profilePath?: string | null;
  decisionPath?: string | null;
}

export interface ReferenceEntry {
  id: string;
  dir: string;
  title: string;
  video: string | null;
  studied: boolean;
  status: ReferenceStatus | string;
  metadata?: ReferenceMetadata | null;
  profile?: ReferenceProfile | null;
  decision?: ReferenceDecision | null;
  quality?: ReferenceQuality | null;
  exists?: boolean;
  error?: string | null;
  updatedAt?: string;
}

export interface StudyActivity {
  running: boolean;
  label: string;
  percent?: number;
}

export const KNOWN_STYLES: Array<{ id: KnownReferenceStyle; label: string }> = [
  { id: "caleb", label: "Caleb" },
  { id: "jadenly", label: "Jaden" },
  { id: "angela", label: "Angela" },
];

export function suggestedMode(reference: ReferenceEntry): ReferenceMode | undefined {
  return reference.profile?.suggestedMode ?? reference.profile?.modeSuggestion ?? undefined;
}

export function referenceIntent(reference: ReferenceEntry): ReferenceIntent | null {
  const decision = reference.decision;
  if (!decision) return null;
  if (typeof reference.status !== "string" && reference.status.state !== "ready") return null;
  if (typeof reference.status === "string" && !reference.studied) return null;
  return {
    id: reference.id,
    title: reference.title,
    mode: decision.mode,
    strategy: decision.strategy,
    ...(decision.targetStyle ? { targetStyle: decision.targetStyle } : {}),
    ...(decision.candidateStyleName ? { candidateStyleName: decision.candidateStyleName } : {}),
  };
}

export function formatDuration(seconds?: number | null): string | null {
  if (typeof seconds !== "number" || !Number.isFinite(seconds)) return null;
  const minutes = Math.floor(seconds / 60);
  const remainder = Math.round(seconds % 60);
  return minutes ? `${minutes}m ${remainder}s` : `${remainder}s`;
}
