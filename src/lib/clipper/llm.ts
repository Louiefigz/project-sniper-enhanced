import { LineDecision } from "@/lib/clipper/types";

export interface ParseIndexedDecisionsResult {
  decisions: LineDecision[];
  /** Indices that were absent from the LLM response and defaulted to KEEP. */
  missingIndices: number[];
}

/** Shape of a single decision from the tool call JSON. */
interface ToolDecision {
  index: number;
  action: "KEEP" | "REMOVE" | "TRIM";
  trimmed_text?: string;
}

/**
 * Parse the LLM's tool-call JSON output into LineDecision[].
 *
 * Expects a complete JSON object matching the submit_edit_decisions tool input:
 *   { "decisions": [{ "index": 0, "action": "KEEP" }, ...] }
 *
 * Throws on malformed input — non-JSON, partial JSON, unknown action values,
 * missing/duplicate/out-of-range indices, TRIM without trimmed_text. Loud
 * failures keep tool-use regressions from silently turning into all-KEEP.
 *
 * Indices omitted from a well-formed response default to KEEP (safe — never
 * silently deletes content) and are reported via missingIndices.
 */
export function parseIndexedDecisions(
  response: string,
  totalLines: number,
  startIndex: number
): ParseIndexedDecisionsResult {
  const trimmed = response.trim();
  if (!trimmed) {
    throw new Error("parseIndexedDecisions: empty response");
  }
  if (!trimmed.startsWith("{")) {
    throw new Error(
      `parseIndexedDecisions: expected JSON tool-call output, got: ${trimmed.slice(0, 80)}…`
    );
  }

  let parsed: { decisions?: ToolDecision[] };
  try {
    parsed = JSON.parse(trimmed);
  } catch (err) {
    throw new Error(
      `parseIndexedDecisions: invalid JSON (${err instanceof Error ? err.message : String(err)})`
    );
  }

  if (!Array.isArray(parsed.decisions)) {
    throw new Error("parseIndexedDecisions: missing 'decisions' array");
  }

  return buildFromToolDecisions(parsed.decisions, totalLines, startIndex);
}

function buildFromToolDecisions(
  toolDecisions: ToolDecision[],
  totalLines: number,
  startIndex: number
): ParseIndexedDecisionsResult {
  const decisionMap = new Map<number, LineDecision>();
  const endExclusive = startIndex + totalLines;

  for (const d of toolDecisions) {
    if (!Number.isInteger(d.index)) {
      throw new Error(
        `parseIndexedDecisions: decision missing integer 'index' (got ${JSON.stringify(d.index)})`
      );
    }
    if (d.index < startIndex || d.index >= endExclusive) {
      throw new Error(
        `parseIndexedDecisions: index ${d.index} out of range [${startIndex}, ${endExclusive})`
      );
    }
    if (decisionMap.has(d.index)) {
      throw new Error(`parseIndexedDecisions: duplicate decision for index ${d.index}`);
    }

    const upperAction = typeof d.action === "string" ? d.action.toUpperCase() : "";
    if (upperAction !== "KEEP" && upperAction !== "REMOVE" && upperAction !== "TRIM") {
      throw new Error(
        `parseIndexedDecisions: index ${d.index} has invalid action ${JSON.stringify(d.action)} (expected KEEP|REMOVE|TRIM)`
      );
    }
    if (upperAction === "TRIM" && !d.trimmed_text) {
      throw new Error(
        `parseIndexedDecisions: index ${d.index} is TRIM but missing trimmed_text`
      );
    }

    const action = upperAction.toLowerCase() as "keep" | "remove" | "trim";
    decisionMap.set(d.index, {
      index: d.index,
      action,
      ...(action === "trim" ? { text: d.trimmed_text } : {}),
    });
  }

  return fillMissing(decisionMap, totalLines, startIndex);
}

function fillMissing(
  decisionMap: Map<number, LineDecision>,
  totalLines: number,
  startIndex: number
): ParseIndexedDecisionsResult {
  const decisions: LineDecision[] = [];
  const missingIndices: number[] = [];

  for (let i = 0; i < totalLines; i++) {
    const idx = startIndex + i;
    if (decisionMap.has(idx)) {
      decisions.push(decisionMap.get(idx)!);
    } else {
      missingIndices.push(idx);
      decisions.push({ index: idx, action: "keep" });
    }
  }

  if (missingIndices.length > 0) {
    console.warn(
      `Warning: ${missingIndices.length} ${missingIndices.length === 1 ? "index" : "indices"} had no LLM decision, defaulting to KEEP: [${missingIndices.join(", ")}]`
    );
  }

  return { decisions, missingIndices };
}
