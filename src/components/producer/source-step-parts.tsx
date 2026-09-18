import { BookOpenCheck } from "lucide-react";
import type { ReferenceIntent } from "@/lib/producer/intent-presets";
import { referenceExecutionClass } from
  "@/lib/producer/reference-qualification";

export function ReferenceSelection({ intent }: { intent: ReferenceIntent }) {
  const direction = intent.strategy === "extend"
    ? `extend ${intent.targetStyle === "jadenly" ? "Jaden" : intent.targetStyle}`
    : intent.strategy === "new-style"
      ? `new style · ${intent.candidateStyleName}`
      : `${referenceExecutionClass(intent.strategy)} · measured guidance`;
  return (
    <div className="mb-5 flex items-start gap-2 rounded-lg border border-signal/35 bg-signal/5 px-3 py-2.5">
      <BookOpenCheck className="mt-0.5 size-4 shrink-0 text-signal" />
      <div className="min-w-0">
        <p className="truncate text-xs font-medium text-foreground">Reference selected: {intent.title}</p>
        <p className="text-[11px] text-muted-foreground">
          {intent.mode === "short" ? "Short · 9:16" : "Long · 16:9"} · {direction}. This decision is attached to the next ingest.
        </p>
        <p className="text-[10px] text-muted-foreground/60">
          Compatible changes keep the reference. Format, closed-style conflicts, or disabling a required lane clears it. Verified mimic is not currently qualified.
        </p>
      </div>
    </div>
  );
}

interface PickButtonProps {
  icon: React.ReactNode;
  label: string;
  description: string;
  disabled: boolean;
  onClick: () => void;
}

export function PickButton({
  icon,
  label,
  description,
  disabled,
  onClick,
}: PickButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="group flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border bg-card/40 px-6 py-10 transition-colors hover:border-signal/50 hover:bg-card/70 disabled:opacity-60"
    >
      <span className="text-muted-foreground/60 transition-colors group-hover:text-signal">{icon}</span>
      <span className="label text-muted-foreground">{label}</span>
      <span className="max-w-52 text-center text-xs text-muted-foreground/60">{description}</span>
    </button>
  );
}
