import { getFrameTimeFormat } from "@/lib/clipper/timecode";
import { Source } from "@/lib/clipper/types";
import { dlog } from "@/lib/debug";

function escapeXml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

function sanitizeRole(label: string): string {
  return label.replace(/[^a-zA-Z0-9_]/g, "_").replace(/^_+|_+$/g, "") || "track";
}

function fileUrl(absPath: string): string {
  return `file://${absPath.startsWith("/") ? "" : "/"}${escapeXml(absPath)}`;
}

/**
 * Generate FCPXML 1.8 from kept segments.
 *
 * Two audio modes (source.audioMode):
 *   - "camera" (default): the primary angle's own audio is routed via
 *     `source.audioChannels` — 2 = channel-isolated stereo (srcCh=1 →
 *     speakerLabels[0] role, srcCh=2 → speakerLabels[1] role); 1 = single srcCh=1.
 *   - "lavs": the cameras' audio is MUTED and two clean lav files (lav1Path =
 *     Host, lav2Path = Guest) are attached as connected audio-only clips on the
 *     Host/Guest dialogue roles (lanes -1 / -2). Lavs are pre-synced to the
 *     cameras, so their media in-point equals the camera's (segStart).
 *
 * Video layout is unchanged by the audio mode:
 *   A-only (angles.length === 1): flat <asset-clip> spine.
 *   A+B (angles.length === 2): primary cam on the spine; secondary cam as a
 *   lane-1 connected video clip per segment (secondary always silent).
 */
