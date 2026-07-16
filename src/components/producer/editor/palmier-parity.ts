export type PalmierFidelity = "exact" | "approximate" | "baked" | "unsupported";

export interface PalmierParityCounts {
  findings: number;
  entries: number;
}

export interface PalmierParitySummary {
  findings: number;
  entries: number;
  byStatus: Record<PalmierFidelity, PalmierParityCounts>;
}

export interface LegacyPalmierParitySummary {
  exact: number;
  approximate: number;
  baked: number;
  unsupported: number;
}

export interface PalmierParityFinding {
  id: string;
  lane: string;
  status?: PalmierFidelity;
  fidelity?: PalmierFidelity;
  label: string;
  message: string;
  count?: number;
  blocksSync?: boolean;
}

export interface PalmierParity {
  fullyEditable: boolean;
  mirrorReady?: boolean;
  mirrorMode?: "visual-master" | "blocked" | string;
  summary: PalmierParitySummary | LegacyPalmierParitySummary;
  findings: PalmierParityFinding[];
  mirrorBlockers?: PalmierParityFinding[];
  capability?: {
    visibleTimeline?: string;
    visualAndAudioFidelity?: string;
    componentAssets?: string;
    componentTimelineEditability?: boolean;
    nativeReconstructionFullyEditable?: boolean;
  };
}

export interface PalmierParityState {
  fullyEditable: boolean;
  label: string;
  tone: "exact" | "partial" | "blocked" | "missing";
  summary: LegacyPalmierParitySummary;
}

export interface PalmierParityGroup {
  key: string;
  fidelity: PalmierFidelity;
  lane: string;
  label: string;
  message: string;
  count: number;
}

const EMPTY_SUMMARY: LegacyPalmierParitySummary = {
  exact: 0,
  approximate: 0,
  baked: 0,
  unsupported: 0,
};

function count(value: number | undefined): number {
  return Number.isFinite(value) && Number(value) > 0 ? Math.floor(Number(value)) : 0;
}

function isCurrentSummary(
  summary: PalmierParitySummary | LegacyPalmierParitySummary,
): summary is PalmierParitySummary {
  return "byStatus" in summary && !!summary.byStatus;
}

export function normalizedParitySummary(parity?: PalmierParity | null): LegacyPalmierParitySummary {
  if (!parity?.summary) return EMPTY_SUMMARY;
  if (isCurrentSummary(parity.summary)) {
    const byStatus = parity.summary.byStatus;
    return {
      exact: count(byStatus.exact?.entries),
      approximate: count(byStatus.approximate?.entries),
      baked: count(byStatus.baked?.entries),
      unsupported: count(byStatus.unsupported?.entries),
    };
  }
  return {
    exact: count(parity.summary.exact),
    approximate: count(parity.summary.approximate),
    baked: count(parity.summary.baked),
    unsupported: count(parity.summary.unsupported),
  };
}

export function palmierFindingFidelity(finding: PalmierParityFinding): PalmierFidelity {
  return finding.status ?? finding.fidelity ?? "unsupported";
}

export function palmierParityState(parity?: PalmierParity | null): PalmierParityState {
  const summary = normalizedParitySummary(parity);
  if (!parity) {
    return { fullyEditable: false, label: "Parity unavailable", tone: "missing", summary };
  }
  if (summary.unsupported > 0) {
    return { fullyEditable: false, label: "Unsupported lanes", tone: "blocked", summary };
  }
  const partial = summary.approximate > 0 || summary.baked > 0;
  if (!parity.fullyEditable || partial) {
    return { fullyEditable: false, label: "Partial fidelity", tone: "partial", summary };
  }
  return { fullyEditable: true, label: "Fully editable", tone: "exact", summary };
}

export function palmierMirrorReady(parity?: PalmierParity | null): boolean {
  if (!parity) return false;
  if (typeof parity.mirrorReady === "boolean") return parity.mirrorReady;
  return palmierParityState(parity).fullyEditable;
}

export function palmierParityBlock(parity?: PalmierParity | null): string | null {
  if (!parity) {
    return "Palmier parity report is unavailable — sync is blocked";
  }
  if (palmierMirrorReady(parity)) return null;
  const blocker = parity.mirrorBlockers?.[0]
    ?? parity.findings.find((finding) => finding.blocksSync === true);
  return blocker
    ? `Palmier mirror is unsafe: ${blocker.label} — ${blocker.message}`
    : "This plan cannot be mirrored safely in Palmier";
}

export function palmierParitySummaryText(parity?: PalmierParity | null): string {
  const value = normalizedParitySummary(parity);
  return `${value.exact} exact · ${value.baked} baked · ${value.approximate} approximate · ${value.unsupported} unsupported`;
}

export function palmierParityIssueCount(parity?: PalmierParity | null): number {
  const value = normalizedParitySummary(parity);
  return value.baked + value.approximate + value.unsupported;
}

/** Collapse repeated element rows into user-facing compatibility issues. */
export function groupedParityFindings(
  parity?: PalmierParity | null,
  includeExact = false,
): PalmierParityGroup[] {
  const groups = new Map<string, PalmierParityGroup>();
  for (const finding of parity?.findings ?? []) {
    const fidelity = palmierFindingFidelity(finding);
    if (!includeExact && fidelity === "exact") continue;
    const key = `${fidelity}:${finding.lane}:${finding.message}`;
    const existing = groups.get(key);
    const count = Number.isFinite(finding.count) ? Math.max(1, Number(finding.count)) : 1;
    if (existing) {
      existing.count += count;
      continue;
    }
    groups.set(key, {
      key,
      fidelity,
      lane: finding.lane,
      label: finding.label,
      message: finding.message,
      count,
    });
  }
  return [...groups.values()];
}
