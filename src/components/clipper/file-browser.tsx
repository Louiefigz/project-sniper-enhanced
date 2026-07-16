"use client";

import { useState } from "react";
import type { Source, TranscriptEntry, TranscribeCompleteInfo, VideoMetadata } from "@/lib/clipper/types";
import { derror, dlog } from "@/lib/debug";
import { frameRateToNumber } from "@/lib/clipper/timecode";
import { FilePickerPanel, type PickerGroup } from "./file-picker-panel";
import { TranscriptionPanel } from "./transcription-panel";
import { autoAssign, type PickedFile, type SlotKey } from "./file-picker-utils";
import { useClipperTranscription } from "./use-clipper-transcription";

interface Props {
  onComplete: (
    transcript: TranscriptEntry[],
    source: Source,
    info: TranscribeCompleteInfo,
  ) => void;
}

interface PickerResponse {
  canceled?: boolean;
  error?: string;
  path?: string;
  name?: string;
  files?: PickedFile[];
}

async function readPickerResponse(response: Response): Promise<PickerResponse> {
  const data = await response.json().catch(() => null) as PickerResponse | null;
  if (!response.ok) {
    throw new Error(data?.error || `File picker failed (${response.status})`);
  }
  if (!data) throw new Error("File picker returned an invalid response");
  if (data.error) throw new Error(data.error);
  return data;
}

type Phase = "browse" | "transcribing";

const SLOT_LABELS: Record<SlotKey, string> = {
  hostCam: "Host camera", guestCam: "Guest camera",
  hostMic: "Host mic", guestMic: "Guest mic",
};