export function generateFCPXML(
  segments: { start: number; end: number; text: string }[],
  source: Source,
  speakerLabels?: [string, string]
): string {
  if (segments.length === 0) {
    throw new Error("generateFCPXML: no segments to export");
  }
  const primary = source.angles.find((a) => a.audioSource);
  if (!primary) {
    throw new Error("generateFCPXML: no angle has audioSource:true");
  }
  const secondary = source.angles.find((a) => !a.audioSource);
  const { duration, frameRate, width, height, audioChannels } = source;
  const fps = frameRate.numerator / frameRate.denominator;

  // Lav mode requires both lav paths; fall back to camera audio if either is missing.
  const lavMode = source.audioMode === "lavs" && !!source.lav1Path && !!source.lav2Path;

  dlog("clipper:xml", "generateFCPXML", {
    segments: segments.length,
    angles: source.angles.length,
    audioMode: source.audioMode ?? "camera",
    lavMode,
    audioChannels: source.audioChannels,
    fps: source.fps,
    duration: source.duration,
    speakerLabels,
  });

  const { frameDuration, frameNum, frameDenom } = getFrameTimeFormat(frameRate);
  const ch1Role = `dialogue.${sanitizeRole(speakerLabels?.[0] ?? "Speaker")}`;
  const ch2Role = `dialogue.${sanitizeRole(speakerLabels?.[1] ?? "Guest")}`;

  const primaryFileName = primary.filePath.split("/").pop() || primary.filePath;
  const trimmedSource = primaryFileName.trim();
  const cleanName = trimmedSource.replace(/\.\w+$/, "").trim() || "export";
  const srcUrl = fileUrl(primary.filePath);

  // Primary clip audio: camera mode routes the camera's own channels; lav mode
  // mutes the camera (the clean audio comes from the connected lav clips below).
  const primaryAudioInner = lavMode
    ? `\n              <adjust-volume amount="-96dB" />`
    : audioChannels === 2
      ? `\n              <audio-channel-source srcCh="1" role="${ch1Role}" />\n              <audio-channel-source srcCh="2" role="${ch2Role}" />`
      : `\n              <audio-channel-source srcCh="1" role="${ch1Role}" />`;

  let offsetFrames = 0;

  const clipElements = segments
    .map((seg) => {
      // floor/ceil = inclusive: never crop a word at a fractional-frame boundary.
      const startFrame = Math.floor(seg.start * fps);
      const endFrame = Math.ceil(seg.end * fps);
      const durFrames = Math.max(1, endFrame - startFrame);

      const offsetStr = `${offsetFrames * frameNum}/${frameDenom}s`;
      const startStr  = `${startFrame  * frameNum}/${frameDenom}s`;
      const durStr    = `${durFrames   * frameNum}/${frameDenom}s`;

      offsetFrames += durFrames;

      // Connected-clip offset is in the parent's source-TC coordinate system,
      // NOT the sequence timeline. For pre-synced A+B (sync handled upstream),
      // B's offset and start are the same value — both reference the same
      // source-TC moment as A's start. If per-cam sync offsets are ever added,
      // this becomes: offset = A.start, start = A.start + B.syncOffset.
      const bClipLine = secondary
        ? `\n              <asset-clip ref="r2" lane="1" offset="${startStr}" start="${startStr}" duration="${durStr}" />`
        : "";

      // Connected lav audio clips (lav mode only). Same source-TC window as the
      // camera since lavs are pre-synced; routed to the Host/Guest dialogue roles.
      const lavLines = lavMode
        ? `\n              <asset-clip ref="rH" lane="-1" offset="${startStr}" name="Host Lav" start="${startStr}" duration="${durStr}" audioRole="${ch1Role}" />\n              <asset-clip ref="rG" lane="-2" offset="${startStr}" name="Guest Lav" start="${startStr}" duration="${durStr}" audioRole="${ch2Role}" />`
        : "";

      return `            <asset-clip ref="r1" offset="${offsetStr}" name="${escapeXml(seg.text.trim().substring(0, 60))}" start="${startStr}" duration="${durStr}" tcFormat="NDF">${primaryAudioInner}${bClipLine}${lavLines}
              <note>${escapeXml(seg.text)}</note>
            </asset-clip>`;
    })
    .join("\n");

  const totalDurStr  = `${offsetFrames * frameNum}/${frameDenom}s`;
  const assetDurFrames = Math.ceil(duration * fps);
  const assetDurStr  = `${assetDurFrames * frameNum}/${frameDenom}s`;

  // In lav mode the primary's own audio is muted, so its channel count is
  // irrelevant; advertise a single channel.
  const primaryAudioChannels = lavMode ? 1 : audioChannels;
  const primaryAssetLine = `    <asset id="r1" name="${escapeXml(cleanName)}" src="${srcUrl}" start="0/${frameDenom}s" duration="${assetDurStr}" hasVideo="1" hasAudio="1" audioSources="${primaryAudioChannels}" audioChannels="${primaryAudioChannels}" audioRate="48000" format="r0" />`;

  let secondaryAssetLine = "";
  if (secondary) {
    const bFileName = secondary.filePath.split("/").pop() || secondary.filePath;
    const bCleanName = bFileName.trim().replace(/\.\w+$/, "").trim();
    const bSrcUrl = fileUrl(secondary.filePath);
    secondaryAssetLine = `\n    <asset id="r2" name="${escapeXml(bCleanName)}" src="${bSrcUrl}" start="0/${frameDenom}s" duration="${assetDurStr}" hasVideo="1" hasAudio="0" format="r0" />`;
  }

  // Lav audio assets (lav mode only): audio-only, one channel each.
  let lavAssetLines = "";
  if (lavMode) {
    const hostName = (source.lav1Path!.split("/").pop() || "Host Lav").replace(/\.\w+$/, "").trim() || "Host Lav";
    const guestName = (source.lav2Path!.split("/").pop() || "Guest Lav").replace(/\.\w+$/, "").trim() || "Guest Lav";
    lavAssetLines =
      `\n    <asset id="rH" name="${escapeXml(hostName)}" src="${fileUrl(source.lav1Path!)}" start="0/${frameDenom}s" duration="${assetDurStr}" hasVideo="0" hasAudio="1" audioSources="1" audioChannels="1" audioRate="48000" />` +
      `\n    <asset id="rG" name="${escapeXml(guestName)}" src="${fileUrl(source.lav2Path!)}" start="0/${frameDenom}s" duration="${assetDurStr}" hasVideo="0" hasAudio="1" audioSources="1" audioChannels="1" audioRate="48000" />`;
  }

  return `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE fcpxml>
<fcpxml version="1.8">
  <resources>
    <format id="r0" frameDuration="${frameDuration}" width="${width}" height="${height}" />
${primaryAssetLine}${secondaryAssetLine}${lavAssetLines}
  </resources>
  <library>
    <event name="${escapeXml(cleanName)}">
      <project name="${escapeXml(cleanName)} - Edited">
        <sequence format="r0" duration="${totalDurStr}" tcStart="0/${frameDenom}s" tcFormat="NDF">
          <spine>
${clipElements}
          </spine>
        </sequence>
      </project>
    </event>
  </library>
</fcpxml>`;
}
