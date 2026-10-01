/** P2-08: a native plan that binds sealed shared evidence must picture its speakers as the evidence says.
 * An output frame f of segment i shows source time `cuts[i].start + (f - segments[i].startFrame) / rate * cuts[i].speed`.
 * Faces come from the sealed speaker observations (P2-06) at their sampled source frames only: an output frame that no
 * sample reaches is unmeasured, never "face absent" (X59(4)). A face is in the picture when at least half of its box
 * lies inside an active picture view's crop; it belongs to the one person whose inclusive `faceRegion.xRange` holds its
 * centre x (none or two: unmapped). Where speaker intervals overlap, an output frame or sample belongs to the interval
 * holding the midpoint of the retained word spoken there (X127, ruled by X228); in silence, to the one that started
 * last. Admission (currency, binding agreement) lives in native-short-speaker-binding.ts; readers never judge it. */
import { NativeCheckError } from "./native-check-error";
import type { SharedSpeakerFacts, SharedSpeakerInterval } from "./native-review-shared-evidence";
import { buildNativeCanvas, type NativeBox } from "./native-short-composition";
import { nativePacingVisualWindows } from "./native-short-pacing-observations";
import type { NativeShortProjectInput } from "./native-short-project";
import { assertSharedEvidenceAdmitted } from "./native-short-speaker-binding";
import { assertSealedPhrasesKept, faceInCrop, faceOwner, nativePlanSourceSha256, nativeSpeakerPictureDecisions, noCoverageText, readBoundSharedEvidence,
  readSpeakerObservations, sealedPhraseReport, type NativeSpeakerPictureDecision, type SealedSharedEvidence,
  type SpeakerFace, type SpeakerObservations } from "./native-short-speaker-evidence";
export type { SpeakerObservations } from "./native-short-speaker-evidence";

/** One P2-08 finding over output frames `[startFrame, endFrame)`; only SP6 is not blocking. */
export interface SpeakerPictureFinding {
  code: "speaker-facts-missing" | "speaker-face-unmapped" | "speaker-not-in-picture" | "speaker-unresolved-picture"
    | "subject-leaves-picture" | "speaker-attribution-probable";
  blocking: boolean; startFrame: number; endFrame: number; sourceSeconds: [number, number]; message: string;
}
/** A decision kind whose reason the critic judges must have at least this many characters (trimmed code points). */
const MIN_REASON = 20;
/** SP5: consecutive dense samples out of the picture that count as leaving it. */
const EXIT_SAMPLES = 3;
const REASONED = new Set(["listener-reaction", "exit-cover", "accepted-exit"]);
/** Output elements that are the pictured source, its sound or its captions, never a supporting visual. */
const NOT_VISUAL = /^(?:source-|dialogue-|caption-)/u;

/** One sampled source frame where the plan shows it. */
interface Sample { frame: number; segment: number; t: number; dense: boolean; faces: SpeakerFace[]; crops: NativeBox[]; interval: number }
/** Everything the rules read, computed once. */
interface Picture {
  input: NativeShortProjectInput; facts: SharedSpeakerFacts; observations: SpeakerObservations; rate: number;
  intervals: SharedSpeakerInterval[]; regions: Array<{ id: string; xRange: [number, number] }>; samples: Sample[];
  frames: Map<number, number[]>; decisions: NativeSpeakerPictureDecision[]; visuals: () => Array<{ startFrame: number; endFrame: number }>;
}

/** The interval governing source time t (`[start, end)`; -1 for none). One holding interval governs; where several
 * hold t, the one holding the midpoint of the retained word spoken at t (unique by the seal), and in silence the one
 * that started last (equal starts: the later row). */
function governor(intervals: SharedSpeakerInterval[], words: SpeakerObservations["words"]): (t: number) => number {
  const holds = (row: SharedSpeakerInterval, doubled: number) => 2 * row.startSeconds <= doubled && doubled < 2 * row.endSeconds;
  return (t) => {
    const holding = intervals.flatMap((row, index) => (holds(row, 2 * t) ? [index] : []));
    if (holding.length < 2) return holding.length ? holding[0] : -1;
    const word = words.find((row) => row.start <= t && t < row.end);
    const spoken = word ? intervals.findIndex((row) => holds(row, word.start + word.end)) : -1;
    return spoken >= 0 ? spoken : holding.reduce((a, b) => (intervals[b].startSeconds >= intervals[a].startSeconds ? b : a));
  };
}

