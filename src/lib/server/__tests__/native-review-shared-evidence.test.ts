/** Shared-evidence schema version 2 readers (P2-07, X53): typed speaker facts and caption phrases from a sealed
 * record, the read-only version 1 mapping, and the unchanged submission re-check for either version.
 * TEST records only; nothing here was heard, watched or attributed, and the engine check is a TEST double. The Python
 * vocabulary is read as text (no child process) to pin the TypeScript mirror to the one definition (X53). */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { SCRIPTS_DIR } from "@/app/api/_lib/spawn-python";
import {
  evidenceCheck, recheckSharedEvidence, sharedCaptionPhrases, sharedSpeakerFacts, SPEAKER_BASES, SPEAKER_CERTAINTIES,
} from "../native-review-shared-evidence";

const KIND = "sniper-shared-source-evidence";
const SHA = "a".repeat(64);
const REFERENCE = { path: "/TEST/inspection/result.json", sha256: SHA, owner: "/TEST/inspection/inspection.render.json",
  ownerSha256: "b".repeat(64) };

/** One TEST interval on raw-1; version 2 rows add certainty, basis and evidence through `extra`. */
function interval(speaker: string | null, extra: object = {}) {
  return { source: "raw-1", startSeconds: 0, endSeconds: 5, speaker, visible: ["S1", "S2"], note: null, ...extra };
}

/** A TEST version 2 record: S1 with a face region, S2 without, one probable and one unresolved interval. */
function v2Record(extra: Record<string, unknown> = {}) {
  const person = (id: string) => ({ id, description: "TEST", visibility: "TEST", evidence: [] });
  const record = { schemaVersion: 2, kind: KIND,
    speakers: { method: "TEST", listening: false, limits: ["TEST"],
      people: [{ ...person("S1"), faceRegion: { source: "raw-1", xRange: [0, 900] } }, person("S2")],
      intervals: [interval("S1", { certainty: "probable", basis: "visual-and-stereo", evidence: [] }),
        interval(null, { certainty: "unresolved", basis: "transcript-only", evidence: [] })] },
    captionPhrases: [{ source: "raw-1", sourceWordIndexes: [10, 11], display: "TEST given", decidedBy: "operator",
      files: ["selections"], note: null }],
    coverage: { batch: "batch-test", clips: [{ clipId: "Q1", scriptIdentity: SHA, wordRanges: [[2, 5]] }],
      observations: { reference: REFERENCE, faceCoverage: [] } } };
  return { ...record, ...extra };
}

/** A TEST version 1 record: no certainty, basis, phrases or coverage. */
function v1Record(listening: boolean) {
  return { schemaVersion: 1, kind: KIND, speakers: { method: "TEST", listening, limits: ["TEST"],
    people: [{ id: "S1", description: "TEST", visibility: "TEST", evidence: [] }],
    intervals: [interval("S1"), interval(null)] } };
}

/** The strings of one `NAME = (...)` tuple in the Python module that defines the vocabulary, read as text. */
function pythonTuple(name: string): string[] {
  const source = readFileSync(path.join(SCRIPTS_DIR, "producer", "role_packet_evidence_speakers.py"), "utf8");
  const tuple = source.match(new RegExp(`^${name} = \\(([^)]*)\\)$`, "m"));
  assert.ok(tuple, `role_packet_evidence_speakers.py defines ${name} as one tuple`);
  return [...tuple[1].matchAll(/"([^"]*)"/g)].map(match => match[1]);
}

test("X53: the vocabulary is P2-07's, verbatim, and the TS mirror equals the Python definition", () => {
  assert.deepEqual([...SPEAKER_CERTAINTIES], ["established", "probable", "unresolved"]);
  assert.deepEqual([...SPEAKER_BASES], ["listening", "operator-statement", "visual-and-stereo", "transcript-only"]);
  assert.deepEqual([...SPEAKER_CERTAINTIES], pythonTuple("CERTAINTIES"));
  assert.deepEqual([...SPEAKER_BASES], pythonTuple("BASES"));
});

