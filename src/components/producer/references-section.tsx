"use client";

import { useState } from "react";
import { BookMarked, Loader2 } from "lucide-react";
import ReferenceCard from "./reference-card";
import ReferenceIntake from "./reference-intake";
import {
  referenceIntent as toReferenceIntent,
  type ReferenceEntry,
  type ReferenceIntent,
} from "./reference-types";
import { useReferences } from "./use-references";

interface Props {
  selectedId?: string | null;
  onSelect: (intent: ReferenceIntent) => void;
  onClearSelection?: () => void;
}

function ReferenceList({ model, selectedId, onSelect, onClearSelection }: {
  model: ReturnType<typeof useReferences>;
  selectedId?: string | null;
  onSelect: (intent: ReferenceIntent) => void;
  onClearSelection?: () => void;
}) {
  if (model.loading) {
    return <p className="flex items-center gap-2 text-xs text-muted-foreground"><Loader2 className="size-3 animate-spin" /> Loading references…</p>;
  }
  if (model.references.length === 0) {
    return <p className="text-xs text-muted-foreground/60">No references yet. Add one above; study starts automatically.</p>;
  }
  return (
    <div className="space-y-3">
      {model.references.map((reference: ReferenceEntry) => (
        <ReferenceCard
          key={reference.id}
          reference={reference}
          activity={model.studies[reference.id]}
          saving={model.savingId === reference.id}
          selected={selectedId === reference.id}
          onStudy={() => void model.study(reference.id)}
          onSave={async (decision) => {
            const updated = await model.saveDecision(reference.id, decision);
            if (updated && selectedId === reference.id) {
              const intent = toReferenceIntent(updated);
              if (intent) onSelect(intent);
              else onClearSelection?.();
            }
            return updated;
          }}
          onUse={onSelect}
          onRemove={() => void model.remove(reference).then((removed) => {
            if (removed && selectedId === reference.id) onClearSelection?.();
          })}
        />
      ))}
    </div>
  );
}

export default function ReferencesSection({ selectedId, onSelect, onClearSelection }: Props) {
  const model = useReferences();
  const [open, setOpen] = useState(false);
  return (
    <section className="mt-8 rounded-lg border border-border bg-card/50" aria-labelledby="references-title">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-start justify-between gap-4 p-4 text-left"
      >
        <span>
          <span id="references-title" className="flex items-center gap-2 text-sm font-semibold text-foreground">
            <BookMarked className="size-4 text-signal" /> Optional: match a reference video
          </span>
          <span className="mt-1 block text-xs leading-relaxed text-muted-foreground">
            Apply pacing and editing mechanics from a polished example. Spoken words, branding, assets, and music are not copied.
          </span>
        </span>
        <span className="text-sm text-signal">{open ? "Close" : "Open"}</span>
      </button>
      {open && <div className="space-y-4 border-t border-border p-4">
        <ReferenceIntake
          adding={model.adding}
          fetching={model.fetching}
          fetchStatus={model.fetchStatus}
          onAddLocal={() => void model.addLocal()}
          onFetch={model.fetchUrl}
        />
        {model.error && (
          <p role="alert" className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
            {model.error}
          </p>
        )}
        <ReferenceList
          model={model}
          selectedId={selectedId}
          onSelect={onSelect}
          onClearSelection={onClearSelection}
        />
      </div>}
    </section>
  );
}
