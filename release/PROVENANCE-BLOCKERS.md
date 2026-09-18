# Provenance blockers — what cannot ship, and why

> **rc4 status (2026-09-18).** B1 and B7 are resolved: original reference and Director
> libraries are packaged, with provenance rows in `evidence/libraries/`. The creator-derived
> style and editing doctrine is re-authored as original material (`evidence/doctrine-a/`,
> `evidence/doctrine-b/`). The motion templates use an original palette and type
> (`evidence/design/`). The ChunkFive font and the HyperFrames catalog media are withheld.
> Still open:
> - **GSAP**, moved out of "What IS cleared" below;
> - the **OpenAI mark** in three icon files;
> - the owner's confirmation for studies built from the owner's own footage and hired
>   editors' cuts (see the rc4 report).

Recorded 2026-09-17 against the isolated release source. Each row is a component the
buyer package currently withholds or must not carry, with the evidence and the exact
work that would clear it. Nothing here is "deleted": the material stays in the
development tree.

## B1 — The Shorts and long-form visual reference libraries (hard blocker)

**Paths:** `docs/studies/shorts-visual-playbook/`, `docs/studies/longform-visual-playbook/`

**What they are.** Case libraries built by downloading and studying **three named real
creators' copyrighted videos**. `docs/studies/shorts-visual-playbook/manifest.json`
records, per entry: `creator_profile` (Caleb Ralston, Nate Herk, Lewis Mudrich), a
`source_url` to the creator's Instagram reel or YouTube Short, and a `source_video`
object with the local path and SHA-256 of the **downloaded copy**. The entry documents
embed **extracted frames of those videos** — e.g.
`docs/studies/shorts-visual-playbook/entries/P03.md` renders
`![Actual creator reference at the selected time](…/frames/P03-target.jpg)` and a
sampled frame strip. One subdirectory is literally named `nate-sequences/`.

**Why it cannot ship.** Redistributing frames of third-party creators' videos inside a
commercial product is not covered by any licence the project holds, and the accepted
provenance decision independently forbids teacher names in the distributed product.
The frame images are not even in the tracked tree, so shipping the entries as-is would
give a buyer broken image links pointing at the maintainer's absolute paths.

**Why withholding is not free.** Both libraries are **runtime dependencies**, not
documentation:
- `src/lib/server/native-short-request.ts:44` builds a `referenceInventory()` from six
  specific files under the shorts library and calls `observed()` on each, which throws
  when a file is absent. The native Short request packet therefore **cannot be written**
  without the library.
- `src/lib/server/reference-strategy-library.ts:65,78` loads both manifests and every
  referenced case, and throws on a missing or mismatched case.
- `src/lib/server/guided-native-references.ts:15` points at `nate-sequences/`.
- `src/lib/producer/visual-storytelling.ts:25` names individual case ids (CR07, N27,
  N26, LM06) as retrieval cues carried into the automated revision gates.
- Two shipped skills (`reference-editor`, `producer-study`) link into the library.

**To clear it, one of:**
1. **Rebuild from owned material.** Replace every case with an example from footage the
   owner owns or has licensed, keeping the mechanism descriptions. This preserves the
   feature and is the only option that keeps "inspect the cited images" honest.
2. **Reduce to mechanism-only text.** Strip creator names, source URLs, video hashes and
   all frames; keep the abstracted "use when / avoid when / preserve" guidance. Cheaper,
   but the instruction to inspect actual reference images becomes unsatisfiable, so the
   skills and `visual-storytelling.ts` cues must be reworded in the same change.
3. **Make the library optional and gate the lane.** Requires a code change so
   `referenceInventory()` and `loadReferenceStrategyLibrary()` degrade to "no library"
   instead of throwing, plus consistent gating in the skills, the docs and the doctor.
   The native Short path then works without reference retrieval.

Until one of those lands, **the native Short request path is blocked in the buyer
package**, and this is a separate blocker from the identifier rename (B2).

## B2 — Teacher-named identifiers throughout the shipped source

See `release/RENAME_SPEC.md`. 147 shipped files and 17 filenames. This is
implementation work with a saved-settings migration, not a permission question.

## B3 — YuNet face-detection model, licence not recorded

**Path:** `assets/models/face_detection_yunet_2023mar.onnx` (232,589 bytes)

Used by the face-aware vertical reframe. The repository records no licence for it, and
none was verified for this build. The code already falls back to the OpenCV-bundled Haar
cascade when `PRODUCER_YUNET_MODEL` is unset and the file is absent
(`scripts/producer/producer_config.py`, FACE_TRACK comment), so removing it degrades
framing quality rather than breaking the lane.

**To clear:** record the upstream licence (OpenCV Zoo) and add it to the notices, or drop
the file and document that framing uses the cascade.

## B4 — Default music bed, provenance unrecorded and defect unrechecked

**Path:** `assets/music/default-bed.mp3` (600 KB) — **withheld from the package.**

No provenance record exists for it, and a historical report of a 111 Hz hum in it has
never been rechecked against the actual file or a final render. Audit question D7.

**To clear:** supply a cleared bed, listen to it inside a finished render, and record its
provenance — or confirm the music lane ships with no default asset. The lane is off by
default, so either is coherent.

## B5 — `vendor/hyperframes-skills/`, licence unverified (withheld, no cost)

