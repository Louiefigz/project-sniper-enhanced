/** Shared bounded JSON transport; shape and invocation authority remain separate. */
// Accommodates the existing 20000 UTF-16-unit raw intent even when every unit is JSON-escaped.
export const MAX_BOUNDED_JSON_BYTES = 128 * 1024;
const MAX_CONTAINER_DEPTH = 16;
const MAX_TOKENS = 16384;
const WHITESPACE = " \t\r\n";
const DELIMITERS = `${WHITESPACE}{[}]:,\"`;

function decodedToken(token: string, label: string): unknown {
  try { return JSON.parse(token); }
  catch { throw new Error(`${label} contains invalid JSON`); }
}

/** Bound traversal before final JSON.parse, preserving its value semantics without last-key-wins. */
class RequestScanner {
  private index = 0;
  private tokens = 0;

  constructor(private readonly source: string, private readonly label: string) {}

  scan(): void {
    this.value(0);
    this.space();
    if (this.index !== this.source.length) throw new Error(`${this.label} has trailing JSON data`);
  }

  private space(): void {
    while (this.index < this.source.length && WHITESPACE.includes(this.source[this.index])) this.index++;
  }

  private token(): void {
    if (++this.tokens > MAX_TOKENS) throw new Error(`${this.label} JSON token limit exceeded`);
  }

  private consume(character: string): boolean {
    this.space();
    if (this.source[this.index] !== character) return false;
    this.index++;
    return true;
  }

  private expect(character: string): void {
    if (!this.consume(character)) throw new Error(`${this.label} contains invalid JSON structure`);
  }

  private string(): string {
    const start = this.index;
    this.expect('"');
    while (this.index < this.source.length) {
      const character = this.source[this.index++];
      if (character === "\\") { this.index++; continue; }
      if (character === '"') return decodedToken(this.source.slice(start, this.index), this.label) as string;
    }
    throw new Error(`${this.label} contains an unterminated JSON string`);
  }

  private primitive(): void {
    const start = this.index;
    while (this.index < this.source.length && !DELIMITERS.includes(this.source[this.index])) this.index++;
    const value = decodedToken(this.source.slice(start, this.index), this.label);
    if (typeof value === "number" && !Number.isFinite(value)) throw new Error(`${this.label} numbers must be finite`);
    if (value !== null && typeof value !== "boolean" && typeof value !== "number") {
      throw new Error(`${this.label} contains an invalid JSON primitive`);
    }
  }

  private value(depth: number): void {
    this.token();
    this.space();
    const character = this.source[this.index];
    if (character === '"') { this.string(); return; }
    if (character !== "{" && character !== "[") { this.primitive(); return; }
    if (depth >= MAX_CONTAINER_DEPTH) throw new Error(`${this.label} JSON depth limit exceeded`);
    if (character === "{") this.object(depth + 1);
    else this.array(depth + 1);
  }

  private object(depth: number): void {
    this.expect("{");
    if (this.consume("}")) return;
    const keys = new Set<string>();
    do {
      this.space();
      this.token();
      const key = this.string();
      if (keys.has(key)) throw new Error(`${this.label} contains a duplicate JSON object key`);
      keys.add(key);
      this.expect(":");
      this.value(depth);
    } while (this.consume(","));
    this.expect("}");
  }

  private array(depth: number): void {
    this.expect("[");
    if (this.consume("]")) return;
    do { this.value(depth); } while (this.consume(","));
    this.expect("]");
  }
}

/** Reject ambiguous/unbounded transport before existing closed service validators see any value. */
export function parseBoundedJson(source: string, label: string): unknown {
  if (Buffer.byteLength(source, "utf8") > MAX_BOUNDED_JSON_BYTES) {
    throw new Error(`${label} JSON byte limit exceeded`);
  }
  new RequestScanner(source, label).scan();
  return JSON.parse(source);
}
