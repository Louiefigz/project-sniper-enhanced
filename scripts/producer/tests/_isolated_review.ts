/** TEST harness: the real `native-review.ts` and `native-short.ts` commands, with the engine given check
 * (`context.py --given-check` and `--review-submitted`) run through `_isolated_context.py` in the calling test's private authority and
 * work-lease roots instead of the user's. Test-only; nothing in the product imports it.
 *
 *   node --import tsx _isolated_review.ts <python> <budget-root> <lease-root> review|short <command arguments...> */
import path from "node:path";
import { givenCheck, givenCheckArguments, givenCheckReport, submittedArguments } from "../../../src/lib/server/native-review-given-check";
import { executeNativeReviewCommand } from "../native-review";
import { executeNativeShortCommand } from "../native-short";

const [python, budgets, lease, family, ...argv] = process.argv.slice(2);
const HARNESS = path.join(path.dirname(path.resolve(process.argv[1])), "_isolated_context.py");
const isolated = (args: string[]) => givenCheckReport(python, ["-B", HARNESS, budgets, lease, ...args]);
givenCheck.run = (packetPath, record) => isolated(givenCheckArguments(packetPath, record));
givenCheck.record = (packetPath, recordSha256, elapsed) => isolated(submittedArguments(packetPath, recordSha256, elapsed));

const command = family === "review" ? executeNativeReviewCommand(argv)
  : family === "short" ? executeNativeShortCommand(argv) : Promise.reject(new Error("TEST harness family is review or short"));
command.then(value => console.log(JSON.stringify(value, null, 2))).catch((error: unknown) => {
  console.error(JSON.stringify({ ok: false, error: String(error).slice(0, 4096) }));
  process.exitCode = 1;
});
