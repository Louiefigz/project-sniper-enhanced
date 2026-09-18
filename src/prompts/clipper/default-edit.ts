export const DEFAULT_EDIT_REQUEST = `Create a concise, engaging edit that is easy to follow. Remove filler, false starts, repetition, and tangents while preserving the speaker's meaning. Open with the strongest clear moment and end after the main takeaway.`;

/** Build the model instructions around the user's plain-language edit request. */
export function buildEditPrompt(editRequest: string): string {
  return `
<task>
Edit the numbered transcript according to this request:

${editRequest.trim()}
</task>

<hard_rules>
- Work in the transcript's existing order.
- Never add, invent, paraphrase, or rearrange spoken words.
- Give every transcript index exactly one KEEP, REMOVE, or TRIM decision.
- KEEP preserves an utterance exactly.
- REMOVE cuts an utterance completely.
- TRIM may use only exact words from that same utterance, in their original order.
- Remove lines that contain only filler, crosstalk, noise, or an unusable fragment.
- If nearby utterances repeat the same speech because of microphone bleed, keep the clearest copy only.
- Make the kept sequence understandable to a first-time viewer, with no abrupt opening or trailing chatter.
</hard_rules>

<output_format>
Use the submit_edit_decisions tool. Return decisions in index order. For TRIM, include trimmed_text. For KEEP and REMOVE, omit trimmed_text.
</output_format>`;
}