/** Every sampled frame the plan shows, at its output frame, with the crops active there, in output order. */
function shownSamples(input: NativeShortProjectInput, observations: SpeakerObservations, governing: (t: number) => number, rate: number): Sample[] {
  const { cuts, segments, pictureViews } = input.canvas;
  return observations.sampling.frames.flatMap((row, at) => segments.flatMap((segment, index) => {
    const cut = cuts[index], frame = segment.startFrame + Math.floor((row.t - cut.start) / cut.speed * rate + 1e-9);
    if (row.t < cut.start || frame >= segment.endFrameExclusive) return [];
    const crops = pictureViews.filter((view) => view.startFrame <= frame && frame < view.endFrame).map((view) => view.crop);
    return [{ frame, segment: index, t: row.t, dense: row.dense, faces: observations.faces[at].faces, crops, interval: governing(row.t) }];
  })).sort((a, b) => a.frame - b.frame || a.t - b.t);
}

/** Output frames per governing interval, from each frame's own source time. */
function framesByInterval(input: NativeShortProjectInput, governing: (t: number) => number, rate: number): Map<number, number[]> {
  const result = new Map<number, number[]>();
  input.canvas.segments.forEach((segment, index) => {
    const cut = input.canvas.cuts[index];
    for (let frame = segment.startFrame; frame < segment.endFrameExclusive; frame++) {
      const owner = governing(cut.start + (frame - segment.startFrame) / rate * cut.speed);
      if (!result.has(owner)) result.set(owner, []);
      result.get(owner)!.push(frame);
    }
  });
  return result;
}

/** The context every rule reads; supporting-visual windows are derived only when a decision needs them. */
function picture(input: NativeShortProjectInput, facts: SharedSpeakerFacts, observations: SpeakerObservations): Picture {
  const [num, den] = input.canvas.frameRate.split("/").map(Number), rate = num / den, source = observations.source.id;
  const intervals = facts.intervals.filter((row) => row.source === source);
  const regions = facts.people.flatMap((row) => (row.faceRegion?.source === source ? [{ id: row.id, xRange: row.faceRegion.xRange }] : []));
  let windows: Array<{ startFrame: number; endFrame: number }> | undefined;
  const visuals = () => (windows ??= nativePacingVisualWindows(input, buildNativeCanvas(input.canvas) + (input.extension?.markup ?? ""))
    .filter((row) => !NOT_VISUAL.test(row.id)));
  const governing = governor(intervals, observations.words);
  return { input, facts, observations, rate, intervals, regions, samples: shownSamples(input, observations, governing, rate),
    frames: framesByInterval(input, governing, rate), decisions: nativeSpeakerPictureDecisions(input), visuals };
}

/** People in the picture at a sample, through the given crops. */
function pictured(context: Picture, sample: Sample, crops = sample.crops): Set<string> {
  return new Set(sample.faces.filter((face) => crops.some((crop) => faceInCrop(face, crop)))
    .map((face) => faceOwner(face, context.regions)).filter((id): id is string => id !== null));
}

/** Whether one decision admits an output frame: inside it, a reasoned kind with a long enough reason, and a
 * supporting visual only where a visual window covers the frame (`nativePacingVisualWindows`). */
function admits(context: Picture, row: NativeSpeakerPictureDecision, frame: number): boolean {
  if (frame < row.startFrame || frame >= row.endFrame) return false;
  if (REASONED.has(row.kind)) return [...row.reason.trim()].length >= MIN_REASON;
  return row.kind !== "supporting-visual" || context.visuals().some((w) => w.startFrame <= frame && frame < w.endFrame);
}

/** Every frame is admitted by some decision of one of the kinds. */
function covered(context: Picture, frames: number[], kinds: readonly string[]): boolean {
  return frames.every((frame) => context.decisions.some((row) => kinds.includes(row.kind) && admits(context, row, frame)));
}

