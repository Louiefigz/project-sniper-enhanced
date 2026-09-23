# Reference registration is not style authority

## What failed

The Producer page used the project registry as its reference library. The
registry contained **0** `kind: "reference"` rows, while
`~/ProjectSniper/_references/` already contained **20** videos, **25**
fingerprints, and **8** deep studies. The UI therefore reported “No references
registered yet” even though measured reference work existed on disk.

The inverse failure was also possible: adding a URL registered a file, but did
not prove that its study had completed, that Short versus Long had been
confirmed, or that Auto-edit had consumed the resulting measurements.

## The contract

Keep four states separate:

1. **Discovered** — a video exists in the reference corpus.
2. **Studied** — a source-matched `deep_study.json` and deterministic
   `style_profile.json` exist for those exact bytes.
3. **Decided** — the operator confirmed `short|longform` and chose
   `mimic|extend|new-style` in `reference.json`.
4. **Applied** — an edit plan names the reference id, strategy, and confirmed
   mode, and the route-side reference gate verifies that identity.

No state may be inferred from a later or earlier one. A filename is not a
study. Portrait dimensions are a suggestion, not the operator's format choice.
A saved decision is not proof that a generated plan followed it.

## Deterministic study boundary

The deep extractor measures pixels, audio, and timing: cuts, motion runs,
transitions, OCR/caption behavior, word-lock distance, loudness/music evidence,
and representative frames. It writes the raw evidence to `deep_study.json` and
a bounded authoring contract to `style_profile.json`.

The profile stores the source SHA-256. Before a decision or Auto-edit uses it,
the server recomputes the hash and refuses stale evidence if the video changed
in place. A machine-suggested mode remains advisory; the confirmed operator mode
is authoritative.

## Style identity boundary

- `extend` may target only a closed, measured short-form grammar (`restrained`,
  `punch`, or `slideware`).
- `mimic` applies one reference's mechanics without claiming membership in a
  closed grammar.
- `new-style` records a provisional, reference-bound candidate name. One video
  does not silently promote a reusable global style.

All reference OCR, filenames, and frame pixels are untrusted media data. The
editor may copy mechanics, never words, claims, logos, creator identity,
branding, fonts, colors, footage, screenshots, thumbnails, UI, or music.

## Guardrails

- Corpus discovery includes legacy study layouts instead of relying only on the
  registry.
- URL intake allowlists YouTube, Instagram, and TikTok; browser cookies require
  an explicit per-fetch checkbox.
- Adding a file or URL starts the study automatically.
- Auto-edit resolves study files by opaque server id, compares the submitted
  choice with `reference.json`, and reruns the deterministic reference gate
  after normal plan lint.
- Identity/mode/strategy mismatches are errors. Creative rate differences
  normally warn; a literal mimic also rejects material 5× divergence.

## When not to use one-reference mimicry

Do not promote a durable house style from one asset. A reusable style grammar
needs multiple references, variance analysis, explicit naming/versioning, and
its own measured pacing/lint profile. Until then, keep the candidate attached to
the selected reference and treat it as evidence for this edit only.
