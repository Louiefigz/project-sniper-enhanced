function positiveInteger(event: Record<string, unknown>, keys: string[]): number | null {
  for (const key of keys) {
    const value = event[key];
    if (Number.isInteger(value) && Number(value) > 0) return Number(value);
  }
  return null;
}

function roundCopy(
  label: string,
  event: Record<string, unknown>,
  roundKeys: string[],
  maxKeys: string[],
): string {
  const round = positiveInteger(event, roundKeys);
  const max = positiveInteger(event, maxKeys);
  if (round && max) return `${label} ${round} of ${max}`;
  return round ? `${label} ${round}` : label;
}

function materialIssueCount(event: Record<string, unknown>): number {
  const direct = positiveInteger(event, [
    "materialIssueCount", "materialIssues", "issueCount", "findingCount",
  ]);
  if (direct) return direct;
  const review = event.review && typeof event.review === "object"
    ? event.review as Record<string, unknown> : null;
  const lists = [
    event.materialIssues,
    review?.materialIssues,
    event.unresolvedFindingIds,
    event.errors,
  ];
  return lists.find(Array.isArray)?.length ?? 0;
}

function reviewPassed(event: Record<string, unknown>): boolean {
  if (event.ok === true || event.verdict === "pass") return true;
  if (!event.review || typeof event.review !== "object") return false;
  return (event.review as Record<string, unknown>).verdict === "pass";
}

function reviewLens(event: Record<string, unknown>): string {
  const lens = typeof event.lens === "string" ? event.lens : "visual";
  if (lens === "composition") return "Composition";
  if (lens === "editorial") return "Editorial";
  return "Visual";
}

export function eventElapsedSuffix(event: Record<string, unknown>): string {
  const ms = Number(event.ms);
  if (!Number.isFinite(ms) || ms < 0) return "";
  const seconds = Math.max(1, Math.round(ms / 1_000));
  if (seconds < 60) return ` · ${seconds}s elapsed`;
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return ` · ${minutes}m ${remainder}s elapsed`;
}

function cutProgress(name: string, event: Record<string, unknown>): string | null {
  const review = roundCopy("Transcript cut review", event, ["round"], ["maxRounds"]);
  const required = positiveInteger(event, ["requiredCleanReviews"]);
  const cleanRule = required
    ? ` · ${required} clean independent reviews of the same cut are required`
    : "";
  if (name === "cut_review_started") return `${review} started${cleanRule}.`;
  if (name === "cut_review_completed") {
    const issues = materialIssueCount(event);
    return reviewPassed(event)
      ? `${review} found no material issues${eventElapsedSuffix(event)} · checking cut approval.`
      : `${review} found ${issues || "material"} issue${issues === 1 ? "" : "s"}${eventElapsedSuffix(event)} · cut revision and a fresh review remain.`;
  }
  if (name === "cut_revision_started") return `${review} revision started.`;
  if (name === "cut_revision_completed") {
    return `${review} revision complete · deterministic cut validation and fresh review remain.`;
  }
  return null;
}

function planningProgress(name: string, event: Record<string, unknown>): string | null {
  const planning = roundCopy(
    "Planning review", event, ["planningRound", "round"],
    ["planningRoundsRequired", "requiredRounds", "maxRounds"],
  );
  const issues = materialIssueCount(event);
  if (name === "planning_review_started") {
    return `${planning} started · fresh editor review is running; revision or render follows.`;
  }
  if (name === "planning_review_completed") {
    return reviewPassed(event)
      ? `${planning} found no material issues${eventElapsedSuffix(event)} · checking the required review count.`
      : `${planning} found ${issues || "material"} issue${issues === 1 ? "" : "s"}${eventElapsedSuffix(event)} · revision and another full review remain.`;
  }
  if (name === "planning_gate_bundle") {
    return event.ok
      ? "Deterministic planning gates passed · fresh editor review remains."
      : `Deterministic planning gates failed${issues ? ` with ${issues} issue${issues === 1 ? "" : "s"}` : ""} · revision and a full gate rerun remain.`;
  }
  if (name === "revision_completed") {
    return `${planning} revision complete · rerunning every deterministic gate and a fresh editor review.`;
  }
  return null;
}

