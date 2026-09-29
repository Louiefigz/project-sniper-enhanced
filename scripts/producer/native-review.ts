/** Typed native review records. Critics author observations; this command binds hashes, canonical paths and schema.
 * It never calls a model, never supplies a verdict and never grants publication or listening approval. */
import { assertNativeFinalReview } from "../../src/lib/server/native-final-review";
import { canonicalInput } from "../../src/lib/server/native-review-packet";
import { submitNativeFinalReview } from "../../src/lib/server/native-final-review-submission";
import { submitNativeMotionReview } from "../../src/lib/server/native-motion-review-submission";
import { bindNativePrebuildReview, submitNativePrebuildReview } from "../../src/lib/server/native-prebuild-review-submission";

const USAGE = "Usage: native-review.ts submit-prebuild|submit-motion|submit-final <role-packet.json> <observations.json> "
  + "<new-record.json> | bind-prebuild <plan.json> <PREBUILD-REVIEW.json> <new-plan.json> | check-final <FINAL-REVIEW.json>";
const SUBMIT = { "submit-prebuild": submitNativePrebuildReview, "submit-motion": submitNativeMotionReview,
  "submit-final": submitNativeFinalReview } as const;

export async function executeNativeReviewCommand(argv: string[]) {
  const [operation, first, second, third] = argv;
  if (operation === "--help" && argv.length === 1) return { usage: USAGE };
  if (Object.hasOwn(SUBMIT, operation) && argv.length === 4) {
    return SUBMIT[operation as keyof typeof SUBMIT]({ packet: first, observations: second, output: third });
  }
  if (operation === "bind-prebuild" && argv.length === 4) return bindNativePrebuildReview(first, second, third);
  if (operation === "check-final" && argv.length === 2) return assertNativeFinalReview(canonicalInput(first, "Final review record"));
  throw new Error(USAGE);
}

if (require.main === module) executeNativeReviewCommand(process.argv.slice(2))
  .then(value => console.log(JSON.stringify(value, null, 2))).catch((error: unknown) => {
    console.error(JSON.stringify({ ok: false, error: String(error).slice(0, 4096),
      recovery: "Failed submissions publish no record. Fix the named input (re-resolve the role packet if its inputs changed) and rerun." }));
    process.exitCode = 1;
  });
