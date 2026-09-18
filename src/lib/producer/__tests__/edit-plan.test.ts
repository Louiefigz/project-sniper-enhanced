// splitSegmentAt + cutOutputRange assertions — run with:
//   npx tsx src/lib/producer/__tests__/edit-plan.test.ts
import assert from "node:assert/strict";
import {
  cutOutputRange,
  cutWindows,
  outputToSource,
  planDuration,
  sourceToOutput,
  splitSegmentAt,
  type CutSegment,
} from "../edit-plan";

const seg = (sourceId: string, start: number, end: number, speed?: number): CutSegment =>
  speed === undefined ? { sourceId, start, end } : { sourceId, start, end, speed };

const close = (a: number, b: number, msg: string, eps = 1e-9) =>
  assert.ok(Math.abs(a - b) < eps, `${msg}: ${a} vs ${b}`);

// The c0679 shape: three kept spans of one source.
const track = [seg("raw-1", 13.28, 61.26, 1), seg("raw-1", 73.14, 114.49, 1), seg("raw-1", 124.34, 143.32, 1)];

// ---- splitSegmentAt: mid-segment ----
{
  const out = splitSegmentAt(track, 10); // output 10s → source 23.28 in segment 0
  assert.ok(out, "mid-segment split succeeds");
  assert.equal(out.length, 4, "one segment became two");
  close(out[0].end, 23.28, "left half ends at the playhead's source time");
  close(out[1].start, 23.28, "right half starts at the playhead's source time");
  assert.equal(out[1].end, 61.26, "right half keeps the original end");
  // playback is unchanged: same windows overall duration + mapping
  close(planDuration({ cutTrack: out }), planDuration({ cutTrack: track }), "duration unchanged");
  close(sourceToOutput(out, "raw-1", 23.28)!, 10, "source time still maps to output 10s");
  // source-time correctness vs cutWindows: the new seam lands exactly at output 10s
  const wins = cutWindows({ cutTrack: out });
  close(wins[0].end, 10, "new cut window boundary at the split's output time");
  // input untouched (pure)
  assert.equal(track.length, 3, "input track untouched");
  assert.equal(track[0].end, 61.26, "input segment untouched");
}

// ---- splitSegmentAt honors speed (source time ≠ output time) ----
{
  const sped = [seg("a", 0, 20, 2)]; // 10s of output
  const out = splitSegmentAt(sped, 4)!; // output 4s → source 8s
  close(out[0].end, 8, "split source time respects speed");
  close(outputToSource(out, 4)!.tSrc, 8, "outputToSource agrees at the seam");
}

// ---- splitSegmentAt: at-seam no-op ----
{
  const seamOut = cutWindows({ cutTrack: track })[0].end; // output time of the first seam
  assert.equal(splitSegmentAt(track, seamOut), null, "split exactly at a seam is a no-op");
  assert.equal(splitSegmentAt(track, seamOut + 0.005), null, "split within epsilon of a seam is a no-op");
  assert.equal(splitSegmentAt(track, 0), null, "split at 0 (start seam) is a no-op");
  assert.equal(splitSegmentAt(track, 9999), null, "split outside every window is a no-op");
  assert.equal(splitSegmentAt([], 5), null, "empty track is a no-op");
}

// ---- sourceToOutput ↔ outputToSource round trip (with speed) ----
{
  const mixed = [seg("a", 0, 10), seg("b", 5, 9), seg("a", 20, 30, 2)];
  for (const outT of [0, 3.7, 10.2, 14.05, 18.9]) {
    const src = outputToSource(mixed, outT)!;
    close(sourceToOutput(mixed, src.sourceId, src.tSrc)!, outT, `round trip out=${outT}`);
  }
}

// ---- cutOutputRange: span inside ONE window = plain strike-to-cut ----
{
  const out = cutOutputRange(track, 5, 10); // source 18.28–23.28 of segment 0
  assert.equal(out.length, 4, "one segment split into two");
  close(out[0].end, 18.28, "left keeps up to span start");
  close(out[1].start, 23.28, "right resumes at span end");
  close(planDuration({ cutTrack: out }), planDuration({ cutTrack: track }) - 5, "5s removed");
}

// ---- cutOutputRange ACROSS a cut seam: two source sub-ranges removed ----
{
  // seam 0→1 at output 47.98; span 46–50 covers 2s of segment 0 + 2s of segment 1
  const seamOut = cutWindows({ cutTrack: track })[0].end;
  const out = cutOutputRange(track, seamOut - 2, seamOut + 2);
  assert.equal(out.length, 3, "tail of seg0 and head of seg1 trimmed, no new segments");
  close(out[0].end, 61.26 - 2, "segment 0 lost its last 2 source seconds");
  close(out[1].start, 73.14 + 2, "segment 1 lost its first 2 source seconds");
  assert.equal(out[2].start, 124.34, "segment 2 untouched");
  close(planDuration({ cutTrack: out }), planDuration({ cutTrack: track }) - 4, "4s removed total");
}

// ---- cutOutputRange across a seam between DIFFERENT sources ----
{
  const multi = [seg("a", 0, 10), seg("b", 100, 110)];
  const out = cutOutputRange(multi, 8, 12); // 2s off a's tail + 2s off b's head
  assert.deepEqual(out, [seg("a", 0, 8), seg("b", 102, 110)], "per-source sub-ranges removed");
}

// ---- cutOutputRange respects speed when mapping to source ----
{
  const sped = [seg("a", 0, 20, 2)]; // output 0–10
  const out = cutOutputRange(sped, 2, 4); // source 4–8
  assert.deepEqual(out, [seg("a", 0, 4, 2), seg("a", 8, 20, 2)], "speed-scaled source removal");
}

// ---- cutOutputRange fails loudly on empty / out-of-range spans ----
assert.throws(() => cutOutputRange(track, 10, 10), /empty span/, "empty span throws");
assert.throws(() => cutOutputRange(track, 9999, 10000), /overlaps no cut window/, "outside throws");

console.log("edit-plan.test.ts: all assertions passed");