function renderedReviewProgress(
  name: string,
  event: Record<string, unknown>,
  candidate: string,
): string | null {
  if (name === "rendered_review_started") {
    return `${candidate} · ${reviewLens(event).toLowerCase()} review started; approval waits for both visual reviews.`;
  }
  if (name !== "rendered_review_completed") return null;
  const lens = reviewLens(event);
  const issues = materialIssueCount(event);
  if (!reviewPassed(event)) {
    return `${candidate} · ${lens.toLowerCase()} review found ${issues || "material"} issue${issues === 1 ? "" : "s"}${eventElapsedSuffix(event)}; repair or a stop decision follows.`;
  }
  return `${candidate} · ${lens.toLowerCase()} review passed${eventElapsedSuffix(event)}; aggregate QC waits for both visual reviews.`;
}

function candidateProgress(name: string, event: Record<string, unknown>): string | null {
  const candidate = roundCopy(
    "Candidate", event, ["qcRound", "candidateRound", "round"], ["qcRoundsMax", "maxRounds"],
  );
  const review = renderedReviewProgress(name, event, candidate);
  if (review) return review;
  const issues = materialIssueCount(event);
  if (name === "candidate_ready") {
    return `${candidate} rendered · Audit B, composition review, and editorial review remain.`;
  }
  if (name === "repair_started") {
    return `${candidate} repair started${issues ? ` for ${issues} finding${issues === 1 ? "" : "s"}` : ""} · plan review, gates, re-render, and QC remain.`;
  }
  if (name === "repair_completed") {
    return `${candidate} repair complete · re-reviewing the plan before a fresh candidate render.`;
  }
  if (name === "candidate_checks_passed") {
    return `${candidate} passed every check · recording approval and promoting it now.`;
  }
  if (name === "candidate_approved") {
    return `${candidate} passed all QC · approval is recorded; final-file promotion remains.`;
  }
  if (name === "candidate_promoted" && event.mode === "palmier-native-initial") {
    return `${candidate} promoted · the exact editable Palmier timeline is approved.`;
  }
  if (name === "candidate_promoted") return `${candidate} promoted · the approved final video is ready.`;
  if (name === "quality_blocked") {
    return `${candidate} has ${issues || "non-plan-repairable"} blocking issue${issues === 1 ? "" : "s"} · no candidate was promoted.`;
  }
  return null;
}

export function planRefitProgressMessage(event: Record<string, unknown>): string | null {
  if (event.event !== "plan_refit_receipt") return null;
  const remapped = Number(event.remapped) || 0;
  const dropped = Number(event.dropped) || 0;
  const adjusted = `${remapped} timed element${remapped === 1 ? "" : "s"} remapped`;
  const prefix = event.alreadyApplied === true
    ? "Existing cut-timebase receipt · no second remap was applied"
    : "Cut-timebase receipt";
  if (dropped) {
    const reason = event.alreadyApplied === true
      ? "removed when that cut was applied"
      : "removed because the new cut removed their content";
    return `${prefix} · ${adjusted}; ${dropped} element${dropped === 1 ? " was" : "s were"} ${reason}.`;
  }
  return `${prefix} · ${adjusted}; no timed elements were dropped.`;
}

/** Progress copy for the bounded planning and rendered-QC controller events. */
export function boundedAutoEditProgressMessage(event: Record<string, unknown>): string | null {
  const refit = planRefitProgressMessage(event);
  if (refit) return refit;
  const name = typeof event.event === "string" ? event.event : "";
  const cut = cutProgress(name, event);
  if (cut) return cut;
  const planning = planningProgress(name, event);
  if (planning) return planning;
  const candidate = candidateProgress(name, event);
  if (candidate) return candidate;
  if (name !== "max_rounds_exhausted") return null;
  const issues = materialIssueCount(event);
  const stage = event.stage === "planning" ? "planning reviews" : "QC attempts";
  return `Maximum ${stage} reached${issues ? ` with ${issues} unresolved finding${issues === 1 ? "" : "s"}` : ""} · no unapproved candidate was promoted.`;
}
