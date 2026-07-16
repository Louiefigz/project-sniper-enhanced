interface Props {
  reason: string | null;
  palmierPrimary?: boolean;
}

export default function EditorLockOverlay({ reason, palmierPrimary = false }: Props) {
  if (!reason) return null;
  return (
    <div className="pointer-events-none absolute inset-x-0 top-12 z-40 flex justify-center p-3">
      <div role="status" aria-live="polite" className="max-w-2xl rounded-lg border border-amber-500/30 bg-neutral-900/95 px-4 py-3 text-center shadow-2xl backdrop-blur-sm">
        <div className="text-sm font-semibold text-amber-300">
          {palmierPrimary ? "Palmier is the editor" : "Read-only while Sniper works"}
        </div>
        <p className="mt-1 text-xs leading-relaxed text-neutral-300">{reason}</p>
        <p className="mt-1 text-[10px] text-neutral-500">
          {palmierPrimary
            ? "Playback, seeking, Palmier review, Ask AI, and candidate QC remain available."
            : "Playback, seeking, and project progress remain available. Editing unlocks automatically."}
        </p>
      </div>
    </div>
  );
}
