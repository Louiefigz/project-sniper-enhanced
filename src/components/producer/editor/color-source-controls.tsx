"use client";
import type { ColorContext, ColorProfile, ColorSource, LightingIntent } from "@/lib/producer/color-diagnostic";
const INPUT = "mt-1 w-full rounded border border-neutral-700 bg-neutral-900 p-1.5 text-xs text-neutral-100";
interface Props { source: ColorSource; value: ColorContext; onChange: (value: ColorContext) => void; disabled: boolean }
export default function ColorSourceControls({ source, value, onChange, disabled }: Props) {
  const group = value.lightingGroups[0];
  const update = (patch: Partial<ColorContext>) => onChange({ ...value, ...patch });
  const history = value.historyState === "unknown" ? "unknown" : value.transformHistory.length ? "transformed" : "none";
  return <fieldset disabled={disabled} className="space-y-3 rounded border border-neutral-800 p-3 text-xs">
    <legend className="max-w-full truncate px-1 text-neutral-200" title={source.label}>{source.id} · {source.duration.toFixed(1)}s</legend>
    <p className="break-words text-neutral-500">{source.label}</p>
    <label className="block text-neutral-400">Source profile
      <select aria-label={`${source.id} source profile`} className={INPUT} value={value.sourceProfile}
        onChange={event => update({ sourceProfile: event.target.value as ColorProfile })}>
        <option value="unknown">Unknown — do not infer</option><option value="bt709-sdr">Known SDR BT.709</option>
        <option value="log">Camera Log</option><option value="hdr">HDR</option>
      </select>
    </label>
    <label className="block text-neutral-400">Camera / picture profile, if known
      <input className={INPUT} maxLength={200} value={value.cameraProfile ?? ""} placeholder="Optional; not guessed from tags"
        onChange={event => update({ cameraProfile: event.target.value.trim() || null })} />
    </label>
    <label className="block text-neutral-400">Prior color transforms
      <select aria-label={`${source.id} transform history`} className={INPUT} value={history} onChange={event => {
        if (event.target.value === "unknown") update({ historyState: "unknown" });
        else update({ historyState: "known", transformHistory: event.target.value === "none" ? [] : ["Describe the prior transform"] });
      }}>
        <option value="unknown">Unknown</option><option value="none">Known: no prior transform</option><option value="transformed">Known: already transformed</option>
      </select>
    </label>
    {history === "transformed" && <label className="block text-neutral-400">Prior transform notes
      <textarea className={INPUT} rows={2} maxLength={500} value={value.transformHistory.join("; ")}
        onChange={event => update({ transformHistory: [event.target.value || "Unspecified prior transform"] })} />
    </label>}
    <label className="block text-neutral-400">Whole-source lighting intent
      <select aria-label={`${source.id} lighting intent`} className={INPUT} value={group.intent}
        onChange={event => update({ lightingGroups: [{ ...group, intent: event.target.value as LightingIntent }] })}>
        <option value="unknown">Unknown / mixed lighting</option><option value="neutral">Intended neutral lighting</option>
        <option value="dark">Intentionally dark</option><option value="colored">Intentionally colored</option>
      </select>
    </label>
    <label className="block text-neutral-400">Lighting notes
      <textarea className={INPUT} rows={2} maxLength={500} placeholder="Intent, lighting changes, or uncertainty"
        value={group.description} onChange={event => update({ lightingGroups: [{ ...group, description: event.target.value }] })} />
    </label>
    <p className="text-[10px] text-neutral-500">One declared group, 0–{source.duration.toFixed(1)}s. If lighting changes, choose unknown/mixed. Shot-specific groups and visual comparisons are not available here yet.</p>
  </fieldset>;
}
