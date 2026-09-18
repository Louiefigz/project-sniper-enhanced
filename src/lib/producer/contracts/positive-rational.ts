import { exactKeys, objectValue, stringValue } from "./validation";

export interface PositiveRationalV1 {
  numerator: string;
  denominator: string;
}

function gcd(left: bigint, right: bigint): bigint {
  let a = left;
  let b = right;
  while (b !== BigInt(0)) [a, b] = [b, a % b];
  return a;
}

function positiveInteger(value: unknown, label: string): string {
  const result = stringValue(value, label, 10_000);
  if (!/^[1-9][0-9]*$/u.test(result)) {
    throw new Error(`${label} must be a canonical positive integer string`);
  }
  return result;
}

export function parsePositiveRationalV1(value: unknown): PositiveRationalV1 {
  const rational = objectValue(value, "PositiveRationalV1");
  exactKeys(
    rational,
    ["numerator", "denominator"],
    ["numerator", "denominator"],
    "PositiveRationalV1",
  );
  const numerator = positiveInteger(rational.numerator, "numerator");
  const denominator = positiveInteger(rational.denominator, "denominator");
  if (gcd(BigInt(numerator), BigInt(denominator)) !== BigInt(1)) {
    throw new Error("PositiveRationalV1 must be reduced");
  }
  return { numerator, denominator };
}
