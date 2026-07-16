export type SlotKey = "hostCam" | "guestCam" | "hostMic" | "guestMic";
export type PickedFile = { path: string; name: string };

const VIDEO_EXT = /\.(mp4|mov|m4v|avi|mkv|mpg|mpeg|webm|wmv|flv)$/i;
const AUDIO_EXT = /\.(wav|mp3|m4a|aac|flac|ogg|opus|aif|aiff|caf|wma)$/i;

function personHintScore(name: string): number {
  const normalized = name.toLowerCase();
  if (/\bhost\b|\bh[\s_-]?cam\b|\bh[\s_-]?mic\b/.test(normalized)) return 0;
  if (/\bguest\b|\bg[\s_-]?cam\b|\bg[\s_-]?mic\b/.test(normalized)) return 1;
  return 0.5;
}

export function autoAssign(files: PickedFile[]): {
  assigned: Partial<Record<SlotKey, PickedFile>>;
  leftovers: PickedFile[];
} {
  const videos = files.filter((file) => VIDEO_EXT.test(file.name));
  const audios = files.filter((file) => AUDIO_EXT.test(file.name));
  const unknown = files.filter((file) => !VIDEO_EXT.test(file.name) && !AUDIO_EXT.test(file.name));
  videos.sort((a, b) => personHintScore(a.name) - personHintScore(b.name) || a.name.localeCompare(b.name));
  audios.sort((a, b) => personHintScore(a.name) - personHintScore(b.name) || a.name.localeCompare(b.name));

  const assigned: Partial<Record<SlotKey, PickedFile>> = {};
  const cameraSlots: SlotKey[] = ["hostCam", "guestCam"];
  const microphoneSlots: SlotKey[] = ["hostMic", "guestMic"];
  videos.slice(0, 2).forEach((file, index) => (assigned[cameraSlots[index]] = file));
  audios.slice(0, 2).forEach((file, index) => (assigned[microphoneSlots[index]] = file));
  return { assigned, leftovers: [...videos.slice(2), ...audios.slice(2), ...unknown] };
}
