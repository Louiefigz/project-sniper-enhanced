export const STUDIO_CAVEAT = "Graphics timing and copy review only. Native font-family and motion-path changes are not supported. Studio is not the approved final; placement, footage, audio and color may differ. Render updated video in Sniper for full QC.";

export interface StudioStatus {
  ok: true;
  state: "ready" | "not-open" | "blocked";
  url: string | null;
  canOpen: boolean;
  pendingEdits: string[];
  blockers: string[];
  caveat: string;
  reused?: boolean;
}

export interface StudioInspection {
  parent: string;
  viewExists: boolean;
  viewCurrent: boolean;
  pendingEdits: string[];
  blockers: string[];
}

export interface StudioRecord {
  pid: number;
  port: number;
  startedAt: string;
}

export class StudioError extends Error {
  constructor(message: string, readonly status = 409,
    readonly code = "STUDIO_UNAVAILABLE") {
    super(message);
  }
}
