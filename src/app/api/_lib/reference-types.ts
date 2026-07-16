export type ReferenceMode = "short" | "longform";
export type ReferenceStrategy = "mimic" | "extend" | "new-style";

export interface ReferenceDecision {
  schemaVersion: 1;
  referenceId: string;
  mode: ReferenceMode;
  strategy: ReferenceStrategy;
  targetStyle: string | null;
  candidateStyleName: string | null;
  decidedAt: string;
}

export interface ReferenceSourceProfile {
  video: string;
  sha256: string;
  width: number | null;
  height: number | null;
  fps: number | null;
  durationS: number | null;
  aspect: string | null;
}

export interface ReferenceStyleProfile {
  schemaVersion: 1;
  referenceId: string;
  title: string;
  source: ReferenceSourceProfile;
  suggestedMode: ReferenceMode | null;
  suggestedKnownStyle: "caleb" | "jadenly" | "angela" | null;
  mechanics: {
    cutsPerMin: number | null;
    shotMedianS: number | null;
    longestStaticS: number | null;
    eventCounts: Record<string, number>;
    eventRatesPerMin: Record<string, number>;
    transitionClasses: Record<string, number>;
    captions: {
      detected: boolean | null;
      positionBand: string | null;
      cuesPerMin: number | null;
      wordsPerCueMean: number | null;
      karaoke: boolean | null;
    };
    colors: { text: string[]; background: string[] };
    audio: {
      integratedLufs: number | null;
      musicLabel: string | null;
      musicConfidence: string | null;
    };
  };
  quality: {
    unclassifiedRuns: number | null;
    wordLockAvailable: boolean;
    wordLockWithin150msPct: number | null;
    semanticsRan: boolean;
  };
  representativeFrames: string[];
}

export interface ReferenceMetadata {
  fileName: string;
  bytes: number;
  mtimeMs: number;
  width: number | null;
  height: number | null;
  fps: number | null;
  durationS: number | null;
  aspect: string | null;
  orientation: "portrait" | "landscape" | "square" | null;
  transcriptPath: string | null;
  sourceUrl: string | null;
}

export interface ReferenceEntry {
  id: string;
  dir: string;
  title: string;
  exists: boolean;
  video: string;
  studied: boolean;
  cli: string;
  metadata: ReferenceMetadata;
  profile: ReferenceStyleProfile | null;
  decision: ReferenceDecision | null;
  status: {
    state: "not-studied" | "invalid" | "needs-decision" | "ready";
    deepStudyPath: string | null;
    fingerprintPath: string | null;
    profilePath: string | null;
    decisionPath: string;
  };
}
