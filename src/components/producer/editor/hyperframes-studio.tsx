"use client";

import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { useStudioReview } from "./use-studio-review";
import { useStudioImport } from "./use-studio-import";
import StudioImportPanel from "./studio-import-panel";

interface Props {
  dir: string;
  dirty: boolean;
  blocked?: string | null;
  onDraftInvalidated?: () => void;
  onDraftChanged?: () => Promise<boolean>;
}
type Studio = ReturnType<typeof useStudioReview>;
type Imported = ReturnType<typeof useStudioImport>;
const CAVEAT = "Graphics timing and copy review only. Studio is not the approved final; placement, footage, audio and color may differ. Render updated video in Sniper for full QC.";

function StudioStatus({ studio }: { studio: Studio }) {
  return (
    <div className="space-y-1 text-xs" aria-live="polite">
      {studio.loading && <p>Preparing the HyperFrames review surface…</p>}
      {studio.error && <p role="alert" className="text-rose-400">{studio.error}</p>}
      {studio.status?.blockers.map((reason) => <p key={reason} className="text-amber-300">{reason}</p>)}
      {!!studio.status?.pendingEdits.length && (
        <p className="text-amber-300">Studio differs from the original review build. Your edits are preserved. Preview Studio changes to check which edits still need importing.</p>
      )}
      {studio.elapsedMs !== null && (
        <p className="text-neutral-400">Last review request: {(studio.elapsedMs / 1000).toFixed(1)}s
          {studio.status?.reused ? " · existing session reused" : ""}</p>
      )}
    </div>
  );
}

function StudioDialog({ studio, imported }: { studio: Studio; imported: Imported }) {
  const url = studio.status?.state === "ready" ? studio.status.url : null;
  return (
    <Dialog open={studio.open} onOpenChange={(open) => {
      if (!open && !imported.applying) { imported.cancelPrepare(); studio.close(); }
    }}>
      <DialogContent showCloseButton={!imported.applying}
        className="flex h-[94vh] w-[96vw] max-w-none flex-col gap-2 p-4 sm:max-w-none">
        <DialogTitle>HyperFrames Studio review</DialogTitle>
        <DialogDescription className="pr-8 text-xs">{studio.status?.caveat || CAVEAT}</DialogDescription>
        <div className="flex items-center justify-between gap-3">
          <StudioStatus studio={studio} />
          <button type="button" disabled={studio.loading || imported.action !== null} onClick={() => void studio.request("status")}
            className="shrink-0 rounded border border-neutral-700 px-3 py-1 text-xs disabled:opacity-50">
            Check review status
          </button>
        </div>
        {url && !studio.error && (
          <iframe title="HyperFrames Studio timeline" src={url} allow="autoplay; fullscreen" inert={imported.applying}
            className={`min-h-0 w-full flex-1 rounded border border-neutral-800 bg-black ${imported.applying ? "pointer-events-none opacity-60" : ""}`} />
        )}
        <StudioImportPanel imported={imported} unavailable={studio.loading || !url} />
        <p className="text-[11px] text-amber-200">Closing preserves Studio edits. Studio export/render is blocked here; return to Sniper for final rendering and QC.</p>
      </DialogContent>
    </Dialog>
  );
}

/** Open the real Studio player without equating its projection with delivery. */
export default function HyperframesStudio({ dir, dirty, blocked, onDraftInvalidated, onDraftChanged }: Props) {
  const studio = useStudioReview(dir);
  const reason = blocked ?? (dirty ? "Save your timeline before opening HyperFrames Studio." : null);
  const imported = useStudioImport({ dir, blocked: reason,
    invalidatePreview: onDraftInvalidated, reloadDraft: onDraftChanged });
  return (
    <>
      <button type="button" disabled={!!reason || studio.loading}
        onClick={() => void studio.request("open")} title={reason ?? "Review graphics timing and copy in HyperFrames Studio"}
        className="whitespace-nowrap rounded-md border border-sky-700 px-3 py-1 text-xs text-sky-200 enabled:hover:bg-sky-950 disabled:cursor-not-allowed disabled:opacity-50">
        HyperFrames Studio
      </button>
      <StudioDialog studio={studio} imported={imported} />
    </>
  );
}
