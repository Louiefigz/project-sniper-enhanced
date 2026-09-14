"use client";

import { AUTOMATIC_SHORT_DIRECTION, SHORT_DIRECTION_SUGGESTIONS, shortMediaPolicy,
  type ShortDirectionRequest } from "@/lib/producer/short-direction";

interface Props {
  value?: ShortDirectionRequest;
  disabled?: boolean;
  onChange: (value: ShortDirectionRequest) => void;
}

/** A request to the edit brain, distinct from the amount of editing. */
export function ShortDirectionControl({ value, disabled, onChange }: Props) {
  const current = value ?? AUTOMATIC_SHORT_DIRECTION;
  return <fieldset disabled={disabled} className="mt-4 space-y-2 rounded-md border border-border p-3">
    <legend className="px-1 text-sm font-medium">What kind of Short?</legend>
    <div className="flex gap-4 text-sm">
      <label><input type="radio" name="short-direction" checked={current.selection === "auto"}
        onChange={() => onChange({ selection: "auto", supportingVideo: current.supportingVideo,
          ...(current.mediaPolicy ? { mediaPolicy: current.mediaPolicy } : {}) })} /> Choose for me</label>
      <label><input type="radio" name="short-direction" checked={current.selection === "requested"}
        onChange={() => onChange({ selection: "requested", request: SHORT_DIRECTION_SUGGESTIONS[0],
          supportingVideo: current.supportingVideo,
          ...(current.mediaPolicy ? { mediaPolicy: current.mediaPolicy } : {}) })} /> I have a style in mind</label>
    </div>
    {current.selection === "requested" && <RequestedDirection current={current} onChange={onChange} />}
    <p className="text-xs text-muted-foreground">The strategy uses the message, footage and reference library
      to choose the framing and visuals before building.</p>
    <MediaSources current={current} onChange={onChange} />
  </fieldset>;
}

function MediaSources({ current, onChange }: { current: ShortDirectionRequest; onChange: Props["onChange"] }) {
  const policy = shortMediaPolicy(current);
  return <div className="space-y-2">
    <label className="flex items-start gap-2 text-sm">
      <input type="checkbox" checked={policy.placement === "auto"} onChange={event => onChange({ ...current,
        supportingVideo: event.target.checked ? "source-first" : "off",
        mediaPolicy: { ...policy, placement: event.target.checked ? "auto" : "off" } })} />
      <span>Use supporting visuals when they help explain the point
        <span className="block text-xs text-muted-foreground">Look in my footage first. Photos, logos and clips follow the same source choice.</span>
      </span>
    </label>
    <label className="block text-sm">Where can supporting visuals come from?
      <select className="mt-1 w-full rounded border border-border bg-background p-2" value={policy.sources}
        disabled={policy.placement === "off"} onChange={event => onChange({ ...current,
          mediaPolicy: { ...policy, sources: event.target.value as typeof policy.sources } })}>
        <option value="provided-only">Only the files I supplied</option>
        <option value="local-only">My files and the existing local library</option>
        <option value="public-web">My files, local library and public websites</option>
      </select>
    </label>
  </div>;
}

function RequestedDirection({ current, onChange }: {
  current: ShortDirectionRequest; onChange: Props["onChange"];
}) {
  return <div className="space-y-2">
    <label className="block text-xs">Describe the style or name a reference
      <input className="mt-1 w-full rounded border border-border bg-background p-2 text-sm"
        maxLength={800} value={current.request ?? ""} placeholder="For example: Nate Herk, show one offer improving step by step"
        onChange={(event) => onChange({ ...current, request: event.target.value })} />
    </label>
    <div className="flex flex-wrap gap-1.5">{SHORT_DIRECTION_SUGGESTIONS.map((request) =>
      <button type="button" key={request} className="rounded-full border border-border px-2 py-1 text-xs"
        aria-pressed={current.request === request} onClick={() => onChange({ ...current, request })}>
        {request.split(" — ")[0]}</button>)}</div>
  </div>;
}
