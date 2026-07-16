// cutTrack surgery — the pure SOURCE-range editing utils behind the Script
// mode's strike-to-cut ("Cut selection") and un-strike ("Restore selection").
// Split from edit-plan.ts (300-line logic budget); edit-plan re-exports both
// so consumers keep importing from "@/lib/producer/edit-plan".

import type { CutSegment } from "./edit-plan";

// removeSourceRange fragment/gap policy: fragments shorter than MIN_FRAGMENT_S
// are dropped (a sub-half-second sliver of speech reads as a glitch), and gaps
// narrower than MERGE_GAP_S are healed (two segments that nearly touch are one
// take — keeping the seam would add a pointless hard cut). BOTH passes apply
// only at the cut boundary — the split/trimmed segments and their immediate
// neighbors. Deliberate short segments and intentional micro-trims elsewhere
// in the track pass through byte-identical.
const MIN_FRAGMENT_S = 0.5;
const MERGE_GAP_S = 0.15;

function subtractRange(seg: CutSegment, start: number, end: number): CutSegment[] {
  if (end <= seg.start || start >= seg.end) return [seg]; // no overlap
  const parts: CutSegment[] = [];
  if (start > seg.start) parts.push({ ...seg, end: start });
  if (end < seg.end) parts.push({ ...seg, start: end });
  return parts; // full cover -> []
}

/**
 * A segment plus whether this subtraction made it eligible for the fragment/
 * gap passes: it was split/trimmed by the removal, or it is the immediate
 * neighbor of a seam the removal actually reached (the cut boundary).
 */
interface MarkedSegment {
  seg: CutSegment;
  eligible: boolean;
}

function mergeNearSegments(track: MarkedSegment[]): CutSegment[] {
  const out: MarkedSegment[] = [];
  for (const item of track) {
    const prev = out[out.length - 1];
    const mergeable =
      prev &&
      (prev.eligible || item.eligible) && // only heal gaps at the cut boundary
      prev.seg.sourceId === item.seg.sourceId &&
      (prev.seg.speed ?? 1) === (item.seg.speed ?? 1) &&
      item.seg.start - prev.seg.end >= 0 &&
      item.seg.start - prev.seg.end < MERGE_GAP_S;
    if (mergeable) {
      prev.seg = { ...prev.seg, end: item.seg.end };
      prev.eligible = true;
    } else {
      out.push({ ...item });
    }
  }
  return out.map((m) => m.seg);
}

/**
 * Remove the SOURCE-seconds range [start, end] of `sourceId` from a cutTrack.
 *
 * Pure: returns a new track. Overlapped segments are trimmed or split; at the
 * cut boundary (the split/trimmed segments, plus an immediate neighbor when
 * the removal reaches the seam it shares — i.e. covers the touched segment's
 * start or end edge) leftover fragments shorter than 0.5s are dropped and
 * same-source gaps narrower than 0.15s are merged. Segments the subtraction
 * did not touch pass through byte-identical — never dropped or re-merged.
 */
export function removeSourceRange(
  cutTrack: CutSegment[],
  sourceId: string,
  start: number,
  end: number,
): CutSegment[] {
  const marked: MarkedSegment[] = [];
  let cutReachesNext = false; // removal covered the previous segment's END → the next seam is at the cut
  for (const seg of cutTrack) {
    const overlaps = seg.sourceId === sourceId && end > seg.start && start < seg.end;
    if (!overlaps) {
      marked.push({ seg: { ...seg }, eligible: cutReachesNext });
      cutReachesNext = false;
      continue;
    }
    // Removal covers this segment's START edge → the seam to the previous
    // element is at the cut boundary; that immediate neighbor becomes eligible.
    if (start <= seg.start && marked.length) marked[marked.length - 1].eligible = true;
    for (const part of subtractRange(seg, start, end)) marked.push({ seg: part, eligible: true });
    cutReachesNext = end >= seg.end;
  }
  const kept = marked.filter((m) => !m.eligible || m.seg.end - m.seg.start >= MIN_FRAGMENT_S);
  return mergeNearSegments(kept);
}

