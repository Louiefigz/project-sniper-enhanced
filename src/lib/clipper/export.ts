import { EditableWord, TranscriptEntry } from "@/lib/clipper/types";

function fmt(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = (seconds % 60).toFixed(2).padStart(5, "0");
  return `${m}:${s}`;
}

/**
 * Merge consecutive kept words into contiguous clips.
 *
 * A new clip starts wherever one or more removed words create a gap.
 * Words are processed in their original order, producing a list of
 * { start, end, text } clips.
 *
 * Final coalesce pass: clips are sorted by source start and any clips whose
 * SOURCE ranges overlap are merged into one. This is what makes the cut robust
 * to lav-mic bleed — the same moment is transcribed twice (once per mic), and if
 * the editor keeps both copies they'd otherwise be laid back-to-back and play
 * TWICE. In this assembly tool an intentional cut never re-uses the same source
 * moment, so overlapping ranges are always duplicates and merging is safe.
 */
export function computeFinalClips(
  words: EditableWord[]
): { start: number; end: number; text: string }[] {
  const clips: { start: number; end: number; text: string }[] = [];
  let current: { start: number; end: number; words: string[] } | null = null;

  for (const word of words) {
    if (word.removed) {
      if (current) {
        clips.push({ start: current.start, end: current.end, text: current.words.join(" ") });
        current = null;
      }
    } else {
      if (!current) {
        current = { start: word.start, end: word.end, words: [word.text] };
      } else {
        current.end = word.end;
        current.words.push(word.text);
      }
    }
  }
  if (current) {
    clips.push({ start: current.start, end: current.end, text: current.words.join(" ") });
  }

  // Coalesce overlapping source ranges (bleed duplicates) so no moment plays twice.
  clips.sort((a, b) => a.start - b.start || a.end - b.end);
  const merged: { start: number; end: number; text: string }[] = [];
  for (const c of clips) {
    const last = merged[merged.length - 1];
    if (last && c.start <= last.end) {
      last.end = Math.max(last.end, c.end);
      if (c.text && c.text !== last.text) last.text = `${last.text} ${c.text}`.trim();
    } else {
      merged.push({ ...c });
    }
  }

  return merged;
}


/**
 * Generate a human-readable debug report showing every kept vs cut block.
 */
export function generateDebugTXT(
  words: EditableWord[],
  fileName: string,
  totalDuration: number
): string {
  const clips = computeFinalClips(words);
  const exportedDuration = clips.reduce((a, c) => a + (c.end - c.start), 0);
  const cutDuration = totalDuration - exportedDuration;
  const pctKept = totalDuration > 0 ? Math.round((exportedDuration / totalDuration) * 100) : 0;
  const keptWords = words.filter((w) => !w.removed).length;
  const removedWords = words.filter((w) => w.removed).length;

  const lines: string[] = [];
  const hr = "─".repeat(60);

  lines.push("CLIPPER EXPORT DEBUG REPORT (word-level)");
  lines.push("═".repeat(60));
  lines.push(`File:              ${fileName}`);
  lines.push(`Original duration: ${fmt(totalDuration)}`);
  lines.push(`Exported duration: ${fmt(exportedDuration)}  (${pctKept}% kept)`);
  lines.push(`Cut:               ${fmt(cutDuration)}  (${100 - pctKept}% removed)`);
  lines.push(`Total words:       ${words.length}  (kept: ${keptWords}, removed: ${removedWords})`);
  lines.push(`Output clips:      ${clips.length}  (each clip = contiguous run of kept words)`);
  lines.push("");
  lines.push("═".repeat(60));
  lines.push("TIMELINE  (K=kept, X=cut)");
  lines.push(hr);

  // Group consecutive same-state words into blocks for readability
  type Block = { kind: "keep" | "cut"; words: EditableWord[] };
  const blocks: Block[] = [];
  let cur: Block | null = null;

  for (const word of words) {
    const kind: "keep" | "cut" = word.removed ? "cut" : "keep";
    if (!cur || cur.kind !== kind) {
      if (cur) blocks.push(cur);
      cur = { kind, words: [word] };
    } else {
      cur.words.push(word);
    }
  }
  if (cur) blocks.push(cur);

  let clipNum = 0;
  for (const block of blocks) {
    const start = block.words[0].start;
    const end = block.words[block.words.length - 1].end;
    const dur = (end - start).toFixed(2);
    const text = block.words.map((w) => w.text).join(" ");

    // Collect LLM rationale from the first word of each utterance in this block
    const seenUttIdx = new Set<number>();
    const blockRationales: string[] = [];
    for (const w of block.words) {
      if (w.rationale && !seenUttIdx.has(w.utteranceIdx)) {
        seenUttIdx.add(w.utteranceIdx);
        blockRationales.push(w.rationale);
      }
      seenUttIdx.add(w.utteranceIdx);
    }
    const rationaleStr = blockRationales.length > 0 ? blockRationales.join(" | ") : "";

    if (block.kind === "keep") {
      clipNum++;
      lines.push(`[K #${clipNum.toString().padStart(3, "0")}]  ${fmt(start)} → ${fmt(end)}  (${dur}s)`);
      lines.push(`         "${text}"`);
    } else {
      lines.push(`[X CUT]  ${fmt(start)} → ${fmt(end)}  (${dur}s)`);
      lines.push(`         "${text}"`);
    }
    lines.push(`         Rationale: ${rationaleStr}`);
    lines.push(`         Feedback: `);
    lines.push("");
  }

  lines.push(hr);
  lines.push(`END — ${clipNum} clips · ${fmt(exportedDuration)} kept of ${fmt(totalDuration)} total`);

  return lines.join("\n");
}

