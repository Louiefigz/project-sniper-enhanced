"use client";

import {
  groupedParityFindings,
  palmierMirrorReady,
  palmierFindingFidelity,
  palmierParityIssueCount,
  palmierParityState,
  type PalmierFidelity,
  type PalmierParity,
  type PalmierParityFinding,
  type PalmierParityGroup,
} from "./palmier-parity";

const FIDELITY_COPY: Record<PalmierFidelity, { label: string; cls: string }> = {
  exact: { label: "Native + editable", cls: "text-emerald-300" },
  baked: { label: "Exact pixels · flattened", cls: "text-sky-300" },
  approximate: { label: "Exact pixels · limited controls", cls: "text-amber-300" },
  unsupported: { label: "Exact pixels · no native control", cls: "text-amber-300" },
};

interface Props {
  parity?: PalmierParity | null;
  notes?: string[];
  blocked?: string;
  onClose: () => void;
}

export default function PalmierParityReport({
  parity,
  notes = [],
  blocked,
  onClose,
}: Props) {
  const state = palmierParityState(parity);
  const issues = groupedParityFindings(parity);
  const issueCount = palmierParityIssueCount(parity);
  const exact = state.summary.exact;
  const ready = palmierMirrorReady(parity);
  const title = ready ? "Visual mirror ready" : "Palmier mirror blocked";
  const description = ready
    ? issueCount
      ? `The approved Sniper pixels and audio mirror exactly. ${issueCount} item${issueCount === 1 ? " has" : "s have"} limited native controls in Palmier.`
      : `The approved mirror is exact and all ${exact} reported entries have native controls.`
    : "The plan is malformed or contains unknown visual state, so no mirror will be sent.";

  return (
    <section
      aria-label="Palmier compatibility check"
      className="max-h-[40vh] overflow-y-auto border-t border-neutral-800 bg-neutral-950/95 px-4 py-3 text-[11px]"
    >
      <ReportHeader
        title={title}
        description={description}
        ready={ready}
        onClose={onClose}
      />
      <ReportBody
        parity={parity}
        ready={ready}
        issues={issues}
        exact={exact}
        notes={notes}
        blocked={blocked}
      />
    </section>
  );
}

function ReportHeader({
  title,
  description,
  ready,
  onClose,
}: { title: string; description: string; ready: boolean; onClose: () => void }) {
  return (
    <div className="sticky top-0 z-10 flex items-start gap-3 bg-neutral-950/95 pb-2">
      <div>
        <p className={ready ? "font-medium text-emerald-300" : "font-medium text-red-300"}>{title}</p>
        <p className="mt-0.5 text-neutral-400">{description}</p>
      </div>
      <button
        type="button"
        onClick={onClose}
        className="ml-auto shrink-0 rounded border border-neutral-800 px-2 py-0.5 text-neutral-400 hover:text-neutral-200"
      >
        Close check
      </button>
    </div>
  );
}

interface BodyProps {
  parity?: PalmierParity | null;
  ready: boolean;
  issues: PalmierParityGroup[];
  exact: number;
  notes: string[];
  blocked?: string;
}

function ReportBody({ parity, ready, issues, exact, notes, blocked }: BodyProps) {
  return (
    <>
      {!parity && <MissingReport />}
      {blocked && !ready && <PrimaryBlocker message={blocked} />}
      {issues.length > 0 && <IssueGroups groups={issues} />}
      {ready && <ReadyProof />}
      {parity && (parity.findings?.length ?? 0) > 0 && (
        <details className="mt-2 rounded border border-neutral-800 px-2 py-1.5">
          <summary className="cursor-pointer text-neutral-400">
            Show all {parity.findings.length} inspected elements · {exact} already compatible
          </summary>
          <FindingRows findings={parity.findings} />
        </details>
      )}
      {notes.length > 0 && <TranslationNotes notes={notes} />}
    </>
  );
}

function PrimaryBlocker({ message }: { message: string }) {
  return (
    <p className="mb-2 rounded border border-red-900/60 bg-red-950/20 px-2 py-1.5 text-red-200">
      <span className="font-medium">First blocker:</span> {message}
    </p>
  );
}

function ReadyProof() {
  return (
    <p className="rounded border border-emerald-900/60 bg-emerald-950/20 px-2 py-1.5 text-emerald-200">
      Palmier receives one verified master clip, byte-identical to the approved Sniper video and audio. Separate source, graphic, caption, music, and other component assets are preserved in the library when importable; the labels below describe what remains natively editable.
    </p>
  );
}

function TranslationNotes({ notes }: { notes: string[] }) {
  return (
    <details className="mt-2 rounded border border-amber-900/50 px-2 py-1.5 text-amber-200/80">
      <summary className="cursor-pointer text-amber-300">Additional translation notes</summary>
      <ul className="mt-1 list-disc space-y-0.5 pl-4">
        {notes.map((note, index) => <li key={`${index}:${note}`}>{note}</li>)}
      </ul>
    </details>
  );
}

function MissingReport() {
  return (
    <p className="rounded border border-red-900/70 bg-red-950/20 px-2 py-1.5 text-red-300">
      Handoff blocked. Compatibility could not be verified, so nothing was sent.
    </p>
  );
}

function IssueGroups({ groups }: { groups: PalmierParityGroup[] }) {
  return (
    <div>
      <p className="mb-1.5 font-medium text-neutral-300">Palmier editing capabilities</p>
      <ul className="space-y-1.5">
        {groups.map((group) => {
          const copy = FIDELITY_COPY[group.fidelity];
          return (
            <li key={group.key} className="rounded border border-neutral-800 bg-neutral-900/40 px-2 py-1.5">
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-neutral-200">{group.count > 1 ? `${group.lane} · ${group.count} items` : group.label}</span>
                <span className="text-neutral-600">—</span>
                <span className={copy.cls}>{copy.label}</span>
              </div>
              <p className="mt-0.5 text-neutral-500">{group.message}</p>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function FindingRows({ findings }: { findings: PalmierParityFinding[] }) {
  return (
    <ul className="mt-2 space-y-1">
      {findings.map((finding) => {
        const fidelity = palmierFindingFidelity(finding);
        const copy = FIDELITY_COPY[fidelity];
        return (
          <li key={finding.id} className="flex flex-wrap gap-x-1.5 text-neutral-500">
            <span className={copy.cls}>{copy.label}</span>
            <span>{finding.label}</span>
            <span className="text-neutral-700">· {finding.lane}</span>
          </li>
        );
      })}
    </ul>
  );
}
