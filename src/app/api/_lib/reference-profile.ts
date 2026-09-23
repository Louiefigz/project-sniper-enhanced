import type {
  ReferenceMode,
  ReferenceStyleProfile,
} from "./reference-types";

type Json = Record<string, unknown>;

function object(value: unknown): Json {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Json : {};
}

function objects(value: unknown): Json[] {
  return Array.isArray(value) ? value.map(object) : [];
}

function numberOrNull(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function boolOrNull(value: unknown): boolean | null {
  return typeof value === "boolean" ? value : null;
}

export function aspectLabel(width: number | null, height: number | null): string | null {
  if (!width || !height) return null;
  const ratio = width / height;
  if (Math.abs(ratio - 16 / 9) < 0.08) return "16:9";
  if (Math.abs(ratio - 9 / 16) < 0.08) return "9:16";
  if (Math.abs(ratio - 1) < 0.05) return "1:1";
  return `${width}:${height}`;
}

function suggestedMode(width: number | null, height: number | null): ReferenceMode | null {
  if (!width || !height) return null;
  return width > height ? "longform" : "short";
}

function counts(values: unknown[]): Record<string, number> {
  const out: Record<string, number> = {};
  for (const value of values) {
    if (typeof value !== "string" || !value) continue;
    out[value] = (out[value] ?? 0) + 1;
  }
  return out;
}

function rates(eventCounts: Record<string, number>, durationS: number | null): Record<string, number> {
  if (!durationS || durationS <= 0) return {};
  const minutes = durationS / 60;
  return Object.fromEntries(
    Object.entries(eventCounts).map(([key, value]) => [key, Number((value / minutes).toFixed(2))]),
  );
}

function uniqueColors(rows: Json[], key: string): string[] {
  return [...new Set(rows.map((row) => row[key]).filter((value): value is string =>
    typeof value === "string" && /^#[0-9a-f]{6}$/i.test(value),
  ))];
}

function representativeFrames(fingerprint: Json, deep: Json): string[] {
  const states = objects(fingerprint.states)
    .map((state) => state.rep_path)
    .filter((value: unknown): value is string => typeof value === "string" && value.length > 0);
  const semantic = objects(object(deep.semantics).events)
    .flatMap((event) => Array.isArray(event.frames) ? event.frames : [])
    .filter((value: unknown): value is string => typeof value === "string" && value.length > 0);
  const all = [...new Set([...states, ...semantic])];
  if (all.length <= 12) return all;
  return Array.from({ length: 12 }, (_, index) => all[Math.round(index * (all.length - 1) / 11)]);
}

function mechanics(deep: Json, fingerprint: Json,
                   durationS: number | null): ReferenceStyleProfile["mechanics"] {
  const text = object(deep.text);
  const events = objects(deep.events);
  const eventCounts = counts(events.map((event) => event.type));
  const captions = object(text.captions);
  const graphics = objects(text.graphics);
  const audio = object(fingerprint.audio);
  const music = object(audio.music);
  const pacing = object(fingerprint.pacing);
  return {
    cutsPerMin: numberOrNull(pacing.cuts_per_min),
    shotMedianS: numberOrNull(pacing.shot_p50),
    longestStaticS: numberOrNull(pacing.longest_static_s),
    eventCounts,
    eventRatesPerMin: rates(eventCounts, durationS),
    transitionClasses: counts(events.map((event) => object(event.transition).class)),
    captions: {
      detected: boolOrNull(captions.detected),
      positionBand: typeof captions.positionBand === "string" ? captions.positionBand : null,
      cuesPerMin: numberOrNull(captions.cuesPerMin),
      wordsPerCueMean: numberOrNull(captions.wordsPerCueMean),
      karaoke: boolOrNull(captions.karaoke),
    },
    colors: { text: uniqueColors(graphics, "textColor"), background: uniqueColors(graphics, "bgColor") },
    audio: {
      integratedLufs: numberOrNull(audio.integrated_lufs),
      musicLabel: typeof music.label === "string" ? music.label : null,
      musicConfidence: typeof music.confidence === "string" ? music.confidence : null,
    },
  };
}

function quality(deep: Json): ReferenceStyleProfile["quality"] {
  const wordLock = object(deep.wordLock);
  const semantics = object(deep.semantics);
  return {
    unclassifiedRuns: numberOrNull(deep.unclassifiedRuns),
    wordLockAvailable: Array.isArray(wordLock.events) && wordLock.events.length > 0,
    wordLockWithin150msPct: numberOrNull(wordLock.within150msPct),
    semanticsRan: semantics.ran === true,
  };
}

export function buildReferenceStyleProfile(args: {
  id: string;
  title: string;
  video: string;
  sha256: string;
  deep: Json;
  fingerprint?: Json | null;
}): ReferenceStyleProfile {
  const { id, title, video, deep, sha256 } = args;
  const fingerprint = args.fingerprint ?? {};
  const source = object(deep.source);
  const width = numberOrNull(source.width);
  const height = numberOrNull(source.height);
  const durationS = numberOrNull(source.durationS);
  return {
    schemaVersion: 1,
    referenceId: id,
    title,
    source: {
      video,
      sha256,
      width,
      height,
      fps: numberOrNull(source.fps),
      durationS,
      aspect: aspectLabel(width, height),
    },
    suggestedMode: suggestedMode(width, height),
    suggestedKnownStyle: null,
    mechanics: mechanics(deep, fingerprint, durationS),
    quality: quality(deep),
    representativeFrames: representativeFrames(fingerprint, deep),
  };
}
