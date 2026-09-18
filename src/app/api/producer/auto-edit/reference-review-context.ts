import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { AutoEditError } from "./stream";

export interface ReferenceReviewText {
  label: string;
  sourcePath: string;
  byteHash: string;
  content: string;
}

type Json = Record<string, unknown>;
const MAX_EVENT_SAMPLES = 64;
const MAX_COUNT_KEYS = 128;

function object(value: unknown): Json {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Json : {};
}

function rows(value: unknown): Json[] {
  return Array.isArray(value) ? value.map(object) : [];
}

function token(value: unknown): string | null {
  return typeof value === "string" && value ? value.slice(0, 64) : null;
}

function finite(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function counts(values: unknown[]): Record<string, number> {
  const raw: Record<string, number> = {};
  for (const value of values) {
    const key = token(value);
    if (!key) continue;
    raw[key] = (raw[key] ?? 0) + 1;
  }
  return Object.fromEntries(Object.entries(raw)
    .sort(([leftKey, left], [rightKey, right]) => right - left || leftKey.localeCompare(rightKey))
    .slice(0, MAX_COUNT_KEYS));
}

function sampleIndexes(length: number): number[] {
  if (length <= MAX_EVENT_SAMPLES) return Array.from({ length }, (_, index) => index);
  return Array.from({ length: MAX_EVENT_SAMPLES }, (_, index) =>
    Math.round(index * (length - 1) / (MAX_EVENT_SAMPLES - 1)));
}

function eventSample(event: Json): Json {
  const transition = object(event.transition);
  const easing = object(event.easing);
  return {
    t: finite(event.t),
    type: token(event.type),
    durationFrames: finite(event.durationFrames),
    bbox: Array.isArray(event.bbox) ? event.bbox.slice(0, 4).map(finite) : null,
    coverage: finite(event.coverage),
    magnitude: finite(event.magnitude),
    transition: {
      class: token(transition.class),
      direction: token(transition.direction),
      frames: finite(transition.frames),
    },
    easing: { bestFit: token(easing.bestFit), r2: finite(easing.r2) },
  };
}

function eventMechanics(events: Json[]): Json {
  const transitions = events.map((event) => object(event.transition));
  const easing = events.map((event) => object(event.easing));
  return {
    eventCount: events.length,
    eventTypes: counts(events.map((event) => event.type)),
    transitionClasses: counts(transitions.map((transition) => transition.class)),
    transitionDirections: counts(transitions.map((transition) => transition.direction)),
    easingFamilies: counts(easing.map((curve) => curve.bestFit)),
    sampledEvents: sampleIndexes(events.length).map((index) => eventSample(events[index])),
  };
}

function captionSummary(text: Json): Json {
  const captions = object(text.captions);
  return {
    detected: typeof captions.detected === "boolean" ? captions.detected : null,
    positionBand: token(captions.positionBand),
    cuesPerMin: finite(captions.cuesPerMin),
    wordsPerCueMean: finite(captions.wordsPerCueMean),
    karaoke: typeof captions.karaoke === "boolean" ? captions.karaoke : null,
    cueCount: rows(captions.cues).length,
  };
}

function deepStudySummary(value: Json, sourceHash: string): Json {
  const events = rows(value.events);
  const text = object(value.text);
  const wordLock = object(value.wordLock);
  const semantics = object(value.semantics);
  const source = object(value.source);
  const params = object(value.params);
  return {
    schemaVersion: 1,
    kind: "bounded-reference-mechanics",
    sourceByteHash: sourceHash,
    source: {
      width: finite(source.width), height: finite(source.height),
      fps: finite(source.fps), durationS: finite(source.durationS),
      frameCount: finite(source.frameCount),
    },
    params: { fps: finite(params.fps), semantics: params.semantics === true },
    mechanics: eventMechanics(events),
    text: {
      graphicObservationCount: rows(text.graphics).length,
      stateObservationCount: rows(text.states).length,
      captions: captionSummary(text),
    },
    wordLock: {
      availableEventCount: rows(wordLock.events).length,
      medianAbsDtS: finite(wordLock.medianAbsDtS),
      within150msPct: finite(wordLock.within150msPct),
      skipped: typeof wordLock.skipped === "boolean" ? wordLock.skipped : token(wordLock.skipped),
    },
    semantics: {
      ran: semantics.ran === true,
      eventCount: rows(semantics.events).length,
    },
    omitted: ["signals", "freezes", "raw OCR words", "caption cue text", "wordLock events"],
  };
}

/** Bind the full study bytes while exposing only bounded mechanics to a critic. */
export function boundedDeepStudyContext(filePath: string): ReferenceReviewText {
  const bytes = readFileSync(filePath);
  const byteHash = createHash("sha256").update(bytes).digest("hex");
  let value: unknown;
  try {
    value = JSON.parse(bytes.toString("utf8")) as unknown;
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    throw new AutoEditError(`reference deep study is invalid JSON: ${detail}`);
  }
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new AutoEditError("reference deep study must be a JSON object");
  }
  return {
    label: "reference-deep-study-bounded-mechanics",
    sourcePath: filePath,
    byteHash,
    content: JSON.stringify(deepStudySummary(value as Json, byteHash)),
  };
}