/** A finding spanning the given output frames. */
function finding(code: SpeakerPictureFinding["code"], frames: number[], seconds: [number, number], message: string): SpeakerPictureFinding {
  const first = frames.reduce((a, b) => Math.min(a, b)), last = frames.reduce((a, b) => Math.max(a, b));
  return { code, blocking: code !== "speaker-attribution-probable", startFrame: first, endFrame: last + 1, sourceSeconds: seconds, message };
}

/** Runs of adjacent items with the same non-null key. */
function runs<T>(items: T[], key: (item: T) => string | null): T[][] {
  const result: T[][] = [];
  let previous: string | null = null;
  for (const item of items) {
    const kind = key(item);
    if (kind !== null && kind === previous) result.at(-1)!.push(item);
    else if (kind !== null) result.push([item]);
    previous = kind;
  }
  return result;
}

/** Source seconds shown at an output frame's start. */
function sourceTime(context: Picture, frame: number): number {
  const index = context.input.canvas.segments.findIndex((row) => row.startFrame <= frame && frame < row.endFrameExclusive);
  const cut = context.input.canvas.cuts[index];
  return cut.start + (frame - context.input.canvas.segments[index].startFrame) / context.rate * cut.speed;
}

/** SP1 and coverage: each kept word lies in a covered clip's approved ranges, and its source midpoint in an interval. */
function factFindings(context: Picture): SpeakerPictureFinding[] {
  const { canvas } = context.input, words = new Map(context.observations.words.map((row) => [row.sourceWord, row]));
  const clips = context.facts.clips ?? [];
  const failure = (word: number) => {
    if (!clips.some((clip) => clip.wordRanges.some(([low, high]) => low <= word && word <= high))) return "uncovered";
    const row = words.get(word);
    if (!row) throw new Error(`Speaker observations lack covered source word ${word}; the record and its coverage disagree`);
    return context.intervals.some((i) => 2 * i.startSeconds <= row.start + row.end && row.start + row.end < 2 * i.endSeconds) ? null : "midpoint";
  };
  const rows = canvas.occurrences.map((row) => ({ row, kind: failure(row[2]) }));
  return runs(rows, (item) => item.kind && `${item.kind}:${item.row[1]}`).map((run) => {
    const [first, last] = [run[0].row, run.at(-1)!.row], frames = [first[3], last[4] - 1], range = `${first[2]}-${last[2]}`;
    return finding("speaker-facts-missing", frames, [sourceTime(context, first[3]), sourceTime(context, last[4] - 1)], run[0].kind === "uncovered"
      ? `retained source words ${range} lie in no clip this record covers; a clip added after sealing, or on another source, needs its own sealed record`
      : `retained source words ${range} ('${run.map((item) => item.row[5]).join(" ").slice(0, 80)}') have their midpoints in no speaker interval`);
  });
}

/** SP2 (X228's U-R7 amendment): every face in the picture (at least half inside an active crop), the faces the other
 * rules read, maps to exactly one person; a face outside every crop is not judged. */
function unmappedFindings(context: Picture): SpeakerPictureFinding[] {
  const judged = (sample: Sample) => sample.faces.filter((face) => sample.crops.some((crop) => faceInCrop(face, crop))
    && faceOwner(face, context.regions) === null);
  return runs(context.samples, (sample) => (judged(sample).length ? "unmapped" : null)).map((run) => {
    const face = judged(run[0])[0];
    return finding("speaker-face-unmapped", run.map((row) => row.frame), [run[0].t, run.at(-1)!.t], `faces at ${run.length} sampled frame(s) `
      + `have a centre in no person's face region or in two (first: centre x ${face.x + face.w / 2} at source ${run[0].t} s)`);
  });
}

