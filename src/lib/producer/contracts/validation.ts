export type JsonRecord = Record<string, unknown>;

export const SHA256_RE = /^[0-9a-f]{64}$/u;
export const STABLE_ID_RE = /^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$/u;
export const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/u;

export function hasOwn(value: JsonRecord, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(value, key);
}

export function objectValue(value: unknown, label: string): JsonRecord {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} must be an object`);
  }
  return value as JsonRecord;
}

export function exactKeys(
  value: JsonRecord,
  allowed: readonly string[],
  required: readonly string[],
  label: string,
): void {
  const extras = Object.keys(value).filter((key) => !allowed.includes(key));
  if (extras.length) {
    throw new Error(`${label} has unsupported fields: ${extras.join(", ")}`);
  }
  const missing = required.filter((key) => !hasOwn(value, key));
  if (missing.length) {
    throw new Error(`${label} is missing fields: ${missing.join(", ")}`);
  }
}

export function stringValue(
  value: unknown,
  label: string,
  maximum = 10_000,
): string {
  if (typeof value !== "string" || !value.trim()) {
    throw new Error(`${label} must be a non-empty string`);
  }
  if (Array.from(value).length > maximum) {
    throw new Error(`${label} exceeds ${maximum} characters`);
  }
  return value;
}

export function stableId(value: unknown, label: string): string {
  const result = stringValue(value, label, 128);
  if (!STABLE_ID_RE.test(result)) throw new Error(`${label} is not a stable id`);
  return result;
}

export function uuid(value: unknown, label: string): string {
  const result = stringValue(value, label, 36);
  if (!UUID_RE.test(result)) throw new Error(`${label} must be a canonical UUID`);
  return result;
}

export function sha256(value: unknown, label: string): string {
  if (typeof value !== "string" || !SHA256_RE.test(value)) {
    throw new Error(`${label} must be a lowercase SHA-256`);
  }
  return value;
}

export function isoDate(value: unknown, label: string): string {
  const result = stringValue(value, label, 64);
  if (!/^\d{4}-\d{2}-\d{2}T/u.test(result) || !Number.isFinite(Date.parse(result))) {
    throw new Error(`${label} must be an ISO-8601 timestamp`);
  }
  return result;
}

export function enumValue<T extends string>(
  value: unknown,
  allowed: readonly T[],
  label: string,
): T {
  if (typeof value !== "string" || !allowed.includes(value as T)) {
    throw new Error(`${label} must be one of ${allowed.join(", ")}`);
  }
  return value as T;
}

export function uniqueStrings(
  value: unknown,
  label: string,
  parser: (item: unknown, itemLabel: string) => string = stableId,
): string[] {
  if (!Array.isArray(value)) throw new Error(`${label} must be an array`);
  const parsed = value.map((item, index) => parser(item, `${label}[${index}]`));
  if (new Set(parsed).size !== parsed.length) {
    throw new Error(`${label} must contain unique values`);
  }
  return parsed;
}

export function hashRecord(value: unknown, label: string): Record<string, string> {
  const input = objectValue(value, label);
  return Object.fromEntries(
    Object.entries(input).map(([key, item]) => [
      stableId(key, `${label} key`),
      sha256(item, `${label}.${key}`),
    ]),
  );
}
