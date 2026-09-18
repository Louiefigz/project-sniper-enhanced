import type { CaptionChapterV1, EditPlan } from "@/lib/producer/edit-plan";
import {
  captionTextWithinLimit,
  trimCaptionText,
} from "./caption-text-contract-v1";

const CHAPTER_ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/u;
const WORD_ID = /^w-[0-9a-f]{16}$/u;

function chapter(value: unknown): CaptionChapterV1 {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("caption chapter must be an object");
  }
  const row = value as Record<string, unknown>;
  const expected = ["chapterId", "title", "wordId"];
  const unknown = Object.keys(row).filter((key) => !expected.includes(key));
  if (unknown.length || expected.some((key) => !(key in row))) {
    throw new Error("caption chapter has unknown or missing fields");
  }
  if (typeof row.chapterId !== "string" || !CHAPTER_ID.test(row.chapterId)) {
    throw new Error("caption chapter id is malformed");
  }
  if (!captionTextWithinLimit(row.title, 500)
      || /[\r\n]/u.test(row.title)) {
    throw new Error("caption chapter title is invalid");
  }
  if (typeof row.wordId !== "string" || !WORD_ID.test(row.wordId)) {
    throw new Error("caption chapter word id is malformed");
  }
  return {
    chapterId: row.chapterId,
    title: trimCaptionText(row.title),
    wordId: row.wordId,
  };
}

export function reconcileCaptionChapters(plan: EditPlan): EditPlan {
  if (plan.captionsTrack && plan.chapters?.length) {
    throw new Error(
      "CaptionTrackV1 uses semantic captionChapters, not legacy chapters",
    );
  }
  if (plan.captionChapters === undefined) return plan;
  if (!plan.captionsTrack) {
    throw new Error("captionChapters require captionsTrack");
  }
  if (plan.target?.mode !== "longform") {
    throw new Error("captionChapters are longform-only");
  }
  if (!Array.isArray(plan.captionChapters)) {
    throw new Error("captionChapters must be an array");
  }
  const chapters = plan.captionChapters.map(chapter);
  const chapterIds = chapters.map((row) => row.chapterId);
  const wordIds = chapters.map((row) => row.wordId);
  if (new Set(chapterIds).size !== chapterIds.length) {
    throw new Error("caption chapter ids must be unique");
  }
  if (new Set(wordIds).size !== wordIds.length) {
    throw new Error("caption chapter word anchors must be unique");
  }
  return { ...plan, captionChapters: chapters };
}
