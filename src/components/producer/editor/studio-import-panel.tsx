"use client";

import type { useStudioImport } from "./use-studio-import";

type Import = ReturnType<typeof useStudioImport>;

function describe(value: unknown): string {
  const text = typeof value === "string" ? value : JSON.stringify(value);
  return text.length <= 180 ? text : `${text.slice(0, 177)}…`;
}

/** The operator sees exact supported changes before saving a canonical draft. */
export default function StudioImportPanel({ imported, unavailable }: {
  imported: Import;
  unavailable: boolean;
}) {
  const proposal = imported.proposal;
  const busy = imported.action !== null;
  return (
    <section aria-label="Import Studio changes" className="rounded border border-neutral-700 bg-neutral-950 p-2 text-xs">
      <div className="flex flex-wrap items-center gap-3">
        <button type="button" disabled={busy || unavailable || !!imported.blocked}
          title={imported.blocked ?? "Compare supported Studio edits with the Sniper draft; do not save or render yet"}
          onClick={() => void imported.prepare()}
          className="rounded border border-sky-700 px-3 py-1 text-sky-200 disabled:opacity-40">
          {imported.action === "prepare" ? "Checking Studio changes…" : "Preview Studio changes"}
        </button>
        {proposal?.state === "ready" && (
          <button type="button" disabled={busy || unavailable || !!imported.blocked}
            onClick={() => void imported.apply()}
            className="rounded border border-amber-700 px-3 py-1 text-amber-200 disabled:opacity-40">
            {imported.applying ? "Importing draft…" : "Apply to Sniper draft"}
          </button>
        )}
        {imported.elapsedMs !== null && <span className="text-neutral-400">
          Last import request + reload: {(imported.elapsedMs / 1000).toFixed(1)}s
        </span>}
      </div>
      <div aria-live="polite" className="mt-1 max-h-24 space-y-1 overflow-y-auto">
        {imported.error && <p role="alert" className="text-rose-300">{imported.error}</p>}
        {imported.message && <p className="text-amber-200">{imported.message}</p>}
        {imported.warnings.map((message, index) => <p key={`result-${index}`} className="text-amber-300">{message}</p>)}
        {proposal?.state === "unchanged" && <p>No supported Studio changes to import.</p>}
        {proposal?.blockers.map((message, index) => <p role="alert" key={index} className="text-rose-300">{message}</p>)}
        {proposal?.warnings.map((message, index) => <p key={index} className="text-amber-300">{message}</p>)}
      </div>
      {!!proposal?.changes.length && <ul aria-label="Proposed draft changes" className="mt-2 max-h-28 space-y-1 overflow-y-auto">
        {proposal.changes.map((change, index) => <li key={`${change.graphicId}:${change.field}:${index}`}>
          <span className="text-neutral-400">{change.graphicId} · {change.field}: </span>
          {describe(change.before)} → {describe(change.after)}
        </li>)}
      </ul>}
      <p className="mt-1 text-[11px] text-neutral-400">{proposal?.caveat ||
        "Imports supported timing and text only. Studio files stay intact. The draft still needs rendering and full QC."}</p>
    </section>
  );
}
