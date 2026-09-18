/**
 * Greedy forward token matcher with concatenation fallback.
 *
 * Handles tokenization mismatches between the LLM's TRIM text and Deepgram's
 * word-level tokens. For example:
 *   LLM writes "530k"      — Deepgram has ["530", "k"]      → pool concat
 *   LLM writes "1,200,000" — Deepgram has ["1,200,000.0"]   → trim concat
 *
 * For each trim token, tries in order:
 *   1. Direct match
 *   2. Concatenate up to 3 consecutive pool tokens → trim token
 *   3. Concatenate up to 3 consecutive trim tokens → pool token
 *   4. Skip pool token (no match at this position)
 *
 * Returns a Set of pool indices that were matched (i.e., should be kept).
 */
export function greedyMatch(trimTokens: string[], poolNorm: string[]): Set<number> {
  const kept = new Set<number>();
  let si = 0; // current pool position

  for (let ti = 0; ti < trimTokens.length; ti++) {
    const trimWord = trimTokens[ti];
    let matched = false;

    while (si < poolNorm.length && !matched) {
      if (poolNorm[si] === trimWord) {
        // 1. Direct match
        kept.add(si); si++; matched = true;
      } else {
        // 2. Pool concat: "530" + "k" === "530k"
        let poolConcat = poolNorm[si];
        let poolConcatMatched = false;
        for (let k = 1; k <= 2 && si + k < poolNorm.length; k++) {
          poolConcat += poolNorm[si + k];
          if (poolConcat === trimWord) {
            for (let m = 0; m <= k; m++) kept.add(si + m);
            si += k + 1;
            poolConcatMatched = true;
            break;
          }
        }
        if (poolConcatMatched) { matched = true; break; }

        // 3. Trim concat: "1,200,000" + "." === "1,200,000."
        let trimConcat = trimWord;
        let trimConcatMatched = false;
        for (let k = 1; k <= 2 && ti + k < trimTokens.length; k++) {
          trimConcat += trimTokens[ti + k];
          if (trimConcat === poolNorm[si]) {
            kept.add(si); si++;
            ti += k; // skip the consumed trim tokens
            trimConcatMatched = true;
            break;
          }
        }
        if (trimConcatMatched) { matched = true; break; }

        // 4. No match at this pool position — skip
        si++;
      }
    }
  }

  return kept;
}