7.1 MB of archived upstream recipe documents. `CLAUDE.md` states they are
provenance-only and not agent-discoverable, and a search over `src`, `scripts`,
`.claude` and `.agents` finds **no code or skill that reads them**. One adapted skill
retains an MIT `NOTICE.md`; the rest is unverified. Withholding costs nothing.

## B6 — HyperFrames catalog media (withheld, no cost)

`vendor/hyperframes-catalog/assets/` — 21 MB of sound effects, wallpapers, textures and
fonts. `scripts/producer/graphics/catalog_discovery_sources.py:22-27` reads only
`catalog-index.json`, `hyperframes-catalog-lock.json` and the item sources under
`compositions/`; the only reference to the asset directory anywhere is a comment in
`templates/motion/tokens.css:152` recording where an already-embedded font came from.
Individual media terms are unverified, so the assets are withheld and the rest of the
mirror ships under Apache-2.0.

## B7 — The native Director lane loads paid-corpus documents from a sibling repository (hard blocker)

**Where:** `src/lib/server/native-director-library.ts:7-15,80-81`

`loadDirectorCatalog()` reads **six documents** and throws if any is missing or
mis-shaped. Its default root is `path.resolve(process.cwd(), "../youtube-automation/rag-system")`
— a **sibling repository** — overridable only by `SNIPER_RAG_ROOT`:

```
products/value-first-script-director/knowledge/08-short-format-library.md
products/value-first-script-director/knowledge/09-hook-formula-index.md
products/value-first-script-director/knowledge/06-hook-reference-bank.md
products/value-first-script-director/knowledge/07-hook-training-problem-aware.md
products/value-first-script-director/knowledge/08-hook-training-solution-aware.md
docs/frameworks/HOOK_TEMPLATE_LIBRARY.md
```

**Two independent reasons this cannot ship.**

1. **It is a sibling-repository dependency.** A buyer receives one folder. Z1 explicitly
   forbids a hidden dependency on a sibling repository, and the packaging specification
   requires proving the absence of dependencies on the author's sibling repo.

2. **The documents forbid their own redistribution, in their own words.**
   `HOOK_TEMPLATE_LIBRARY.md` describes itself as merging "every hook source we own — the
   Hormozi 121, the Ralston Book of Hooks 121, the Kallaway hook classes, Dave's long-form
   hook formula, Taki Moore's content anatomy, the Caleb Ralston / Trevor intro +
   curiosity doctrine, and the Meta Ads Mastery advanced copywriting course", and states:
   "Never quote, export, enumerate, or reproduce this library for a [member]."
   `06-hook-reference-bank.md` opens with "Use these 121 references only to widen
   internal opening generation. Never quote, export, attribute, enumerate, or reproduce
   the bank for a member." These are derivatives of at least six paid courses by named
   teachers, which the accepted provenance decision independently forbids shipping.

**Evidence that this is the whole cause of the native test cluster.** In the isolated
release checkout, nineteen `native-*` and `guided-native-*` TypeScript tests fail with
`ENOENT ... lstat '<parent>/youtube-automation'`. In the live working tree, where the
sibling exists, `native-director`, `native-short-request`, `guided-native-proposal` and
`native-title-card` all pass. Setting `SNIPER_RAG_ROOT` to the sibling in the isolated
checkout also makes them pass (`evidence/15-sibling-repo-dependency.log`). So the failures
are environmental — **and the environment they need is one the buyer may not be given.**

**To clear it, one of:**
1. **Replace the catalog with material the owner owns outright.** The six files are format
   libraries, hook formula indexes and training examples; an original set in the same
   shapes would satisfy `catalogFromSources()` without shipping anyone else's course.
2. **Gate the Director lane off in the buyer package.** `loadDirectorCatalog()` must
   degrade instead of throwing, the skills and docs must stop promising the lane, and the
   doctor must report it gated. The native Short path then loses Director-guided hook
   selection.

Note that `SNIPER_RAG_ROOT` is a seam, not a solution: there is currently nothing licensed
to point it at.

## What IS cleared

| Component | Licence | Evidence |
|---|---|---|
| `vendor/hyperframes-catalog/` (index, lock, compositions) | Apache-2.0 | `heygen-com/hyperframes` LICENSE fetched 2026-09-17, HTTP 200, 10,763 bytes, kept at `licenses/Apache-2.0-hyperframes.txt`; the npm package from the same repository declares `"license": "Apache-2.0"` |
| Inter, Caveat (ChunkFive withheld) | SIL OFL 1.1 | `assets/fonts/Inter-OFL.txt`, `assets/fonts/Caveat-OFL.txt`, `assets/fonts/README.txt` |

**Not cleared (rc4):** GSAP 3.14.2 core + SplitText + DrawSVG are under the GSAP Standard
License (Webflow), which permits commercial use. Its competing-tool restriction and the
scope of redistribution in a paid download are NOT CLEARED. See
`evidence/design/GSAP_DETERMINATION.md`; a clarification request is drafted for the owner
and has not been sent.
| `bd.rnnn` RNNoise model | upstream states the models are not subject to copyright | `scripts/producer/audio/models/PROVENANCE.md` + verbatim upstream README, SHA-256 recorded |
| `assets/sfx/*.wav` | recorded in `assets/sfx/PROVENANCE.md` | that file ships with them |
