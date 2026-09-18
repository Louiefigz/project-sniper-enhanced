"use client";

import { useCallback, useState, type Dispatch, type SetStateAction } from "react";
import { dlog } from "@/lib/debug";
import {
  autoAssign,
  EMPTY_SLOTS,
  type FileSlots,
  type PickedFile,
  responseError,
  SLOT_LABELS,
  type SlotKey,
} from "@/lib/segmenter/file-browser-helpers";

interface PickerResponse {
  canceled?: boolean;
  error?: string;
  path?: string;
  name?: string;
  files?: PickedFile[];
}

async function requestPicker(body: Record<string, unknown>): Promise<PickerResponse> {
  const response = await fetch("/api/segmenter/pick-file", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw await responseError(response, "File picker");
  return response.json() as Promise<PickerResponse>;
}

function assignmentNotice(
  assigned: Partial<Record<SlotKey, PickedFile>>,
  leftovers: PickedFile[],
): string {
  const order: SlotKey[] = ["a", "b", "c", "lav1", "lav2"];
  const placed = order.filter((slot) => assigned[slot]).map((slot) => SLOT_LABELS[slot]).join(", ");
  const notice = placed ? `Auto-sorted: ${placed}.` : "No camera or audio files recognized.";
  if (leftovers.length === 0) return notice;
  const count = `${leftovers.length} file${leftovers.length === 1 ? "" : "s"}`;
  return `${notice} ${count} didn't fit (only 3 cameras + 2 lavs): ${leftovers.map((file) => file.name).join(", ")}.`;
}

function pickerError(error: unknown): string {
  return error instanceof Error ? error.message : "Picker failed";
}

interface SelectionState {
  slots: FileSlots;
  setSlots: Dispatch<SetStateAction<FileSlots>>;
  pickingSlot: SlotKey | null;
  setPickingSlot: Dispatch<SetStateAction<SlotKey | null>>;
  pickingMulti: boolean;
  setPickingMulti: Dispatch<SetStateAction<boolean>>;
  pickError: string | null;
  setPickError: Dispatch<SetStateAction<string | null>>;
  autoNotice: string | null;
  setAutoNotice: Dispatch<SetStateAction<string | null>>;
  applyToSlot: (slot: SlotKey, file: PickedFile | null) => void;
}

function useSelectionState(): SelectionState {
  const [slots, setSlots] = useState<FileSlots>({ ...EMPTY_SLOTS });
  const [pickingSlot, setPickingSlot] = useState<SlotKey | null>(null);
  const [pickingMulti, setPickingMulti] = useState(false);
  const [pickError, setPickError] = useState<string | null>(null);
  const [autoNotice, setAutoNotice] = useState<string | null>(null);
  const applyToSlot = useCallback((slot: SlotKey, file: PickedFile | null) => {
    setSlots((current) => ({ ...current, [slot]: file }));
  }, []);
  return {
    slots, setSlots, pickingSlot, setPickingSlot, pickingMulti,
    setPickingMulti, pickError, setPickError, autoNotice, setAutoNotice, applyToSlot,
  };
}

function useSinglePicker(state: SelectionState) {
  return useCallback(async (slot: SlotKey) => {
    if (state.pickingSlot) return;
    state.setPickingSlot(slot);
    state.setPickError(null);
    const isAudio = slot === "lav1" || slot === "lav2";
    try {
      const data = await requestPicker({
        prompt: `Pick ${isAudio ? "audio" : "video"} for ${SLOT_LABELS[slot]}`,
        kind: isAudio ? "audio" : "video",
      });
      if (data.canceled) return;
      if (data.error) throw new Error(data.error);
      if (!data.path || !data.name) throw new Error("The picker returned an invalid file.");
      state.applyToSlot(slot, { path: data.path, name: data.name });
      dlog("segmenter:browse", `picked ${SLOT_LABELS[slot]}`, data);
    } catch (error: unknown) {
      state.setPickError(pickerError(error));
    } finally {
      state.setPickingSlot(null);
    }
  }, [state]);
}

function useMultiPicker(state: SelectionState) {
  return useCallback(async () => {
    if (state.pickingSlot || state.pickingMulti) return;
    state.setPickingMulti(true);
    state.setPickError(null);
    state.setAutoNotice(null);
    try {
      const data = await requestPicker({
        prompt: "Select all clips — cameras and audio together",
        kind: "any",
        multiple: true,
      });
      if (data.canceled) return;
      if (data.error) throw new Error(data.error);
      const files = Array.isArray(data.files) ? data.files : [];
      if (files.length === 0) return;
      const { assigned, leftovers } = autoAssign(files);
      state.setSlots((current) => ({ ...current, ...assigned }));
      state.setAutoNotice(assignmentNotice(assigned, leftovers));
      dlog("segmenter:browse", "auto-sort assignment", { assigned, leftovers });
    } catch (error: unknown) {
      state.setPickError(pickerError(error));
    } finally {
      state.setPickingMulti(false);
    }
  }, [state]);
}

export function useFileSelection() {
  const state = useSelectionState();
  const pickFileFor = useSinglePicker(state);
  const pickMultiple = useMultiPicker(state);
  return {
    slots: state.slots,
    pickingSlot: state.pickingSlot,
    pickingMulti: state.pickingMulti,
    pickError: state.pickError,
    autoNotice: state.autoNotice,
    pickFileFor,
    pickMultiple,
    clearSlot: (slot: SlotKey) => state.applyToSlot(slot, null),
  };
}
