/**
 * Stable-code error for the P2 plan-build checks (P2-EARLY-CHECKS P2-02).
 *
 * Every new TS check in Phase 2 throws this, so the CLI output, the build report and the replay harness see a
 * stable `code` and a message of the form `[<code>] <text>`. Codes in use: reveal-cue-invalid,
 * reveal-not-statically-hidden, motion-cue-premature-reveal, protected-phrases-malformed,
 * protected-phrase-crosses-cut, protected-phrase-split, protected-phrase-dropped,
 * protected-phrase-partly-retained, the six speaker-picture codes of P2-08, explanatory-beat-unbound.
 * Existing checks keep their plain `Error`s.
 */

/** A failed P2 check: `code` is stable; `message` is `[<code>] <text>`. */
export class NativeCheckError extends Error {
  readonly code: string;

  constructor(code: string, text: string) {
    super(`[${code}] ${text}`);
    this.code = code;
  }
}
