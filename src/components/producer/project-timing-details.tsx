import { timingCaveats, timingDuration, timingInputSummary, type RunTimingReport } from "@/lib/producer/run-timing";

/** Persisted measurements stay visible after failure, resume and completion. */
export default function ProjectTimingDetails({ report }: { report?: RunTimingReport | null }) {
  if (!report) return null;
  return (
    <details className="mt-2 border-t border-border/60 pt-2 text-[10px]">
      <summary className="cursor-pointer text-foreground">
        Measured job timing · {timingDuration(report.wallMs)} wall · {report.attempts ?? "unknown"} attempt(s)
      </summary>
      <p className="mt-1">{report.jobStatus} · {report.openSpans} open recorded span(s) · partial instrumentation</p>
      {report.observedActivity && (report.wallMs === null || report.observedActivity.sinceRequestMs > report.wallMs) && (
        <p className="mt-1 text-amber-600 dark:text-amber-400">
          Recorded work extends to {timingDuration(report.observedActivity.sinceRequestMs)} after the job request
          {" "}(observed through {report.observedActivity.throughAt}). The status clock above is older.
          {" "}This is a lower bound, not total active time or confirmed running work.
        </p>
      )}
      {!!report.stages.length && (
        <table className="mt-2 w-full text-left">
          <caption className="mb-1 text-left">Recorded stage work, longest first (overlapping/inclusive)</caption>
          <thead><tr><th>Stage</th><th>Calls</th><th>Time</th><th>Failed / interrupted</th></tr></thead>
          <tbody>{report.stages.map((stage) => (
            <tr key={stage.stage}>
              <td className="break-all pr-2">
                <span className="font-mono">{stage.stage}</span>
                {timingInputSummary(stage).map((label) => (
                  <p key={label} className="text-muted-foreground">{label}</p>
                ))}
              </td>
              <td>{stage.calls}</td><td className="whitespace-nowrap">{timingDuration(stage.inclusiveMs)}</td>
              <td>{stage.failed} / {stage.interrupted}</td>
            </tr>
          ))}</tbody>
        </table>
      )}
      <ul className="mt-2 list-disc space-y-1 pl-4 text-muted-foreground">
        {timingCaveats(report).map((note) => <li key={note}>{note}</li>)}
      </ul>
    </details>
  );
}
