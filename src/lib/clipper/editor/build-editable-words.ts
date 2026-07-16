import { TranscriptEntry, LineDecision, EditableWord, WordTiming } from "@/lib/clipper/types";
import { normalizeWord } from "./normalize";
import { greedyMatch } from "./greedy-match";

/**
 * Build a flat array of EditableWords from the transcript and LLM decisions.
 *
 * - "remove" utterances: all words marked removed=true
 * - "keep" utterances: all words marked removed=false
 * - "trim" utterances: greedy forward scan to match trimmed text against source
 *   words (non-contiguous OK); unmatched words marked removed; on failure keep all.
 *
 * If an utterance has no word-level data, timestamps are interpolated
 * evenly across the utterance duration as a fallback.
 */
export function buildEditableWords(
  transcript: TranscriptEntry[],
  decisions: LineDecision[]
): EditableWord[] {
  const decisionMap = new Map(decisions.map((d) => [d.index, d]));
  const allWords: EditableWord[] = [];

  // Helper: get word timings for a transcript entry, synthesising if missing.
  const getSourceWords = (seg: TranscriptEntry): WordTiming[] =>
    seg.words && seg.words.length > 0
      ? seg.words
      : seg.text
          .split(/\s+/)
          .filter(Boolean)
          .map((w, i, arr) => {
            const d = (seg.end - seg.start) / arr.length;
            return { word: w, start: seg.start + i * d, end: seg.start + (i + 1) * d };
          });

  // ── Pre-compute removedIndices for every utterance ──────────────────────────
  //
  // When the LLM merges adjacent utterances it puts the combined TRIM text on
  // index N and marks N+1, N+2, … as REMOVE. The old matcher only looked at
  // utterance N's words, so the trim tokens that came from N+1/N+2 caused the
  // match to fail and fall back to "keep all". This pre-pass fixes that by
  // expanding the word pool through subsequent consecutive REMOVE'd utterances.
  //
  const LOOKAHEAD = 10;
  const MATCH_THRESHOLD = 0.8;
  type Removal = "all" | "none" | Set<number>;
  const resolvedRemovals = new Map<number, Removal>();

  for (let i = 0; i < transcript.length; i++) {
    if (resolvedRemovals.has(i)) continue; // already set by a prior expanded match

    const decision = decisionMap.get(i);
    const action = decision?.action ?? "keep";

    if (action === "remove") {
      resolvedRemovals.set(i, "all");
      continue;
    }

    if (action === "keep" || !decision?.text) {
      resolvedRemovals.set(i, "none");
      continue;
    }

    // action === "trim"
    const sourceWords = getSourceWords(transcript[i]);
    const trimTokens = decision.text.split(/\s+/).filter(Boolean).map(normalizeWord);
    const normSource = sourceWords.map((w) => normalizeWord(w.word));

    // Greedy forward scan against utterance i alone
    const kept = greedyMatch(trimTokens, normSource);
    const matchPct = trimTokens.length > 0 ? kept.size / trimTokens.length : 0;
    const matchPassed = matchPct >= MATCH_THRESHOLD;

    if (matchPassed) {
      const removed = new Set<number>();
      sourceWords.forEach((_, wi) => { if (!kept.has(wi)) removed.add(wi); });
      resolvedRemovals.set(i, removed);
      continue;
    }

    // ── Expanded match: absorb subsequent consecutive REMOVE'd utterances ────
    type PoolWord = { word: string; utterIdx: number; wordIdx: number };
    const pool: PoolWord[] = sourceWords.map((w, wi) => ({ word: w.word, utterIdx: i, wordIdx: wi }));
    let expandedCount = 0;

    for (let j = i + 1; j < transcript.length && j <= i + LOOKAHEAD; j++) {
      const jAction = (decisionMap.get(j)?.action) ?? "keep";
      if (jAction !== "remove") break;
      getSourceWords(transcript[j]).forEach((w, wi) =>
        pool.push({ word: w.word, utterIdx: j, wordIdx: wi })
      );
      expandedCount++;
    }

    if (expandedCount > 0) {
      const poolNorm = pool.map((pw) => normalizeWord(pw.word));
      const expandedKept = greedyMatch(trimTokens, poolNorm);
      const expandedMatchPct = trimTokens.length > 0 ? expandedKept.size / trimTokens.length : 0;
      const expandedPassed = expandedMatchPct >= MATCH_THRESHOLD;

      if (expandedPassed) {
        // Tally which pool positions are removed per utterance
        const uttWordCount = new Map<number, number>();
        const uttRemovedSet = new Map<number, Set<number>>();
        pool.forEach((pw, poolIdx) => {
          uttWordCount.set(pw.utterIdx, (uttWordCount.get(pw.utterIdx) ?? 0) + 1);
          if (!expandedKept.has(poolIdx)) {
            if (!uttRemovedSet.has(pw.utterIdx)) uttRemovedSet.set(pw.utterIdx, new Set());
            uttRemovedSet.get(pw.utterIdx)!.add(pw.wordIdx);
          }
        });

        for (const uttIdx of new Set(pool.map((pw) => pw.utterIdx))) {
          const total = uttWordCount.get(uttIdx) ?? 0;
          const removedSet = uttRemovedSet.get(uttIdx) ?? new Set<number>();
          if (removedSet.size === 0) resolvedRemovals.set(uttIdx, "none");
          else if (removedSet.size >= total) resolvedRemovals.set(uttIdx, "all");
          else resolvedRemovals.set(uttIdx, removedSet);
        }
        continue;
      }
    }

    // All match attempts failed — keep all words of utterance i
    resolvedRemovals.set(i, "none");
  }

  // ── Build EditableWord array using pre-computed removals ───────────────────
  transcript.forEach((seg, utteranceIdx) => {
    const decision = decisionMap.get(utteranceIdx);
    const sourceWords = getSourceWords(seg);
    const removedIndices: Removal = resolvedRemovals.get(utteranceIdx) ?? "none";

    sourceWords.forEach((w, wi) => {
      const removed =
        removedIndices === "all"
          ? true
          : removedIndices === "none"
          ? false
          : (removedIndices as Set<number>).has(wi);

      allWords.push({
        id: `${utteranceIdx}-${wi}`,
        text: w.word,
        removed,
        start: w.start,
        end: w.end,
        utteranceIdx,
        confidence: w.confidence,
        speaker: w.speaker,
        // Propagate fragment warning and rationale to the first word only
        ...(wi === 0 && decision?.fragmentWarning ? { fragmentWarning: true } : {}),
        ...(wi === 0 && decision?.rationale ? { rationale: decision.rationale } : {}),
      });
    });
  });

  return allWords;
}
