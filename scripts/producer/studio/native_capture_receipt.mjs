/** Lossless compaction of repeated per-frame typography in native capture receipts. */
import assert from 'node:assert/strict';
import {isDeepStrictEqual} from 'node:util';

/**
 * Every captured frame re-reads every caption and word element, although only clip and color
 * change from frame to frame (E's audited receipt: 755 rows, 45.36 MiB). The receipt keeps the
 * first complete state once and, per frame, only the fields that differ from it. Expansion is
 * asserted equal to the observed state for every frame before a receipt is published.
 */
export const TYPOGRAPHY_ENCODING = 'reference-and-sparse-changes-v1';

function isRecord(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function isFullTypography(value) {
  return isRecord(value) && ['lines', 'captions', 'words'].every(key => Array.isArray(value[key])) && 'titleClip' in value;
}

function sameShape(base, rows) {
  return Array.isArray(base) && Array.isArray(rows) && base.length === rows.length && rows.every((row, index) =>
    isRecord(row) && isRecord(base[index]) && isDeepStrictEqual(Object.keys(row).sort(), Object.keys(base[index]).sort()));
}

/** Changes turning `reference` into `state`: equal-shape row arrays per index/field, else whole values. */
export function typographyChanges(reference, state) {
  assert.ok(isDeepStrictEqual(Object.keys(state).sort(), Object.keys(reference).sort()), 'Typography state keys changed');
  const changes = {};
  for (const [key, value] of Object.entries(state)) {
    const base = reference[key];
    if (isDeepStrictEqual(base, value)) continue;
    if (!sameShape(base, value)) { changes[key] = {value}; continue; }
    const rows = {};
    value.forEach((row, index) => {
      const fields = Object.entries(row).filter(([field, item]) => !isDeepStrictEqual(item, base[index][field]));
      if (fields.length) rows[index] = Object.fromEntries(fields);
    });
    changes[key] = {rows};
  }
  return changes;
}

/** The complete state recorded by `typographyChanges`. */
export function expandTypography(reference, changes) {
  const state = structuredClone(reference);
  for (const [key, change] of Object.entries(changes)) {
    if (Object.hasOwn(change, 'value')) { state[key] = structuredClone(change.value); continue; }
    for (const [index, fields] of Object.entries(change.rows)) Object.assign(state[key][Number(index)], structuredClone(fields));
  }
  return state;
}

/** Replace each complete per-frame typography state with exact sparse changes (in place). */
export function compactNativeTypography(receipt) {
  const rows = receipt.frames.filter(row => isFullTypography(row.typography));
  if (!rows.length) return receipt;
  const reference = rows[0].typography;
  for (const row of rows) {
    const changes = typographyChanges(reference, row.typography);
    assert.ok(isDeepStrictEqual(expandTypography(reference, changes), row.typography),
      `Typography compaction is not exact at frame ${row.frame}`);
    delete row.typography;
    row.typographyChanges = changes;
  }
  receipt.typographyEncoding = TYPOGRAPHY_ENCODING;
  receipt.typographyReference = reference;
  return receipt;
}

/** Every frame's complete typography state, for tools and tests (uncompacted rows pass through). */
export function expandNativeTypography(receipt) {
  if (receipt.typographyEncoding === undefined) return receipt.frames.map(row => row.typography);
  assert.equal(receipt.typographyEncoding, TYPOGRAPHY_ENCODING, 'Unknown typography encoding');
  return receipt.frames.map(row => row.typographyChanges
    ? expandTypography(receipt.typographyReference, row.typographyChanges) : row.typography);
}
