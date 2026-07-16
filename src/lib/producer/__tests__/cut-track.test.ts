// addSourceRange assertions — run with: npx tsx src/lib/producer/__tests__/cut-track.test.ts
import assert from "node:assert/strict";
import { addSourceRange, removeSourceRange } from "../cut-track";
import type { CutSegment } from "../edit-plan";

const seg = (sourceId: string, start: number, end: number, speed?: number): CutSegment =>
  speed === undefined ? { sourceId, start, end } : { sourceId, start, end, speed };

// 1) Restore a middle span that touches BOTH neighbors → one merged segment.
{
  const track = [seg("a", 0, 10), seg("a", 14, 20)];
  const out = addSourceRange(track, "a", 10, 14);
  assert.deepEqual(out, [seg("a", 0, 20)], "middle span should merge both neighbors into one");
}

// 2) Adjacent-touch merge: range touching only the PREVIOUS segment extends it.
{
  const track = [seg("a", 0, 10), seg("a", 20, 30)];
  const out = addSourceRange(track, "a", 10, 15);
  assert.deepEqual(out, [seg("a", 0, 15), seg("a", 20, 30)], "touching prev should extend it only");
}

// 2b) …and touching only the NEXT segment extends its start.
{
  const track = [seg("a", 0, 10), seg("a", 20, 30)];
  const out = addSourceRange(track, "a", 16, 20);
  assert.deepEqual(out, [seg("a", 0, 10), seg("a", 16, 30)], "touching next should extend its start");
}

// 3) Cross-source untouched: other sources pass through byte-identical.
{
  const track = [seg("b", 0, 5), seg("a", 0, 10), seg("b", 5, 9), seg("a", 14, 20)];
  const out = addSourceRange(track, "a", 10, 14);
  assert.deepEqual(
    out,
    [seg("b", 0, 5), seg("a", 0, 20), seg("b", 5, 9)],
    "same-source merge must not disturb other-source segments",
  );
  // input untouched (pure)
  assert.deepEqual(track, [seg("b", 0, 5), seg("a", 0, 10), seg("b", 5, 9), seg("a", 14, 20)]);
}

// 4) No touching segment → fresh 1x segment inserted in source order.
{
  const track = [seg("a", 0, 10), seg("a", 30, 40)];
  const out = addSourceRange(track, "a", 15, 20);
  assert.deepEqual(out, [seg("a", 0, 10), seg("a", 15, 20), seg("a", 30, 40)], "gap restore inserts in order");
}

// 4b) Range before every same-source segment inserts FIRST.
{
  const track = [seg("b", 0, 3), seg("a", 30, 40)];
  const out = addSourceRange(track, "a", 5, 10);
  assert.deepEqual(out, [seg("b", 0, 3), seg("a", 5, 10), seg("a", 30, 40)]);
}

// 5) Overlapping restore unions (no double coverage, no split).
{
  const track = [seg("a", 0, 10)];
  const out = addSourceRange(track, "a", 8, 14);
  assert.deepEqual(out, [seg("a", 0, 14)]);
}

// 6) Speed carried through a merge; mixed speeds fail loudly.
{
  const track = [seg("a", 0, 10, 1.1), seg("a", 14, 20, 1.1)];
  assert.deepEqual(addSourceRange(track, "a", 10, 14), [seg("a", 0, 20, 1.1)]);
  const mixed = [seg("a", 0, 10, 1.1), seg("a", 14, 20, 1.25)];
  assert.throws(() => addSourceRange(mixed, "a", 10, 14), /different speeds/);
}

// 7) Round-trip: cut a middle span, then restore it → the original take heals.
{
  const track = [seg("a", 0, 30)];
  const cut = removeSourceRange(track, "a", 10, 14);
  assert.deepEqual(cut, [seg("a", 0, 10), seg("a", 14, 30)]);
  assert.deepEqual(addSourceRange(cut, "a", 10, 14), [seg("a", 0, 30)]);
}

// 8) Degenerate range (end <= start) is a no-op copy.
{
  const track = [seg("a", 0, 10)];
  assert.deepEqual(addSourceRange(track, "a", 5, 5), [seg("a", 0, 10)]);
}

console.log("cut-track.test.ts: all assertions passed");
