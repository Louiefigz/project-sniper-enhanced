import type { ColorGroup, ColorJob } from "@/lib/producer/color-diagnostic";
function Group({ group }: { group: ColorGroup }) {
  return <details className="rounded border border-neutral-800 p-2" open>
    <summary className="cursor-pointer text-neutral-200">{group.sourceId}: {group.sampledFrames}/{group.observations.length} sampled · {group.intent}</summary>
    <p className="mt-1 text-[10px] text-neutral-400">Declarations for this result: {group.context.sourceProfile} · transform history {group.context.historyState} · lighting {group.intent}.</p>
    <dl className="mt-2 grid grid-cols-2 gap-1 text-[10px]">
      {["range", "primaries", "transfer", "matrix", "pixelFormat"].map(key => <div key={key} className="contents"><dt className="text-neutral-500">{key}</dt><dd className="break-all text-neutral-300">{String(group.metadata[key] ?? "unknown")}</dd></div>)}
    </dl>
    <p className="mt-2 text-neutral-400">Encoded luma mean range: {group.minimumMeanLuma?.toFixed(1) ?? "—"}–{group.maximumMeanLuma?.toFixed(1) ?? "—"} / 255.</p>
    <p className="text-[10px] text-neutral-500">Reduced-frame limit occupancy: black {group.worstNominalBlackFraction === null ? "—" : `${(group.worstNominalBlackFraction * 100).toFixed(1)}%`}, white {group.worstNominalWhiteFraction === null ? "—" : `${(group.worstNominalWhiteFraction * 100).toFixed(1)}%`}. Not proof of lost sensor detail.</p>
    <details className="mt-2"><summary className="cursor-pointer text-neutral-400">Retained intervals and sampled times</summary>
      <p className="mt-1 text-neutral-500">{group.retainedIntervals.map(row => `${row.sourceStart.toFixed(2)}–${row.sourceEnd.toFixed(2)}s`).join(", ")}</p>
      {group.observations.map((row, i) => <p key={i} className="text-neutral-500">{row.requestedTime.toFixed(2)}s → {row.actualSourceTime?.toFixed(2) ?? "—"}s · {row.status}{row.error ? ` (${row.error})` : ""}</p>)}
      <p className="mt-1 text-amber-200">Unsampled retained intervals: {group.unsampledIntervalIndices.length ? group.unsampledIntervalIndices.map(i => i + 1).join(", ") : "none at this sampling resolution"}. Not exhaustive frame/shot coverage.</p>
    </details>
    {group.screeningOffsets.map((offset, i) => <p key={i} className="mt-2 rounded bg-amber-900/20 p-2 text-amber-200">Unreviewed luma screening: {offset > 0 ? "+" : ""}{offset.toFixed(4)}. Not exposure stops, not a grade, and cannot be applied to the plan. Requires operator image comparison.</p>)}
    {!group.screeningOffsets.length && <p className="mt-2 text-neutral-400">No numeric correction suggested. This is not a quality pass.</p>}
    <ul className="mt-2 list-disc space-y-1 pl-4 text-[10px] text-amber-200">{group.warnings.map((warning, i) => <li key={i}>{warning}</li>)}</ul>
  </details>;
}
export default function ColorResult({ job, contextsCurrent = true }: { job: ColorJob; contextsCurrent?: boolean }) {
  return <section aria-label="Private color diagnostic result" className="space-y-3 text-xs">
    <p className="text-neutral-200">{job.state} · {(job.elapsedMs / 1000).toFixed(1)}s elapsed · no queue</p>
    <p className="text-[10px] text-neutral-500">Private / unreviewed. No grade, render, or approval. Cleanup {job.cleanupVerified ? "verified" : "not yet verified"}.</p>
    {!job.parentsCurrent && <p role="alert" className="text-amber-200">Saved inputs changed. These observations are historical and must not guide a new correction without rerunning.</p>}
    {!!job.groups.length && !contextsCurrent && <p role="alert" className="text-amber-200">The controls differ from this result&apos;s saved declarations. These observations still belong to the previous check; run a new check to evaluate the edited declarations.</p>}
    {job.error && <p role="alert" className="text-amber-200">{job.error}</p>}
    {job.groups.map(group => <Group key={`${group.sourceId}:${group.groupId}`} group={group} />)}
    <details><summary className="cursor-pointer text-neutral-400">Timing and scope</summary>
      <p className="mt-1 text-neutral-500">120s work budget; cleanup has separate bounded headroom. Elapsed includes the API attempt, not user thinking time. No before/after visual comparison or final/proxy color parity is qualified.</p>
      {job.timings.map(row => <p key={row.sourceId} className="mt-1 break-words text-neutral-500">{row.sourceId}: {row.elapsedMs}ms worker envelope, {row.workerMs ?? "—"}ms decoding. {row.ffmpeg}</p>)}
      <ul className="mt-2 list-disc space-y-1 pl-4 text-neutral-500">{job.caveats.map((item, i) => <li key={i}>{item}</li>)}</ul>
    </details>
  </section>;
}
