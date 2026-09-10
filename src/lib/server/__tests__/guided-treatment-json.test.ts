import assert from "node:assert/strict";
import { test } from "node:test";
import { parseTreatmentRequestJson as parse } from "../../../../scripts/producer/guided-treatment-json";

test("rejects duplicate decoded keys at every object depth, including contradictory attestations", () => {
  const inputs = [
    '{"attestation":false,"attestation":true}',
    '{"attestation":false,"\\u0061ttestation":true}',
    '{"attestation":{"watched":false,"watched":true}}',
    '{"attestation":{"watched":false,"\\u0077atched":true}}',
    '{"outer":[0,{"inner":{"listened":false,"listened":true}}]}',
    '{"__proto__":null,"__proto__":true}',
    '{"a\\nb":0,"a\\u000ab":1}',
    '{"𝄞":0,"\\ud834\\udd1e":1}',
  ];
  for (const input of inputs) assert.throws(() => parse(input), /duplicate JSON object key/);
});

test("separate objects may repeat keys and delimiter-like raw intent remains exact data", () => {
  const value = { rawIntent: 'Keep {braces}, [arrays]: "quoted" \\ and \\u0061; é 😀\n\t',
    rows: [{ watched: true }, { watched: false }], nested: { rawIntent: "untouched" } };
  const text = JSON.stringify(value);
  assert.deepEqual(parse(` \n\t${text}\r `), value);
  assert.deepEqual(parse('{"a":1,"\\u0062":2}'), { a: 1, b: 2 });
});

test("rejects nonfinite numeric overflow at root, array and nested object locations", () => {
  for (const text of ["1e400", "-1e400", "[0,1E+400]", '{"a":{"b":-9e999}}']) {
    assert.throws(() => parse(text), /numbers must be finite/);
  }
  const text = '[0,-0,1e-400,1e300,-0.125,2.5E+2,true,false,null,"1e400"]';
  assert.deepEqual(parse(text), JSON.parse(text));
});

test("malformed grammar, trailing data, invalid escapes and controls fail closed", () => {
  const inputs = ["", " ", "{}{}", "{} true", "[1,]", '{"a":1,}', '{"a" 1}', "{a:1}",
    '[1 2]', '{"a":}', "[", "{", '"unterminated', '"a\\"', '"\\q"', '"\\u12xx"',
    '"a\nb"', "NaN", "Infinity", "undefined", "01", "1.", "+1", "truex", "[truefalse]", "\ufeff{}"];
  for (const text of inputs) assert.throws(() => parse(text), Error, text);
});

test("sixteen container levels remain valid; deeper nesting rejects before final JSON.parse", () => {
  const allowed = "[".repeat(16) + "0" + "]".repeat(16);
  assert.deepEqual(parse(allowed), JSON.parse(allowed));
  for (const depth of [17, 3000]) {
    assert.throws(() => parse("[".repeat(depth) + "0" + "]".repeat(depth)), /JSON depth limit/);
  }
  const objects = '{"nested":'.repeat(17) + "null" + "}".repeat(17);
  assert.throws(() => parse(objects), /JSON depth limit/);
});

test("aggregate token count is bounded across keys and values, not only nested depth", () => {
  const allowed = "[" + Array(16383).fill("0").join(",") + "]";
  assert.deepEqual(parse(allowed), JSON.parse(allowed));
  assert.throws(() => parse("[" + Array(16384).fill("0").join(",") + "]"), /JSON token limit/);
  const keys = Array.from({ length: 8192 }, (_, index) => `"${index}":0`).join(",");
  assert.throws(() => parse(`{${keys}}`), /JSON token limit/);
});

test("byte cap rejects multi-byte overflow while full escaped raw-intent contract fits", () => {
  assert.throws(() => parse(JSON.stringify("é".repeat(65536))), /JSON byte limit/);
  const value = "a".repeat(20000);
  assert.deepEqual(parse('{"rawIntent":"' + "\\u0061".repeat(20000) + '"}'), { rawIntent: value });
});
