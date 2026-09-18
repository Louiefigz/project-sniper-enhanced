/** Explicit TEST author/critic replies; real libraries and source clocks, no creative-quality claim. */
import type { NativeDirectorPlan, DirectorFill } from "@/lib/producer/contracts/native-director-v1";
import { DIRECTOR_CONDITIONS } from "@/lib/producer/contracts/native-director-v1";
import type { DirectorBrainInput } from "../native-director-store";
import type { DirectorInput } from "../native-director-validation";
import type { DirectorCatalog } from "../native-director-library";

export function testDirectorPlan(input: DirectorInput, catalog: Pick<DirectorCatalog, "examples">): NativeDirectorPlan {
  const words = input.occurrences.slice(0, 3), quote = { occurrenceIds: words.map((word) => word[0]), quote: words.map((word) => word[5]).join(" ") };
  const example = catalog.examples.find((row) => row.id === "R013")!;
  const fills = ["Can This Be Clearer?", "What Makes This Clearer?"].map((writtenHook): DirectorFill => ({ writtenHook,
    reason: "TEST only: distinct candidate binding; no actual clarity score.",
    audit: Object.fromEntries(DIRECTOR_CONDITIONS.map((key) => [key, { surface: "written", quote: writtenHook,
      reason: "TEST only: verify literal condition evidence; no real editorial pass.", pass: true }])) as DirectorFill["audit"] }));
  return { schemaVersion: 1, viewer: "TEST viewer", problem: "TEST source question", payoff: quote,
    awareness: { level: "problem_aware", reason: "TEST routed audience context" },
    format: { id: "one_step", reason: "TEST format resolver", alternatives: [{ id: "how_to", reason: "TEST alternative resolver" }] },
    template: { anchor: "question-ever-wonder", referenceId: example.id, reason: "TEST template resolution and slot completeness",
      slots: example.slots.map((name) => ({ name, value: "TEST source-derived slot", ...quote })),
      alternatives: [{ anchor: "question-ever-wonder", referenceId: "R010", reason: "TEST gift template is not supported by an available giveaway" }] },
    spokenOpening: quote, fills, chosenFill: 0, visual: { firstPicture: "TEST retained presenter; actual picture not inspected",
      placement: "TEST proposed chest box, verify face/caption separation in actual pixels",
      contrast: "TEST white on dark backing; contrast measurement pending",
      reading: "TEST phone-size reading review pending", exitFrame: Math.min(30, input.totalFrames), exitReason: "TEST end of opening context" } };
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
