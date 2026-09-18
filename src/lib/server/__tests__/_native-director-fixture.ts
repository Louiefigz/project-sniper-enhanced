/** Explicit TEST author/critic replies; real libraries and source clocks, no creative-quality claim. */
import { DIRECTOR_CRITERIA, type DirectorFill, type NativeDirectorPlanV1, type NativeDirectorPlanV2 } from "@/lib/producer/contracts/native-director-v2";
import { LEGACY_V1_AUDIT_KEYS } from "@/lib/producer/contracts/native-director-v1";
import type { DirectorBrainInput } from "../native-director-store";
import type { DirectorInput } from "../native-director-validation";
import type { DirectorCatalog } from "../native-director-library";

export function testDirectorPlan(input: DirectorInput, catalog: Pick<DirectorCatalog, "examples">): NativeDirectorPlanV2 {
  const words = input.occurrences.slice(0, 3), quote = { occurrenceIds: words.map((word) => word[0]), quote: words.map((word) => word[5]).join(" ") };
  const example = catalog.examples.find((row) => row.id === "R508")!;
  const fills = ["Can This Be Clearer?", "What Makes This Clearer?"].map((writtenHook): DirectorFill => ({ writtenHook,
    reason: "TEST only: distinct candidate binding; no actual criteria judgment.",
    audit: Object.fromEntries(DIRECTOR_CRITERIA.map((key) => [key, { surface: "written", quote: writtenHook,
      reason: "TEST only: verify literal criterion evidence; no real editorial pass.", pass: true }])) as DirectorFill["audit"] }));
  return { schemaVersion: 2, viewer: "TEST viewer", problem: "TEST source question", payoff: quote,
    awareness: { level: "problem_aware", reason: "TEST routed audience context" },
    format: { id: "ordered_steps", reason: "TEST format resolver", alternatives: [{ id: "one_change", reason: "TEST alternative resolver" }] },
    template: { anchor: "steps-toward-goal", referenceId: example.id, reason: "TEST template resolution and slot completeness",
      slots: example.slots.map((name) => ({ name, value: "TEST source-derived slot", ...quote })),
      alternatives: [{ anchor: "steps-checks-before", referenceId: "R510", reason: "TEST checklist template has no counted checks in the source" }] },
    spokenOpening: quote, fills, chosenFill: 0, visual: { firstPicture: "TEST retained presenter; actual picture not inspected",
      placement: "TEST proposed chest box, verify face/caption separation in actual pixels",
      contrast: "TEST dark ink on light backing; contrast measurement pending",
      reading: "TEST phone-size reading review pending", exitFrame: Math.min(30, input.totalFrames), exitReason: "TEST end of opening context" } };
}

/** The same TEST decision in the retained pre-2026-09-18 v1 shape (legacy audit keys and awareness level). */
export function testLegacyDirectorPlan(input: DirectorInput, catalog: Pick<DirectorCatalog, "examples">): NativeDirectorPlanV1 {
  const plan = testDirectorPlan(input, catalog);
  const fills = plan.fills.map((fill) => ({ ...fill, audit: Object.fromEntries(LEGACY_V1_AUDIT_KEYS.map((key) => [key,
    { ...fill.audit.supportedClaim }])) as NativeDirectorPlanV1["fills"][number]["audit"] }));
  return { ...plan, schemaVersion: 1, awareness: { level: "product_aware", reason: "TEST retained v1 level" }, fills };
}

export async function nativeDirectorTestBrain(request: DirectorBrainInput) {
  const packet = JSON.parse(request.prompt.split("DIRECTOR_INPUT_JSON\n")[1]);
  if (request.phase === "critic") return { output: { schemaVersion: 1, planHash: packet.review.planHash,
    verdict: "pass", findings: ["TEST independent invocation and binding; this is not a creative pass."] } };
  return { output: testDirectorPlan(packet.input, packet.library) };
}

export function directorSourceFixture(): DirectorInput {
  return { rawIntent: "Explain this real source.", frameRate: "25/1", totalFrames: 100,
    timelineMapHash: "a".repeat(64), target: { width: 1080, height: 1920 },
    occurrences: [[0, 0, 0, 0, 10, "One", 0], [1, 0, 1, 10, 20, "clear", 0], [2, 0, 2, 20, 30, "move.", 0]] };
}