/**
 * Cut an OUTPUT-time span [outStart, outEnd] out of the track — the ruler
 * range-select "Cut section". The span is first resolved to SOURCE sub-ranges
 * against the ORIGINAL track (one per cut segment it overlaps, so a span
 * crossing a cut seam yields one sub-range per underlying source segment),
 * then each sub-range is removed with `removeSourceRange` — the semantics
 * (fragment drop + gap heal at the cut boundary) match strike-to-cut exactly.
 * Throws when the span overlaps no cut window — fail loudly, never silently.
 */
export function cutOutputRange(
  cutTrack: CutSegment[],
  outStart: number,
  outEnd: number,
): CutSegment[] {
  if (!(outEnd > outStart)) throw new Error(`cutOutputRange: empty span ${outStart}–${outEnd}s`);
  const pieces: { sourceId: string; start: number; end: number }[] = [];
  let acc = 0;
  for (const c of cutTrack) {
    const speed = c.speed ?? 1;
    const len = (c.end - c.start) / speed;
    const a = Math.max(outStart, acc);
    const b = Math.min(outEnd, acc + len);
    if (b > a) {
      pieces.push({
        sourceId: c.sourceId,
        start: c.start + (a - acc) * speed,
        end: c.start + (b - acc) * speed,
      });
    }
    acc += len;
  }
  if (!pieces.length) {
    throw new Error(`cutOutputRange: span ${outStart}–${outEnd}s overlaps no cut window`);
  }
  return pieces.reduce((ct, p) => removeSourceRange(ct, p.sourceId, p.start, p.end), cutTrack);
}

/**
 * Restore (un-cut) the SOURCE-seconds range [start, end] of `sourceId` into a
 * cutTrack — the inverse gesture of `removeSourceRange`.
 *
 * Pure: returns a new track; segments of OTHER sources pass through
 * byte-identical. The restored range is UNIONED with every same-source segment
 * it overlaps or touches (boundary-equal counts as touching), so no segment is
 * ever split and adjacent segments heal into one. When it touches nothing, a
 * fresh 1x segment is inserted at the source-order position among the
 * same-source segments. Merging across segments with differing `speed` is
 * ambiguous (which rate wins?) — fail loudly rather than guess.
 */
export function addSourceRange(
  cutTrack: CutSegment[],
  sourceId: string,
  start: number,
  end: number,
): CutSegment[] {
  if (!(end > start)) return cutTrack.map((s) => ({ ...s }));
  const touches = (seg: CutSegment): boolean =>
    seg.sourceId === sourceId && seg.end >= start && seg.start <= end;
  const touchedIdx = cutTrack.map((s, i) => (touches(s) ? i : -1)).filter((i) => i >= 0);

  if (touchedIdx.length === 0) {
    // Fresh segment — insert in source order among the same-source segments:
    // after the last one that ends at/before `start`, else before the first
    // same-source segment (the range precedes them all), else append.
    const seg: CutSegment = { sourceId, start, end };
    let at = cutTrack.length;
    const lastBefore = cutTrack
      .map((s, i) => (s.sourceId === sourceId && s.end <= start ? i : -1))
      .filter((i) => i >= 0)
      .pop();
    const firstSame = cutTrack.findIndex((s) => s.sourceId === sourceId);
    if (lastBefore !== undefined) at = lastBefore + 1;
    else if (firstSame >= 0) at = firstSame;
    const out = cutTrack.map((s) => ({ ...s }));
    out.splice(at, 0, seg);
    return out;
  }

  const speeds = new Set(touchedIdx.map((i) => cutTrack[i].speed ?? 1));
  if (speeds.size > 1) {
    throw new Error(
      `addSourceRange: restore span touches segments with different speeds (${[...speeds].join(", ")}) — split the restore`,
    );
  }
  const merged: CutSegment = {
    ...cutTrack[touchedIdx[0]],
    start: Math.min(start, ...touchedIdx.map((i) => cutTrack[i].start)),
    end: Math.max(end, ...touchedIdx.map((i) => cutTrack[i].end)),
  };
  const out: CutSegment[] = [];
  cutTrack.forEach((s, i) => {
    if (i === touchedIdx[0]) out.push(merged);
    else if (!touchedIdx.includes(i)) out.push({ ...s });
  });
  return out;
}
