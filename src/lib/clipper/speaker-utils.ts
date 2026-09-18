import { TranscriptEntry, SpeakerMap } from "@/lib/clipper/types";

interface SpeakerStats {
  id: number;
  totalWords: number;
  utteranceCount: number;
  questionCount: number;
}

/**
 * Auto-assign speaker roles based on conversational heuristics:
 *
 * - The speaker with the highest average words-per-utterance is the
 *   "insights deliverer" → labeled HOST.
 * - All other speakers are labeled GUEST (or GUEST 2, GUEST 3 for 3+).
 *
 * A question-ratio penalty is applied so that a speaker who mostly asks
 * short questions doesn't accidentally outscore on word count alone.
 *
 * Falls back gracefully: if only one speaker is detected, they become HOST.
 * If no speaker metadata exists, returns an empty map (no labels applied).
 */
export function autoDetectSpeakers(transcript: TranscriptEntry[]): SpeakerMap {
  const statsMap = new Map<number, SpeakerStats>();

  for (const entry of transcript) {
    const words = entry.words ?? [];
    if (!words.length) continue;

    // Derive speaker from the majority of words in the utterance
    const speakerCounts = new Map<number, number>();
    for (const w of words) {
      if (w.speaker != null) {
        speakerCounts.set(w.speaker, (speakerCounts.get(w.speaker) ?? 0) + 1);
      }
    }
    if (!speakerCounts.size) continue;

    const dominantSpeaker = [...speakerCounts.entries()].sort((a, b) => b[1] - a[1])[0][0];

    if (!statsMap.has(dominantSpeaker)) {
      statsMap.set(dominantSpeaker, {
        id: dominantSpeaker,
        totalWords: 0,
        utteranceCount: 0,
        questionCount: 0,
      });
    }

    const stat = statsMap.get(dominantSpeaker)!;
    stat.totalWords += words.length;
    stat.utteranceCount += 1;
    if (entry.text.trim().endsWith("?")) stat.questionCount += 1;
  }

  if (!statsMap.size) return {};

  // Score: avg words per utterance, penalised by question ratio
  const scored = [...statsMap.values()].map((s) => {
    const avgWords = s.utteranceCount > 0 ? s.totalWords / s.utteranceCount : 0;
    const questionRatio = s.utteranceCount > 0 ? s.questionCount / s.utteranceCount : 0;
    return { id: s.id, score: avgWords * (1 - questionRatio * 0.6) };
  });

  // Highest score = HOST
  scored.sort((a, b) => b.score - a.score);

  const result: SpeakerMap = {};
  scored.forEach(({ id }, i) => {
    if (i === 0) {
      result[id] = "Host";
    } else if (scored.length === 2) {
      result[id] = "Guest";
    } else {
      result[id] = i === 1 ? "Guest" : `Guest ${i}`;
    }
  });

  return result;
}
