// Word-level timestamp from Deepgram
export interface WordTiming {
  word: string;
  start: number;
  end: number;
  confidence?: number;
}

// Transcript entry (utterance from Deepgram)
export interface TranscriptEntry {
  start: number;
  end: number;
  text: string;
  words?: WordTiming[];
}

// Segment group identified by Claude
export interface SegmentGroup {
  id: number;
  title: string;
  startLine: number;
  endLine: number;
  start: number;
  end: number;
  summary: string;
}
