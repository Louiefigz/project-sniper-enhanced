import assert from "node:assert/strict";
import { parseAutoEditIntent } from "../../../app/api/producer/auto-edit/stream";
import { targetStep } from "../../../app/api/producer/auto-edit/authoring-prompt";
import { buildAutoEditRequest } from "../intent-flow";
import { validateIntent, type ProjectIntent } from "../intent-presets";

const baseIntent = {
  mode: "short",
  scope: "light",
  lanes: {},
} as const;

{
  const intent = validateIntent({ ...baseIntent, brief: "  Keep the opening direct.  " });
  assert.equal(intent.brief, "Keep the opening direct.");
}

for (const brief of ["", "   "]) {
  assert.throws(
    () => validateIntent({ ...baseIntent, brief }),
    /intent\.brief must not be empty/,
  );
}
assert.throws(
  () => validateIntent({ ...baseIntent, brief: "x".repeat(1201) }),
  /intent\.brief must be 1–1200 characters/,
);
assert.throws(
  () => validateIntent({ ...baseIntent, brief: 42 }),
  /intent\.brief must be a string/,
);

{
  const intent: ProjectIntent = {
    ...baseIntent,
    brief: "Use the strongest proof point as the hook.",
  };
  assert.deepEqual(buildAutoEditRequest("/tmp/job", intent), {
    dir: "/tmp/job",
    scope: "light",
    mode: "short",
    lanes: {},
    brief: "Use the strongest proof point as the hook.",
  });
}

{
  const parsed = parseAutoEditIntent({ brief: "  Make the final CTA feel calm.  " });
  assert.equal(parsed?.brief, "Make the final CTA feel calm.");
  assert.throws(() => parseAutoEditIntent({ brief: "" }), /brief must be 1–1200 characters/);
  assert.throws(
    () => parseAutoEditIntent({ brief: "x".repeat(1201) }),
    /brief must be 1–1200 characters/,
  );
  assert.throws(() => parseAutoEditIntent({ brief: false }), /brief must be a string/);
}

{
  const intent = validateIntent({
    mode: "longform", scope: "produced", lanes: {}, excerpt: true,
  });
  assert.equal(intent.excerpt, true);
  assert.equal(buildAutoEditRequest("/tmp/intro", intent).excerpt, true);
  assert.equal(parseAutoEditIntent({ mode: "longform", excerpt: true })?.excerpt, true);
  assert.match(targetStep({
    dir: "/tmp/producer", scope: "produced", intent,
    planPath: "/tmp/producer/edit_plan.json",
    manifestPath: "/tmp/source/asset_manifest.json",
    transcriptsDir: "/tmp/source",
  }), /"excerpt": true/);
  assert.throws(
    () => validateIntent({ ...baseIntent, excerpt: true }),
    /valid only for longform/,
  );
  assert.throws(
    () => parseAutoEditIntent({ mode: "short", excerpt: true }),
    /valid only for longform/,
  );
}

console.log("brief-contract.test.ts: all assertions passed");
