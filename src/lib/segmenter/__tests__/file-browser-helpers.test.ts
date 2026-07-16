import assert from "node:assert/strict";
import {
  autoAssign,
  DEFAULT_SEGMENT_PROMPT,
  SEGMENT_PROMPT_TEMPLATES,
  segmentPromptForTemplate,
  segmentsFromPayload,
  validateSegments,
  validateTranscript,
} from "../file-browser-helpers";
import {
  consumeTranscriptionStream,
  parseSseDataLine,
} from "../transcription-stream";

const transcript = [
  { start: 0, end: 2, text: "Welcome Alex" },
  { start: 2, end: 5, text: "Thanks for having me" },
];
const segment = {
  id: 1,
  title: "Alex",
  startLine: 0,
  endLine: 1,
  start: 0,
  end: 5,
  summary: "Alex joins the host.",
};

assert.deepEqual(validateTranscript(transcript), transcript);
assert.throws(() => validateTranscript([]), /0 utterances/);
assert.throws(
  () => validateTranscript([{ start: 5, end: 1, text: "bad" }]),
  /invalid utterance/,
);

assert.deepEqual(validateSegments([segment], transcript.length), [segment]);
assert.throws(() => validateSegments([], transcript.length), /no segments/);
assert.throws(
  () => validateSegments([{ ...segment, title: "" }], transcript.length),
  /invalid segment/,
);
assert.throws(
  () => validateSegments([segment, { ...segment, id: 2 }], transcript.length),
  /invalid segment/,
);
assert.throws(
  () => segmentsFromPayload({ error: "provider unavailable", segments: [segment] }, transcript.length),
  /provider unavailable/,
);
assert.throws(
  () => segmentsFromPayload({ error: { code: "failed" } }, transcript.length),
  /returned an error/,
);
assert.deepEqual(segmentsFromPayload({ segments: [segment] }, transcript.length), [segment]);

const assignment = autoAssign([
  { path: "/b.mov", name: "show_b-cam.mov" },
  { path: "/a.mp4", name: "show_master.mp4" },
  { path: "/lav.wav", name: "host_lav.wav" },
]);
assert.equal(assignment.assigned.a?.path, "/a.mp4");
assert.equal(assignment.assigned.b?.path, "/b.mov");
assert.equal(assignment.assigned.lav1?.path, "/lav.wav");

assert.equal(SEGMENT_PROMPT_TEMPLATES[0].id, "topics");
assert.match(SEGMENT_PROMPT_TEMPLATES[0].description, /Recommended/);
assert.equal(segmentPromptForTemplate("topics"), DEFAULT_SEGMENT_PROMPT);
assert.match(segmentPromptForTemplate("coaching"), /coaching show/i);
assert.equal(segmentPromptForTemplate("custom"), "");

assert.equal(parseSseDataLine(": keepalive"), null);
assert.deepEqual(parseSseDataLine('data: {"status":"done"}'), { status: "done" });
assert.throws(() => parseSseDataLine("data: not-json"), /malformed stream event/);

async function testStreamCompletion(): Promise<void> {
  const completed = await consumeTranscriptionStream(
    new Response(`data: ${JSON.stringify({ status: "done", transcript, duration: 5 })}\n\n`),
    { onMessage: () => undefined },
  );
  assert.deepEqual(completed.transcript, transcript);
  assert.equal(completed.duration, 5);
  await assert.rejects(
    consumeTranscriptionStream(
      new Response('data: {"status":"transcribing_chunk","chunk":1,"total":1}\n\n'),
      { onMessage: () => undefined },
    ),
    /terminal done event/,
  );
  await assert.rejects(
    consumeTranscriptionStream(
      new Response('data: {"status":"done","transcript":[]}\n\n'),
      { onMessage: () => undefined },
    ),
    /0 utterances/,
  );
}

testStreamCompletion()
  .then(() => console.log("file-browser-helpers.test.ts: all assertions passed"))
  .catch((error: unknown) => {
    console.error(error);
    process.exitCode = 1;
  });
