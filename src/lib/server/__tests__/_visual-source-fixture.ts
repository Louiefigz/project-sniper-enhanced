/** Synthetic source-policy evidence, never production design approval. */
import { writeFileSync } from "node:fs";
import path from "node:path";
import { canonicalJsonSha256, fileSha256 } from "../auto-edit-hash";
import { nativeVisualSourceSubject, nativeVisualSourceTargets } from "../visual-source-admission";
import type { NativeShortProjectInput } from "../native-short-project";
import { VISUAL_SOURCE_POLICY } from "@/lib/producer/visual-source-policy";

export function refreshVisualSourceFixture(input: NativeShortProjectInput): void {
  const request = path.join(path.dirname(input.assets[0].path), "TEST-visual-request.json");
  writeFileSync(request, JSON.stringify({ scope: "TEST synthetic request; no actual design approval", selectedReferences: [] }));
  const files = new Set((input.catalogFiles ?? []).map(row => row.file));
  const targets = nativeVisualSourceTargets(input).filter(target => !files.has(target));
  input.visualSources = { schemaVersion: 1, policyVersion: VISUAL_SOURCE_POLICY.policyVersion,
    subjectSha256: canonicalJsonSha256(nativeVisualSourceSubject(input)),
    request: input.requestPacket ?? { path: request, sha256: fileSha256(request)! },
    decisions: targets.length ? [{ route: "custom", targets,
      reason: "TEST isolated synthetic contract geometry for admission tests",
      gapType: "missing-capability", query: "TEST contract geometry for synthetic native fixture",
      gap: "TEST count-up does not implement the synthetic fixture admission contract",
      scope: "TEST fixture geometry only; no real design review or source evaluation",
      inspected: [{ id: "count-up", sourceSha256: VISUAL_SOURCE_POLICY.integrated["count-up"].upstreamSha256,
        limitation: "TEST numeric counter is not this synthetic admission fixture" }] }] : [] };
  input.visualSources.decisions.push(...(input.catalogFiles ?? []).map(row => ({ route: "catalog", targets: [row.file],
    reason: "TEST mounted upstream source identity and adapted file binding",
    catalog: [{ id: row.catalogId, sourceSha256: row.sourceSha256 }],
    configuration: "TEST stage the inspected source as a native subcomposition" })));
}