/** SP3, SP4 and SP6 for one interval the plan shows. */
function intervalFindings(context: Picture, interval: SharedSpeakerInterval, index: number): SpeakerPictureFinding[] {
  const frames = context.frames.get(index) ?? [], samples = context.samples.filter((row) => row.interval === index);
  const seconds: [number, number] = [interval.startSeconds, interval.endSeconds], span = `${interval.startSeconds}-${interval.endSeconds} s`;
  if (!frames.length) return [];
  if (interval.speaker === null) {
    const twoShot = (frame: number) => context.decisions.some((row) => row.kind === "two-shot" && admits(context, row, frame));
    const support = (frame: number) => covered(context, [frame], ["supporting-visual"]);
    const bare = frames.filter((frame) => !support(frame) && !twoShot(frame));
    const missing = samples.filter((row) => !support(row.frame) && twoShot(row.frame)
      && !(interval.visible.length && interval.visible.every((person) => pictured(context, row).has(person))));
    return bare.length || missing.length ? [finding("speaker-unresolved-picture", [...bare, ...missing.map((row) => row.frame)], seconds,
      `unresolved interval ${span}: ${bare.length} frame(s) are neither a declared two-shot nor a supporting visual, and at ${missing.length} `
      + `two-shot sample(s) not everyone in [${interval.visible.join(", ")}] is in the picture`)] : [];
  }
  const speaker = interval.speaker, shown = samples.filter((row) => pictured(context, row).has(speaker));
  const result = samples.length && !shown.length && !covered(context, frames, ["supporting-visual", "listener-reaction"])
    ? [finding("speaker-not-in-picture", frames, seconds, `${interval.certainty} speaker ${speaker} is never in the picture at the `
      + `${samples.length} sampled frame(s) of interval ${span}${context.regions.some((row) => row.id === speaker) ? "" : ` (${speaker} has no face region on this source)`}; `
      + "show them, or cover these frames with a supporting-visual decision over a visual or a reasoned listener-reaction decision")] : [];
  const alone = shown.filter((row) => pictured(context, row).size === 1);
  if (interval.certainty === "probable" && alone.length) {
    result.push(finding("speaker-attribution-probable", frames, seconds, `probable speaker ${speaker} is shown alone at ${alone.length} `
      + `sampled frame(s) of interval ${span}; a final needs listening or an operator statement`));
  }
  return result;
}

/** SP5 runs in one view over one source cut: the subject in the crop at a dense sample, then out of it (or undetected)
 * for at least EXIT_SAMPLES consecutive dense samples. The subject is the governing speaker, else the only person in
 * the crop; a run ends at a non-dense sample, when its person is back, or when another speaker takes over. */
function exitRuns(context: Picture, sequence: Sample[], crop: NativeBox): Array<{ person: string; samples: Sample[] }> {
  const result: Array<{ person: string; samples: Sample[] }> = [];
  let person: string | null = null, outs: Sample[] = [];
  const close = () => { if (person !== null && outs.length >= EXIT_SAMPLES) result.push({ person, samples: outs }); person = null; outs = []; };
  for (const sample of sequence) {
    const speaker = sample.interval >= 0 ? context.intervals[sample.interval].speaker : null, inside = pictured(context, sample, [crop]);
    if (!sample.dense || (person !== null && speaker !== null && speaker !== person)) close();
    if (!sample.dense) continue;
    if (person !== null && !inside.has(person)) { outs.push(sample); continue; }
    close();
    const subject: string | null = speaker ?? (inside.size === 1 ? [...inside][0] : null);
    if (subject !== null && inside.has(subject)) person = subject;
  }
  close();
  return result;
}

/** SP5 over every picture view and source cut, less the exits an exit decision with a reason covers. */
function exitFindings(context: Picture): SpeakerPictureFinding[] {
  const { pictureViews, segments } = context.input.canvas;
  return pictureViews.flatMap((view, number) => segments.flatMap((_, index) => exitRuns(context, context.samples.filter((row) =>
    row.segment === index && view.startFrame <= row.frame && row.frame < view.endFrame), view.crop))
    .filter((run) => !covered(context, run.samples.map((row) => row.frame), ["exit-cover", "accepted-exit"]))
    .map((run) => finding("subject-leaves-picture", run.samples.map((row) => row.frame), [run.samples[0].t, run.samples.at(-1)!.t],
      `${run.person}'s face leaves picture view ${number} for ${run.samples.length} consecutive dense samples; cover the exit with an `
      + `exit-cover or accepted-exit decision whose reason has at least ${MIN_REASON} characters`)));
}

/** Every P2-08 finding for a plan against sealed speaker facts and their observations, blocking or not; never throws
 * for a finding (the build's `measure` lists them).
 * @param input the native plan
 * @param facts `sharedSpeakerFacts` of the record the plan binds
 * @param observations the speaker observations that record's coverage binds
 * @returns findings in rule order (facts and coverage, unmapped faces, intervals, exits), each by output frame
 */
