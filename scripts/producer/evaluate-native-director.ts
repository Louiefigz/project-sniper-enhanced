/** Real-source Director exercise; retains actual model failures and elapsed time. */
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { performance } from "node:perf_hooks";
import { stageNativeDirector } from "../../src/lib/server/native-director-store";
import { canonicalJsonSha256, fileSha256 } from "../../src/lib/server/auto-edit-hash";
import type { ProposalEvidence } from "../../src/lib/server/guided-proposal-evidence";

const SOURCES = "artifacts/shorts-strategy-validation-2026-09-10";
const INTENTS: Record<string, string> = {
  "03-follow-up": "Make a self-contained Short for small business owners about why useful follow-up earns trust. Preserve the supplied spoken words. Choose an evidence-supported screen hook from the Director library. Keep the presenter prominent; explain the source-specific reason for any added visual. No invented results or customer messages.",
  "01-offer": "Make a self-contained Short for small business owners about replacing a vague offer with a specific outcome and timeframe. This is the speaker's dog-food business example, not veterinary advice or proof of improved sales. Preserve the supplied speech. Choose a library-grounded screen hook and a readable comparison. Do not invent results.",
  "02-member-target": "Make a self-contained Short for early membership-business owners about the arithmetic of a $1,000 monthly recurring revenue goal: 26 members at $39. This is a goal and arithmetic illustration, not an achieved result or an acquisition strategy. Preserve the supplied speech. Choose a source-supported library hook; avoid promising how to recruit members.",
};

function sourceInput(id: string): ProposalEvidence {
  const filename = path.resolve(SOURCES, id, "evidence.json");
  const source = JSON.parse(readFileSync(filename, "utf8"));
  if (fileSha256(source.source.path) !== source.source.sha256
      || fileSha256(source.transcript.path) !== source.transcript.sha256) throw new Error("Evaluation source changed");
  return { ...source, schemaVersion: 9,
    target: { mode: "short", width: 1080, height: 1920 },
    timelineMapHash: canonicalJsonSha256({ cuts: source.cuts, segments: source.segments,
      sourceSha256: source.source.sha256, transcriptSha256: source.transcript.sha256 }),
  } as ProposalEvidence;
}

async function main(): Promise<void> {
  const [id, destination] = process.argv.slice(2);
  if (!INTENTS[id] || !destination) throw new Error("Usage: evaluate-native-director.ts <case-id> <new-output-directory>");
  const directory = path.resolve(destination);
  mkdirSync(directory, { recursive: false });
  const started = performance.now(), deadline = started + 600_000;
  const receipt: Record<string, unknown> = { schemaVersion: 1, caseId: id,
    scope: "real-source-real-provider-director-evaluation-not-render-or-delivery",
    startedAt: new Date().toISOString(), modelResponsesSimulated: false, status: "failed" };
  const remainingMs = () => {
    const remaining = Math.floor(deadline - performance.now());
    if (remaining < 1) throw new Error("Director evaluation exceeded its original ten-minute allowance");
    return remaining;
  };
  try {
    const evidence = sourceInput(id);
    const record = await stageNativeDirector({ directory, rawIntent: INTENTS[id], evidence, remainingMs });
    Object.assign(receipt, { status: "director-reviewed", planHash: record.planHash,
      format: record.plan.format.id, template: record.plan.template.anchor,
      hook: record.plan.fills[record.plan.chosenFill].writtenHook });
  } catch (error) {
    receipt.error = String(error); process.exitCode = 1;
  } finally {
    Object.assign(receipt, { elapsedMs: Math.round(performance.now() - started), finishedAt: new Date().toISOString() });
    writeFileSync(path.join(directory, "evaluation.json"), JSON.stringify(receipt, null, 2) + "\n", { flag: "wx" });
    console.log(JSON.stringify(receipt));
  }
}

void main().catch((error: unknown) => { console.error(String(error)); process.exitCode = 1; });
