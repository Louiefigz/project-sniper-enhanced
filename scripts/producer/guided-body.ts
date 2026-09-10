/** Foreground Codex/Producer continuation. No detached controller, implicit human approval or automatic retry. */
import path from "node:path";
import { observeCutPreviewFile } from "../../src/app/api/producer/auto-edit/cut-preview-receipt";
import { parseContinueApprovedOpening } from "../../src/lib/producer/contracts/guided-body-v1";
import { runGuidedBody, BodyRequestConflictError } from "../../src/lib/server/guided-body-service";
import { readGuidedBodyStatus } from "../../src/lib/server/guided-body-status";
import { cleanupGuidedBody, parseBodyCleanupRequest } from "../../src/lib/server/guided-body-cleanup";

const USAGE = "node --import tsx scripts/producer/guided-body.ts status <producer-dir> OR run|cleanup <producer-dir> <request.json>";

/** No-media TEST seams only; command/request data cannot replace production execution or ownership checks. */
export const bodyCommandServices = { run: runGuidedBody, status: readGuidedBodyStatus, cleanup: cleanupGuidedBody };

function boundedPath(value: string): string {
  if (!value || value.length > 4096 || /[\0\r\n]/u.test(value)) throw new Error("Body command path is invalid");
  return path.resolve(value);
}

function request(file: string): unknown {
  const read = observeCutPreviewFile(boundedPath(file), 16_384, true);
  return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(read.bytes));
}

/** Explicit run/cleanup only. Status and same-request replay cannot spawn media, extend deadlines or approve anything. */
export async function executeBodyCommand(argv: string[], services = bodyCommandServices) {
  const [command, directory, file] = argv;
  if (argv.length === 1 && command === "--help") return { usage: USAGE,
    note: "Run from repository root using an exact persisted continue-approved-opening request. Run remains in the foreground and owns the original55-minute body allocation plus bounded safety cleanup. Only a private mechanically qualified candidate is produced; independent creative review, listening and delivery approval remain separate. Unknown/failed attempts are never automatically restarted." };
  const valid = command === "status" && argv.length === 2 || (command === "run" || command === "cleanup") && argv.length === 3;
  if (!valid) throw new Error(USAGE);
  const dir = boundedPath(directory);
  if (command === "status") return services.status(dir);
  const submission = request(file);
  if (command === "cleanup") return services.cleanup({ dir, submission: parseBodyCleanupRequest(submission) });
  return services.run({ dir, submission: parseContinueApprovedOpening(submission) });
}

/** Closed failure protocol lets tests/operators distinguish a real conflict from timeout, import failure or malformed output. */
export function bodyCommandFailure(error: unknown) {
  const code = error instanceof BodyRequestConflictError ? error.code : "BODY_COMMAND_FAILED";
  return { ok: false as const, code, error: String(error).slice(0, 4000) };
}

if (require.main === module) {
  executeBodyCommand(process.argv.slice(2)).then((value) => process.stdout.write(JSON.stringify(value) + "\n"))
    .catch((error: unknown) => {
      process.stderr.write(JSON.stringify(bodyCommandFailure(error)) + "\n");
      process.exitCode = 1;
    });
}