export function nativeSpeakerPictureFindings(input: NativeShortProjectInput, facts: SharedSpeakerFacts,
  observations: SpeakerObservations): SpeakerPictureFinding[] {
  const planned = nativePlanSourceSha256(input), all = [0, input.canvas.totalFrames - 1];
  if (!facts.clips || observations.source.sourceSha256 !== planned) {
    return [finding("speaker-facts-missing", all, [0, 0], `the sealed speaker facts cover no clip of this plan: they measure source `
      + `${observations.source.id} (${observations.source.sourceSha256}), and this plan's source is ${planned}`)];
  }
  const context = picture(input, facts, observations);
  return [...factFindings(context), ...unmappedFindings(context),
    ...context.intervals.flatMap((row, index) => intervalFindings(context, row, index)), ...exitFindings(context)];
}

/** Refuse a plan whose picture contradicts the sealed speaker facts: one NativeCheckError whose code is the first
 * blocking finding's and whose message lists every blocking finding with its code and output frames. */
export function assertNativeSpeakerPicture(input: NativeShortProjectInput, facts: SharedSpeakerFacts, observations: SpeakerObservations): void {
  const blocking = nativeSpeakerPictureFindings(input, facts, observations).filter((row) => row.blocking);
  if (!blocking.length) return;
  throw new NativeCheckError(blocking[0].code, `Speaker picture contradicts the sealed speaker facts: ${blocking
    .map((row) => `${row.code} frames ${row.startFrame}-${row.endFrame - 1}: ${row.message}`).join("; ")}`);
}

/** The build's shared-evidence rules at admission (the project writer; never a reader): the binding agrees with the
 * review (`shared-evidence-unbound`, X229) and, when present, is current (`stale-evidence`); then (a) sealed phrases the
 * plan keeps whole are protected caption phrases, and (b) `assertNativeSpeakerPicture`. A plan that may omit it builds as before. */
export function assertNativeSharedEvidence(input: NativeShortProjectInput): void {
  assertSharedEvidenceAdmitted(input);
  const sealed = readBoundSharedEvidence(input);
  if (!sealed) return;
  assertSealedPhrasesKept(input, sealed);
  assertNativeSpeakerPicture(input, sealed.facts, readSpeakerObservations(sealed));
}

/** SP findings for a record read; a record without coverage gives its one refusal as a finding. */
function sealedFindings(input: NativeShortProjectInput, sealed: SealedSharedEvidence): SpeakerPictureFinding[] {
  if (!sealed.facts.observations) return [finding("speaker-facts-missing", [0, input.canvas.totalFrames - 1], [0, 0], noCoverageText(sealed))];
  return nativeSpeakerPictureFindings(input, sealed.facts, readSpeakerObservations(sealed));
}

/** `measure`'s view of the shared evidence (admission): every speaker-picture finding and each sealed phrase's status
 * (nulls without a binding). A finding never throws here; an unbound, stale, unreadable or foreign binding refuses. */
export function nativeSharedEvidenceMeasure(input: NativeShortProjectInput) {
  assertSharedEvidenceAdmitted(input);
  const sealed = readBoundSharedEvidence(input);
  if (!sealed) return { speakerPicture: null, protectedPhrases: null };
  return { speakerPicture: sealedFindings(input, sealed), protectedPhrases: sealedPhraseReport(input, sealed) };
}

/** SP6 as open draft findings (`SPEAKER-ATTRIBUTION-PROBABLE`), judged on the bound bytes with no currency check, so a
 * draft reader lists them; a final build refuses them and `build-draft` records them. */
export function nativeSpeakerAttributionFindings(input: NativeShortProjectInput) {
  const sealed = readBoundSharedEvidence(input);
  if (!sealed) return [];
  return sealedFindings(input, sealed).filter((row) => row.code === "speaker-attribution-probable")
    .map((row) => ({ code: "SPEAKER-ATTRIBUTION-PROBABLE", severity: "major", lane: "speaker-picture",
      message: `frames ${row.startFrame}-${row.endFrame - 1}: ${row.message}`,
      requiredAction: "Listen to the interval or record an operator statement, reseal the shared evidence, then rebuild",
      source: "shared-evidence" }));
}
