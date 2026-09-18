/** Thin new-only guided cut preparation. No implicit user attestation or UI server. */
import path from "node:path";
import { canonicalProducerDir } from "../../src/app/api/producer/auto-edit/request";
import { observeCutPreviewFile } from "../../src/app/api/producer/auto-edit/cut-preview-receipt";
import { parseGuidedProjectRequest } from "../../src/lib/server/guided-project-bootstrap-contract";
import { bootstrapGuidedProject, authorGuidedProjectCut } from "../../src/lib/server/guided-project-bootstrap";
import { readGuidedProjectBootstrapStatus } from "../../src/lib/server/guided-project-bootstrap-status";
import { MAX_TREATMENT_REQUEST_BYTES, parseTreatmentRequestJson } from "./guided-treatment-json";

const USAGE = "node --import tsx scripts/producer/guided-project.ts bootstrap <request.json> OR author-cut <request.json> OR status <producer-dir>";
export const projectCommandServices = { bootstrap: bootstrapGuidedProject, authorCut: authorGuidedProjectCut, status: readGuidedProjectBootstrapStatus,
  canonicalDir: canonicalProducerDir };

function boundedPath(value: string): string {
  if (!value || value.length > 4096 || /[\0\r\n]/u.test(value)) throw new Error("Bootstrap command path is invalid");
  return path.resolve(value);
}

/** Submitted intent must already match candidate target; no missing-scope/default-treatment repair. */
export async function executeProjectCommand(argv: string[]) {
  const receivedAt = new Date().toISOString();
  const [command, file] = argv;
  if (argv.length === 1 && command === "--help") return { usage: USAGE,
    scope: "new-only-cut-preparation-not-human-acceptance",
    authorCut: "author-cut requires a full validated intent.brief, exact admitted manifest reference, and explicit output {width,height,fps}: longform1920x1080 or short1080x1920, finite numeric fps1..60 (rational-string targets unsupported). This is intended final target metadata, not cadence-conversion or final-canvas qualification; the cut preview preserves its source aspect/rate and downstream support gates remain mandatory. It creates only an unapproved four-field empty seed, then uses the ordinary subscription-backed cut writer and two independent critics before qualified preview PAUSE. Fixed original120-minute preparation budget includes intake/pinning/writer/reviews/preview; no request deadline or model override, no automatic human acceptance, no downstream lane waiver. Repeated UUID reads retained state only.",
    note: "Run from repository root. Supply an existing admitted manifest and unapproved previsual cut candidate by exact absolute path/SHA256 plus actual operator intent. Candidate target mode/scope/lanes/pace/style must already match intent; produced/full keeps treatment=produced even before graphics. Target music is a strict boolean mirror of submitted music intent (omission means false), not an independent opt-in; no accepted-plan retrofit occurs. Request and metadata files are bounded to128KiB. No studied-reference context yet. The detached existing worker freshly verifies sources, validates previsual cuts, requires two independent subscription-backed critics without a writer, and qualifies a private cut preview before PAUSE. Any gate/critic issue stops unchanged. This may invoke configured subscription CLIs and local media; no paid API fallback is authorized. No human watched/listened acceptance is generated. Repeating the same UUID reads retained state only and never relaunches. Status is not fresh source verification. Failed/partial/unknown cleanup requires explicit recovery, not automatic retry. A paused timing-review candidate is not automatically eligible." };
  if (argv.length !== 2 || !["bootstrap", "author-cut", "status"].includes(command)) throw new Error(USAGE);
  const resolved = boundedPath(file);
  if (command === "status") return projectCommandServices.status(projectCommandServices.canonicalDir(resolved));
  const held = observeCutPreviewFile(resolved, MAX_TREATMENT_REQUEST_BYTES, true);
  const request = parseGuidedProjectRequest(parseTreatmentRequestJson(new TextDecoder("utf-8", { fatal: true }).decode(held.bytes)));
  if (command === "author-cut" && request.operation === "author-cut") return projectCommandServices.authorCut(request, receivedAt);
  if (command === "bootstrap" && request.operation === "bootstrap-existing-cut") return projectCommandServices.bootstrap(request);
  throw new Error("Guided project command does not match submitted operation");
}

if (require.main === module) {
  executeProjectCommand(process.argv.slice(2)).then((value) => process.stdout.write(JSON.stringify(value) + "\n"))
    .catch((error: unknown) => {
      process.stderr.write(JSON.stringify({ ok: false, error: error instanceof Error ? error.message.slice(0, 2048) : "Bootstrap failed",
        recovery: "Keep the request UUID and retained project; status only. Error does not prove rollback or stopped descendants." }) + "\n");
      process.exitCode = 1;
    });
}
