/** Pure request/occurrence projection; no accepted-cut, asset-clock or execution authority. */
import { parsePositiveRationalV1 } from "@/lib/producer/contracts/positive-rational";
import { assertPresenterLayoutGeometry, type PresenterLayoutV1 } from "@/lib/producer/contracts/presenter-layout-v1";
import { parseTreatmentProposalV8, type TreatmentProposalV8 } from "@/lib/producer/contracts/treatment-proposal-v8";
import { objectValue, stringValue } from "@/lib/producer/contracts/validation";

export interface GuidedPresenterWindow {
  operationIndex: number; startFrame: number; endFrameExclusive: number; layout: PresenterLayoutV1;
}
export interface GuidedPresenterFrameEvidence {
  target: Record<string, unknown>; frameRate: string; totalFrames: number; anchors: number[];
  segments: Array<{ index: number; sourceId: string; startFrame: number; endFrameExclusive: number }>;
}

function frame(value: unknown, label: string, maximum: number): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || Object.is(value, -0) || value < 0 || value > maximum) {
    throw new Error(`Presenter ${label} requires a bounded canonical frame integer`);
  }
  return value;
}

function assertClock(evidence: GuidedPresenterFrameEvidence): void {
  const rate = stringValue(evidence.frameRate, "presenter frameRate", 64).split("/");
  if (rate.length !== 2) throw new Error("Presenter requires an exact rational frame rate");
  const parsed = parsePositiveRationalV1({ numerator: rate[0], denominator: rate[1] });
  if (![parsed.numerator, parsed.denominator].every(item => Number.isSafeInteger(Number(item)))) {
    throw new Error("Presenter frame-rate components exceed the safe-integer class");
  }
  if (!frame(evidence.totalFrames, "totalFrames", 1_000_000_000)) throw new Error("Presenter requires a positive program clock");
  const anchors = evidence.anchors;
  if (!Array.isArray(anchors) || anchors.length < 2 || anchors.length > 60_002
      || anchors[0] !== 0 || anchors.at(-1) !== evidence.totalFrames) throw new Error("Presenter anchors must cover the full program");
  anchors.forEach((value, index) => {
    frame(value, "anchor", evidence.totalFrames);
    if (index > 0 && value <= anchors[index - 1]) throw new Error("Presenter anchors must be strictly ordered and unique");
  });
}

function assertSegments(evidence: GuidedPresenterFrameEvidence): void {
  const segments = evidence.segments, anchors = new Set(evidence.anchors);
  if (!Array.isArray(segments) || !segments.length || segments.length > 60_001) throw new Error("Presenter requires bounded retained segments");
  let next = 0;
  for (const [index, raw] of segments.entries()) {
    const row = objectValue(raw, "presenter retained segment");
    const start = frame(row.startFrame, "segment start", evidence.totalFrames);
    const end = frame(row.endFrameExclusive, "segment end", evidence.totalFrames);
    if (row.index !== index || start !== next || end <= start || !anchors.has(start) || !anchors.has(end)) {
      throw new Error("Presenter retained segments must be an exact contiguous anchored partition");
    }
    stringValue(row.sourceId, "presenter retained sourceId", 128); next = end;
  }
  if (next !== evidence.totalFrames) throw new Error("Presenter retained segments do not cover the full program");
}

function windowFromOperation(input: { proposal: TreatmentProposalV8; evidence: GuidedPresenterFrameEvidence; operationIndex: number }): GuidedPresenterWindow {
  const { evidence, operationIndex } = input, operation = input.proposal.operations[operationIndex];
  const startFrame = frame(evidence.anchors[operation.startAnchor!], "window start", evidence.totalFrames);
  const endFrameExclusive = frame(evidence.anchors[operation.endAnchorExclusive!], "window end", evidence.totalFrames);
  const layout = operation.presenterLayout!;
  if (startFrame + layout.enterFrames > endFrameExclusive - 1 - layout.exitFrames) {
    throw new Error("Presenter window cannot contain both complete positive ramps and a full-layout hold frame");
  }
  const sources = [...new Set(evidence.segments.filter(segment => segment.endFrameExclusive > startFrame
    && segment.startFrame < endFrameExclusive).map(segment => segment.sourceId))];
  if (!sources.length || sources.length !== layout.sourceIds.length || sources.some((id, index) => id !== layout.sourceIds[index])) {
    throw new Error("Presenter sourceIds differ from ordered overlapping retained source occurrences");
  }
  const target = objectValue(evidence.target, "presenter target");
  assertPresenterLayoutGeometry(layout, { width: target.width as number, height: target.height as number });
  return { operationIndex, startFrame, endFrameExclusive, layout: structuredClone(layout) };
}

/** Independently rederive real V8 windows, retaining original indices while ordering the new track. */
export function guidedPresenterWindows(proposal: TreatmentProposalV8, evidence: GuidedPresenterFrameEvidence): GuidedPresenterWindow[] {
  const current = parseTreatmentProposalV8(proposal);
  const indices = current.operations.flatMap((operation, index) => operation.type === "presenter-layout-window" ? [index] : []);
  if (!indices.length) return [];
  if (indices.length > 32) throw new Error("Presenter layout supports at most 32 explicit windows");
  assertClock(evidence); assertSegments(evidence);
  const windows = indices.map(operationIndex => windowFromOperation({ proposal: current, evidence, operationIndex }))
    .sort((left, right) => left.startFrame - right.startFrame || left.operationIndex - right.operationIndex);
  if (windows.some((window, index) => index > 0 && window.startFrame < windows[index - 1].endFrameExclusive)) {
    throw new Error("Presenter layout windows overlap; no last-writer-wins layout");
  }
  return windows;
}
