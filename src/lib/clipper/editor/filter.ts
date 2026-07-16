import { EditableWord } from "@/lib/clipper/types";

const MIN_CLIP_DURATION = 0.5; // seconds — drop sub-second word fragments from over-aggressive TRIMs

export function filterShortClips(words: EditableWord[]): EditableWord[] {
  const result = [...words];
  let i = 0;
  while (i < result.length) {
    if (result[i].removed) { i++; continue; }
    let j = i;
    while (j < result.length && !result[j].removed) j++;
    const duration = result[j - 1].end - result[i].start;
    if (duration < MIN_CLIP_DURATION) {
      for (let k = i; k < j; k++) result[k] = { ...result[k], removed: true };
    }
    i = j;
  }
  return result;
}