export default function FileBrowser({ onComplete }: Props) {
  const [aCamPath, setACamPath] = useState("");
  const [aCamName, setACamName] = useState("");
  const [bCamPath, setBCamPath] = useState("");
  const [bCamName, setBCamName] = useState("");
  const [lav1Path, setLav1Path] = useState("");
  const [lav1Name, setLav1Name] = useState("");
  const [lav2Path, setLav2Path] = useState("");
  const [lav2Name, setLav2Name] = useState("");
  const [pickingSlot, setPickingSlot] = useState<SlotKey | null>(null);
  const [pickingMulti, setPickingMulti] = useState(false);
  const [pickError, setPickError] = useState<string | null>(null);
  const [autoNotice, setAutoNotice] = useState<string | null>(null);
  const [phase, setPhase] = useState<Phase>("browse");
  const transcription = useClipperTranscription();

  const applyToSlot = (slot: SlotKey, file: PickedFile) => {
    if (slot === "hostCam") { setACamPath(file.path); setACamName(file.name); }
    else if (slot === "guestCam") { setBCamPath(file.path); setBCamName(file.name); }
    else if (slot === "hostMic") { setLav1Path(file.path); setLav1Name(file.name); }
    else { setLav2Path(file.path); setLav2Name(file.name); }
  };

  const clearSlot = (slot: SlotKey) => {
    if (slot === "hostCam") { setACamPath(""); setACamName(""); }
    else if (slot === "guestCam") { setBCamPath(""); setBCamName(""); }
    else if (slot === "hostMic") { setLav1Path(""); setLav1Name(""); }
    else { setLav2Path(""); setLav2Name(""); }
  };

  const pickFileFor = async (slot: SlotKey) => {
    if (pickingSlot) return;
    setPickingSlot(slot);
    setPickError(null);
    const audio = slot === "hostMic" || slot === "guestMic";
    try {
      const response = await fetch("/api/clipper/native-pick", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: `Pick ${audio ? "audio" : "video"} for ${SLOT_LABELS[slot]}`, kind: audio ? "audio" : "video" }),
      });
      const data = await readPickerResponse(response);
      if (data.canceled) return;
      if (!data.path || !data.name) throw new Error("File picker did not return a file");
      dlog("clipper:pick", `picked ${SLOT_LABELS[slot]}`, { path: data.path });
      applyToSlot(slot, { path: data.path, name: data.name });
    } catch (error) {
      setPickError(error instanceof Error ? error.message : "Picker failed");
      derror("clipper:pick", "single pick failed", error);
    } finally { setPickingSlot(null); }
  };

  const pickMultiple = async () => {
    if (pickingSlot || pickingMulti) return;
    setPickingMulti(true); setPickError(null); setAutoNotice(null);
    try {
      const response = await fetch("/api/clipper/native-pick", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: "Select all clips — cameras and mics together", kind: "any", multiple: true }),
      });
      const data = await readPickerResponse(response);
      if (data.canceled) return;
      const files = Array.isArray(data.files)
        ? data.files.filter((file) => typeof file?.path === "string" && typeof file?.name === "string")
        : [];
      if (!files.length) throw new Error("File picker did not return any usable files");
      const { assigned, leftovers } = autoAssign(files);
      const order: SlotKey[] = ["hostCam", "guestCam", "hostMic", "guestMic"];
      order.forEach((slot) => { if (assigned[slot]) applyToSlot(slot, assigned[slot]!); });
      const placed = order.filter((slot) => assigned[slot]).map((slot) => SLOT_LABELS[slot]).join(", ");
      const overflow = leftovers.length
        ? ` ${leftovers.length} file${leftovers.length === 1 ? "" : "s"} didn't fit: ${leftovers.map((file) => file.name).join(", ")}.`
        : "";
      setAutoNotice(`${placed ? `Auto-sorted: ${placed}.` : "No camera or audio files recognized."}${overflow}`);
      dlog("clipper:pick", "bulk auto-sort", { picked: files.map((file) => file.name), placed, leftovers });
    } catch (error) {
      setPickError(error instanceof Error ? error.message : "Picker failed");
      derror("clipper:pick", "bulk pick failed", error);
    } finally { setPickingMulti(false); }
  };

  const startTranscription = () => {
    setPhase("transcribing");
    void transcription.start({
      filePath: aCamPath, cameraName: aCamName, guestCameraName: bCamName,
      hostLavPath: lav1Path, guestLavPath: lav2Path,
      hostLavName: lav1Name, guestLavName: lav2Name,
    });
  };

  const buildSource = (media: VideoMetadata, audioMode: "camera" | "lavs", audioChannels: 1 | 2): Source => ({
    angles: bCamPath ? [
      { id: "A", filePath: aCamPath, audioSource: true },
      { id: "B", filePath: bCamPath, audioSource: false },
    ] : [{ id: "A", filePath: aCamPath, audioSource: true }],
    duration: media.duration,
    fps: frameRateToNumber(media.frameRate),
    frameRate: media.frameRate,
    width: media.width,
    height: media.height,
    audioChannels,
    audioMode,
    lav1Path: lav1Path || undefined,
    lav2Path: lav2Path || undefined,
  });

  const finishTranscription = () => {
    const pending = transcription.pendingComplete;
    if (!pending) return;
    const info: TranscribeCompleteInfo = {
      twoSpeakers: pending.lavMode || pending.stereo,
      speakerKind: pending.lavMode ? "guest" : pending.stereo ? "caller" : "diarized",
      audioMode: pending.lavMode ? "lavs" : "camera",
    };
    onComplete(pending.transcript, buildSource(pending.media, info.audioMode, pending.stereo ? 2 : 1), info);
  };

  const groups: PickerGroup[] = [
    { person: "Host", slots: [
      { key: "hostCam", label: "Camera", path: aCamPath, name: aCamName, required: true },
      { key: "hostMic", label: "Lav mic", path: lav1Path, name: lav1Name, required: false },
    ] },
    { person: "Guest", slots: [
      { key: "guestCam", label: "Camera", path: bCamPath, name: bCamName, required: false },
      { key: "guestMic", label: "Lav mic", path: lav2Path, name: lav2Name, required: false },
    ] },
  ];
  const selectedFiles = [
    { key: "hostCam", name: aCamName, audio: false }, { key: "guestCam", name: bCamName, audio: false },
    { key: "hostMic", name: lav1Name, audio: true }, { key: "guestMic", name: lav2Name, audio: true },
  ].filter((file) => file.name);

  return <div className="max-w-2xl mx-auto">
    {phase === "browse" && <FilePickerPanel groups={groups} pickingSlot={pickingSlot}
      pickingMulti={pickingMulti} autoNotice={autoNotice} pickError={pickError}
      lavsReady={!!(lav1Path && lav2Path)} canTranscribe={!!aCamPath}
      onPickMultiple={() => void pickMultiple()} onPickSlot={(slot) => void pickFileFor(slot)}
      onClearSlot={clearSlot} onTranscribe={startTranscription} />}
    {phase === "transcribing" && <TranscriptionPanel {...transcription} selectedFiles={selectedFiles}
      onBack={() => { dlog("clipper:transcribe", "back to file selection"); setPhase("browse"); }}
      onContinue={finishTranscription} />}
  </div>;
}
