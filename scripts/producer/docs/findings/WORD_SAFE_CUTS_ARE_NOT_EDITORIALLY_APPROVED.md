# Word-safe cuts are not editorially approved

## Finding

A transcript cut can be structurally valid and still be unusable. Timestamp
alignment proves that a cut does not split a word; it does not prove that the
kept speech is coherent, concise, or complete.

The C0679 60-second run exposed the distinction. A single kept range from
11.271s to 60.061s passed the old transcript contract, but the assembled speech
still contained:

- the restart `maybe, maybe`;
- the disposable filler `you know`; and
- the unfinished final clause `because most people.`

The contract had proved legal boundaries and source identity. It had not proved
editorial quality.

## Enforced order

1. Build the transcript-bound cut candidate.
2. Run deterministic boundary, removal-evidence, duplicate-restart, and
   incomplete-ending checks.
3. Give an independent cut critic the exact hash-bound transcript/cut packet.
4. Revise only cut fields when the critic finds a material defect.
5. Repeat the deterministic checks and require two clean reviews of the same
   cut hash.
6. Only then mint controller cut approval and start visual planning.

The visual author cannot repair the spoken spine later. Once graphics are timed
against a cut, changing that cut invalidates every downstream decision.

## What stays human/editorial

Not every disfluency is mechanically removable. Repeated words can be deliberate
emphasis, and fillers can preserve a natural delivery. Deterministic checks must
therefore cover only high-signal cases; the independent critic owns cadence,
meaning, and whether a splice sounds natural.

## When not to use an aggressive cleanup

Do not apply produced-edit cleanup to documentary testimony, intentionally raw
delivery, comedy timing, or a user-requested verbatim cut. Those modes need an
explicit intent flag and their own review policy; silently weakening the
produced-intro contract is not the solution.
