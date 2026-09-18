# Reference evidence is not template authority

## What the audit found

The reference path correctly binds a selected video's identity, bytes, chosen
mode, and operator strategy. It does **not** currently contain a measured
template vocabulary.

`style_profile.json` schema v1 exposes aggregate cuts, low-level visual event
rates, transition-animation classes, caption measurements, colors, audio, and
quality flags. `graphics_planner.py` never receives that profile; it proposes
from the global trigger grammar and `MOTION["card_form_map"]`. The reference
gate then compares only aggregate plan rates.

Those rates are not sufficient to infer a card family. In particular:

- a reference `graphic-in` or `panel-in` is a detected component event, while
  a plan graphic is one authored window;
- `transitionClasses` describes animation observed on visual events, not
  necessarily a cut-seam transition;
- the profile does not label comparison, process, evidence, chapter, thesis,
  or any HyperFrames template kind;
- the profile has no per-metric confidence that would make a tight rate band
  safe to enforce.

Therefore, translating `sweep` into a particular Palmier transition or mapping
an OCR box to a named template would be invented authority, not measurement.

## The current safe contract

Keep two learning channels explicit:

1. **Selected reference** — hash-bound evidence for one run. The writer reads
   its bounded profile and drills into the deep study for a specific mechanics
   question. Identity/mode/strategy fail closed. A literal mimic may reject a
   grossly omitted measured lane, but v1 cannot honestly enforce exact forms.
2. **Promoted house doctrine** — reviewed cross-reference findings encoded in
   templates, `producer_config.py`, the Failure Ledger, and deterministic
   tests. These teachings apply even when no single reference is selected.

All promoted study documents must be pinned into the run's immutable doctrine
snapshot. Raw `deep_study.json` must not be dumped into a critic prompt: real
studies reach 11 MB and may contain OCR of embedded instructions. Bind the full
file hash, then expose a bounded mechanics summary with counts and stratified
event samples.

## What schema v2 needs before strict reference-form enforcement

A future study compiler may add a versioned, confidence-bearing grammar with:

- verified graphic **windows**, distinct from low-level component events;
- reviewed information-shape/form labels for those windows;
- cut-seam roles and measured transition families;
- intro/body density bands using comparable authored-window units;
- layout/anchor families and motion/easing envelopes;
- a provenance and confidence receipt for every derived metric.

Only then may `mimic` or `extend` fail on a reference-specific form or seam
vocabulary. Until that evidence exists, global semantic-form and variety gates
are the deterministic wall: they ensure a rich, non-repetitive edit without
pretending the selected study proved a mapping it did not measure.