// ─── Speaker-turn helpers ────────────────────────────────────────────────────

interface SpeakerTurn {
  turnIdx: number;
  speaker: string;
  originalText: string; // full merged text of all utterances in this turn
  keptText: string;     // joined kept word tokens
  action: "keep" | "remove" | "trim";
}

/**
 * Merge consecutive same-speaker Deepgram utterances into speaker turns,
 * then compute a KEEP/REMOVE/TRIM action for each turn based on the
 * actual word-level state (post-editor).
 *
 * This mirrors the structure of the DEFAULT_EDIT_PROMPT examples, where
 * each [index] is a complete speaker turn rather than a Deepgram micro-utterance.
 */
function buildSpeakerTurns(
  transcript: TranscriptEntry[],
  words: EditableWord[]
): SpeakerTurn[] {
  // Map utteranceIdx → { kept[], total }
  const uttKept = new Map<number, string[]>();
  const uttTotal = new Map<number, number>();
  for (const word of words) {
    if (!uttTotal.has(word.utteranceIdx)) {
      uttTotal.set(word.utteranceIdx, 0);
      uttKept.set(word.utteranceIdx, []);
    }
    uttTotal.set(word.utteranceIdx, (uttTotal.get(word.utteranceIdx) ?? 0) + 1);
    if (!word.removed) uttKept.get(word.utteranceIdx)!.push(word.text);
  }

  // Speaker label per utterance
  const uttSpeaker = transcript.map((entry) => {
    const spk = entry.words?.[0]?.speaker ?? null;
    return spk != null ? `Speaker ${spk}` : "Speaker";
  });

  // Merge consecutive same-speaker utterances
  type Acc = {
    speaker: string;
    originalTexts: string[];
    keptWords: string[];
    totalWords: number;
  };

  const merged: Acc[] = [];
  for (let i = 0; i < transcript.length; i++) {
    const spk = uttSpeaker[i];
    const keptWds = uttKept.get(i) ?? [];
    const total = uttTotal.get(i) ?? 0;
    const last = merged[merged.length - 1];
    if (last && last.speaker === spk) {
      last.originalTexts.push(transcript[i].text);
      last.keptWords.push(...keptWds);
      last.totalWords += total;
    } else {
      merged.push({
        speaker: spk,
        originalTexts: [transcript[i].text],
        keptWords: [...keptWds],
        totalWords: total,
      });
    }
  }

  return merged.map((turn, idx) => {
    const action: "keep" | "remove" | "trim" =
      turn.keptWords.length === 0
        ? "remove"
        : turn.keptWords.length === turn.totalWords
        ? "keep"
        : "trim";
    return {
      turnIdx: idx,
      speaker: turn.speaker,
      originalText: turn.originalTexts.join(" "),
      keptText: turn.keptWords.join(" "),
      action,
    };
  });
}



// ─── Public generators ────────────────────────────────────────────────────────

/**
 * Generate a numbered raw transcript in the prompt-example format:
 *   [0] Speaker 0: Hello there.
 *   [1] Speaker 1: Right.
 * Consecutive same-speaker Deepgram utterances are merged into one turn.
 */
export function generateExampleTranscript(
  transcript: TranscriptEntry[],
  words: EditableWord[]
): string {
  return buildSpeakerTurns(transcript, words)
    .map((t) => `[${t.turnIdx}] ${t.speaker}: ${t.originalText}`)
    .join("\n");
}

/**
 * Generate the decisions block in the prompt-example format, derived from
 * speaker turns (so they match the Final Transcript Preview):
 *   [0] KEEP
 *   [1] REMOVE
 *   [2] TRIM: trimmed text here
 */
export function generateExampleDecisions(
  words: EditableWord[],
  transcript: TranscriptEntry[]
): string {
  return buildSpeakerTurns(transcript, words)
    .map((t) => {
      if (t.action === "keep") return `[${t.turnIdx}] KEEP`;
      if (t.action === "remove") return `[${t.turnIdx}] REMOVE`;
      return `[${t.turnIdx}] TRIM: ${t.keptText}`;
    })
    .join("\n");
}


