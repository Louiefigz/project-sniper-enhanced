import assert from "node:assert/strict";
import {
  INTENT_PRESETS,
  presetToIntent,
  type ProjectIntent,
  type ReferenceIntent,
} from "../intent-presets";
import {
  applyReferenceChange,
  intentForReference,
} from "../../../components/producer/reference-intent";

const preset = (id: string) => INTENT_PRESETS.find((item) => item.id === id)!;
const mimic: ReferenceIntent = {
  id: "ref-mimic",
  title: "Mimic reference",
  mode: "short",
  strategy: "mimic",
};

const selected = intentForReference(mimic);
assert.equal(selected.preset, "produced-short");
assert.equal(selected.reference?.id, mimic.id);
assert.equal(selected.music, false);

const musicOn = applyReferenceChange({ ...selected, music: true }, mimic);
assert.equal(musicOn.cleared, false, "music is operator-owned and does not contradict mechanics");
assert.equal(musicOn.intent.reference?.id, mimic.id);

for (const id of ["light-short", "trim-only"]) {
  const reduced = presetToIntent(preset(id), "short");
  const result = applyReferenceChange(reduced, mimic);
  assert.equal(result.cleared, true, `${id} cannot satisfy a literal mimic mechanics gate`);
  assert.equal(result.intent.reference, undefined);
}

for (const lane of ["motion", "graphics", "transitions", "captions", "credibility"] as const) {
  const reduced: ProjectIntent = {
    ...selected,
    preset: "custom",
    lanes: { ...selected.lanes, [lane]: "off" },
  };
  const result = applyReferenceChange(reduced, mimic);
  assert.equal(result.cleared, true, `disabling ${lane} clears a literal mimic request`);
  assert.equal(result.intent.reference, undefined);
}

const noBroll: ProjectIntent = {
  ...selected,
  preset: "custom",
  lanes: { ...selected.lanes, broll: "off" },
};
assert.equal(
  applyReferenceChange(noBroll, mimic).cleared,
  false,
  "an asset-dependent b-roll waiver keeps the mimic request with reduced fidelity",
);

const operatorGraphics: ProjectIntent = {
  ...selected,
  preset: "custom",
  lanes: { graphics: "operator" },
};
assert.equal(
  applyReferenceChange(operatorGraphics, mimic).cleared,
  true,
  "operator-owned graphics are absent from auto-edit and cannot pass the mimic gate",
);

const longform = presetToIntent(preset("longform-produced"), "longform");
assert.equal(applyReferenceChange(longform, mimic).cleared, true, "mode changes remain incompatible");

console.log("reference-selection-flow.test.ts: all assertions passed");
