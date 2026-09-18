# Director library (packaged, original)

The Director reads these six files to choose a Short's format and opening hook. They
ship inside Project Sniper and are the only library the Director loads by default.

**Provenance.** Written for Project Sniper on 2026-09-17 from the Director's own
functional contract (`src/lib/server/native-director-library.ts`) and general editing
practice. They are not copied, adapted or paraphrased from any course, book or paid
library, and they name no creator. Earlier development builds loaded a separate internal
library from a sibling repository; that library is not part of this product and is never
read by it.

**What each file is for**

| File | Parsed as | Used for |
|---|---|---|
| `formats.md` | `## <id> — <title>` sections | the Short's overall shape |
| `hook-anchors.md` | `### N. CATEGORY — …` then `` | `anchor` | template | notes | `` rows | the named opening move; quoted templates can be slot-filled literally |
| `hook-formulas.md` | `### R001 · name` with `- formula:` / `- disqualify-if:` | slot structure for each reference example |
| `hook-references.md` | `- **R001 · text**` | worked example openings |
| `hook-training-problem-aware.md` | `### T001` sections | worked input/output pairs for viewers who know the problem |
| `hook-training-solution-aware.md` | `### T009` sections | the same for viewers comparing solutions |

**Rules the loader enforces.** Every formula id must have a reference or training entry;
ids are unique; the byte hash of each file is recorded in every Director decision, so
editing a file invalidates earlier decisions rather than silently changing them.

**Using it.** References and training pairs widen the Director's options. A hook must be
built from the speaker's own retained words; the validator rejects a written hook that
copies five or more consecutive words from an example.

To point the Director at a different library with the same six files, set
`SNIPER_DIRECTOR_LIBRARY` to its absolute path.
