"use client";

import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import type { GuidedOpeningStatusV1, GuidedOpeningMediaDescriptorV1 } from "@/lib/producer/contracts/guided-opening-status-v1";
import { openingPlaybackMatches, openingRangeSeconds } from "@/lib/producer/guided-opening-media-client";

type ReadyOpening = Extract<GuidedOpeningStatusV1, { state: "ready-for-review" }>;

/** Only a guarded exact selection reaches this player. Playback never records a decision. */
function OpeningVideo({ media, label, approved }: { media: GuidedOpeningMediaDescriptorV1; label: string; approved: boolean }) {
  const failed = useRef(false);
  const [error, setError] = useState<string | null>(null);
  const [metadataMatched, setMetadataMatched] = useState(false);
  return <div className="space-y-2">
    <video controls playsInline preload="metadata" src={media.url}
      aria-label={`${label}, ${approved ? "operator-approved" : "unapproved"} opening preview`}
      className="max-h-[60vh] w-full rounded bg-black"
      onError={(event) => {
        failed.current = true; event.currentTarget.pause(); setMetadataMatched(false);
        setError("Opening playback failed. Recheck the exact preview; no review or approval was recorded.");
      }}
      onLoadedMetadata={(event) => {
        const video = event.currentTarget;
        const matches = !failed.current && openingPlaybackMatches(media, {
          duration: video.duration, width: video.videoWidth, height: video.videoHeight,
        });
        if (!matches) {
          failed.current = true; video.pause();
          setError("Playback dimensions or duration do not match the selected opening, or playback already failed.");
        }
        setMetadataMatched(matches);
      }} />
    <p role={error ? "alert" : "status"} className={error ? "text-sm text-red-300" : "text-xs text-neutral-400"}>
      {error ?? (metadataMatched
        ? "Playback metadata matches. Loading or playing is not proof that you watched, listened or approved."
        : "Checking playback metadata…")}
    </p>
  </div>;
}

export default function GuidedOpeningPlayer({ opening }: { opening: ReadyOpening }) {
  const [range, setRange] = useState<"core" | "review">("review");
  const media = opening.media[range];
  const label = range === "core" ? "Opening" : "Opening with following context";
  return <div className="space-y-3">
    <p className="text-xs text-amber-200">Last qualified selection: <time dateTime={opening.selectionQualifiedAt}>{opening.selectionQualifiedAt}</time>.
      {" "}This status has not rechecked source bytes. Sources and current checks must be revalidated before any approval.</p>
    <div role="group" aria-label="Opening review range" className="flex flex-wrap gap-2">
      <Button type="button" size="xs" variant={range === "core" ? "default" : "outline"}
        aria-pressed={range === "core"} onClick={() => setRange("core")}>Opening only</Button>
      <Button type="button" size="xs" variant={range === "review" ? "default" : "outline"}
        aria-pressed={range === "review"} onClick={() => setRange("review")}>Opening + context</Button>
    </div>
    <p className="text-xs text-neutral-400">{label} · {openingRangeSeconds(media).toFixed(2)}s · {media.width}×{media.height}
      {" "}· {media.frameRate} fps · frames [{media.startFrame}, {media.endFrameExclusive})</p>
    <OpeningVideo key={`${opening.selectionHash}:${range}:${media.mediaSha256}`} media={media} label={label} approved={opening.openingApproved} />
    <p className="text-sm text-neutral-300">Check the first seconds for a clear hook and deliberate pacing. Then watch the context:
      {" "}the opening should lead into the story, not feel like an unrelated montage.</p>
    <ul className="list-disc space-y-1 pl-5 text-xs text-neutral-400">
      <li>Speech stays intelligible; music and effects do not compete with it.</li>
      <li>Copy remains readable at normal playback speed; movement supports the point.</li>
      <li>Skin, exposure and color stay consistent across cuts. Inspect bright and dark shots.</li>
    </ul>
    <p className="text-xs text-amber-200">Opening approval requires the separate explicit review checklist. Playback alone records no approval.
      {" "}Scoped revision and full-video continuation are still unfinished; this private preview is not a delivery.</p>
  </div>;
}