test("a version 2 record reads its people, intervals, coverage and observations reference verbatim", () => {
  const facts = sharedSpeakerFacts(v2Record());
  assert.equal(facts.schemaVersion, 2);
  assert.deepEqual(facts.people, [{ id: "S1", faceRegion: { source: "raw-1", xRange: [0, 900] } },
    { id: "S2", faceRegion: null }]);
  assert.deepEqual(facts.intervals.map(row => [row.speaker, row.certainty, row.basis]),
    [["S1", "probable", "visual-and-stereo"], [null, "unresolved", "transcript-only"]]);
  assert.deepEqual(facts.clips, [{ clipId: "Q1", scriptIdentity: SHA, wordRanges: [[2, 5]] }]);
  assert.deepEqual(facts.observations, REFERENCE);
  assert.deepEqual(sharedCaptionPhrases(v2Record()),
    [{ source: "raw-1", sourceWordIndexes: [10, 11], display: "TEST given", decidedBy: "operator" }]);
  const without = sharedSpeakerFacts(v2Record({ coverage: null }));
  assert.deepEqual([without.clips, without.observations], [null, null]);
});

test("the observations reference and covered script identities must be SHA-256 digests", () => {
  const record = v2Record(), coverage = record.coverage;
  for (const key of ["sha256", "ownerSha256"] as const) {
    const reference = { ...REFERENCE, [key]: "TEST-not-a-digest" };
    assert.throws(() => sharedSpeakerFacts({ ...record, coverage: { ...coverage, observations: { reference } } }),
      new RegExp(`reference.${key} must be a lowercase SHA-256`));
  }
  const clips = [{ ...coverage.clips[0], scriptIdentity: "TEST" }];
  assert.throws(() => sharedSpeakerFacts({ ...record, coverage: { ...coverage, clips } }),
    /coverage.clips\[0\].scriptIdentity must be a lowercase SHA-256/);
});

test("a version 1 record maps certainty read-only and carries no phrases or coverage", () => {
  for (const [listening, certainty, basis] of [[false, "probable", null], [true, "established", "listening"]] as const) {
    const facts = sharedSpeakerFacts(v1Record(listening));
    assert.equal(facts.schemaVersion, 1);
    assert.deepEqual(facts.intervals.map(row => [row.certainty, row.basis]), [[certainty, basis], ["unresolved", basis]]);
    assert.deepEqual([facts.clips, facts.observations, sharedCaptionPhrases(v1Record(listening))], [null, null, []]);
  }
});

test("version 2 invariants and record identity are refused by name", () => {
  const record = v2Record(), rows = record.speakers.intervals;
  const cases: [object, RegExp][] = [
    [{ ...record, speakers: { ...record.speakers, intervals: [{ ...rows[0], certainty: "unresolved" }] } },
      /intervals\[0\]: certainty is unresolved exactly when speaker is null/],
    [{ ...record, speakers: { ...record.speakers, intervals: [{ ...rows[1], certainty: "probable" }] } },
      /intervals\[0\]: certainty is unresolved exactly when speaker is null/],
    [{ ...record, speakers: { ...record.speakers, intervals: [{ ...rows[0], certainty: "likely" }] } }, /certainty must be one of/],
    [{ ...record, speakers: { ...record.speakers, intervals: [{ ...rows[0], basis: "stills" }] } }, /basis must be one of/],
    [{ ...record, speakers: { ...record.speakers, listening: "no" } }, /listening must be true or false/],
    [{ ...record, schemaVersion: 3 }, /schema version 1 or 2/],
    [{ ...record, kind: "TEST-other" }, /schema version 1 or 2/],
  ];
  for (const [value, message] of cases) assert.throws(() => sharedSpeakerFacts(value as Record<string, unknown>), message);
  const phrase = record.captionPhrases[0];
  assert.throws(() => sharedCaptionPhrases({ ...record, captionPhrases: [{ ...phrase, decidedBy: "editor" }] }),
    /decidedBy must be one of/);
  assert.throws(() => sharedCaptionPhrases({ ...record, captionPhrases: [{ ...phrase, sourceWordIndexes: [10] }] }),
    /sourceWordIndexes must be \[first, last\]/);
});

test("the submission re-check accepts a version 2 record's current report exactly as version 1's", t => {
  const bound = { path: "/TEST/SHARED-EVIDENCE-v2.json", sha256: "c".repeat(64), contentSha256: "d".repeat(64), version: 2 };
  t.mock.method(evidenceCheck, "run", () => ({ status: "shared-evidence-current", ...bound }));
  assert.deepEqual(recheckSharedEvidence(bound), bound);
  t.mock.method(evidenceCheck, "run", () => ({ status: "shared-evidence-current", ...bound, contentSha256: "e".repeat(64) }));
  assert.throws(() => recheckSharedEvidence(bound), /no longer current/);
});
