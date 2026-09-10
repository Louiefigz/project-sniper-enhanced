/** Strict treatment transport; service hashing and shape validation stay unchanged. */
import { MAX_BOUNDED_JSON_BYTES, parseBoundedJson } from "../../src/lib/producer/contracts/bounded-json";

// Accommodates the existing 20000 UTF-16-unit raw intent even when every unit is JSON-escaped.
export const MAX_TREATMENT_REQUEST_BYTES = MAX_BOUNDED_JSON_BYTES;

/** Preserve existing treatment bounds and diagnostics using the shared duplicate-key-safe scanner. */
export function parseTreatmentRequestJson(source: string): unknown {
  return parseBoundedJson(source, "Treatment request");
}
