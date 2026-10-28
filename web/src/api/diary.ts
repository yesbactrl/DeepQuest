import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";

export type DiaryStatus = "done" | "failed" | "private";
export type PartOfDay = "morning" | "day" | "evening";

// Что запись говорит про одну сферу — цель верхнего уровня.
export interface DiarySphere {
  goal_id: number;
  // 1–10; null — из записи не понять.
  score: number | null;
  good: string | null;
  bad: string | null;
}

export interface DiaryEntry {
  id: number;
  text: string;
  created_at: string;
  logical_date: string;
  part_of_day: PartOfDay;
  // Шкалы 1–10; null — из записи не понять.
  mood: number | null;
  energy: number | null;
  drive: number | null;
  emotions: string[];
  factors: string[];
  summary: string | null;
  status: DiaryStatus;
  edited: boolean;
  spheres: DiarySphere[];
  // Запись про другой день, чем написана: задним числом или перенесена.
  backdated: boolean;
}

export interface DiaryDay {
  day: string;
  mood: number | null;
  energy: number | null;
  drive: number | null;
  focus_min: number;
  xp: number;
  entries: DiaryEntry[];
}

export interface Diary {
  days: DiaryDay[];
  norm_min: number;
}

export interface EntryResult {
  entry: DiaryEntry;
  agent_failed: boolean;
  // XP за саму запись.
  xp: number;
}

export interface DiaryEdit {
  text?: string;
  // 0 — убрать оценку.
  mood?: number;
  energy?: number;
  drive?: number;
  emotions?: string[];
  factors?: string[];
  summary?: string;
  // Сферы целиком; score 1–10, 0 — без оценки.
  spheres?: { goal_id: number; score: number; good: string; bad: string }[];
  // Перенести на другой день (YYYY-MM-DD); XP переезжает вместе с записью.
  day?: string;
}

const DIARY_KEY = ["diary"] as const;

export function useDiary(goalId: number | null = null) {
  return useQuery({
    queryKey: [...DIARY_KEY, goalId],
    queryFn: () => api.get<Diary>(goalId === null ? "/diary" : `/diary?goal_id=${goalId}`),
  });
}

function useDiaryMutation<I, O>(mutationFn: (input: I) => Promise<O>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: DIARY_KEY });
      // Запись приносит XP: уровни, персонаж и графики меняются.
      void client.invalidateQueries({ queryKey: ["summary"] });
      void client.invalidateQueries({ queryKey: ["character"] });
      void client.invalidateQueries({ queryKey: ["chart"] });
    },
  });
}

export function useAddEntry() {
  return useDiaryMutation(
    ({ text, analyze, goalIds, day }: { text: string; analyze: boolean; goalIds: number[]; day: string | null }) =>
      // day — задним числом, если запись про прошлый день; null — сегодня.
      api.post<EntryResult>("/diary", { text, analyze, goal_ids: goalIds, day }),
  );
}

export function useEditEntry(id: number) {
  return useDiaryMutation((changes: DiaryEdit) => api.patch<DiaryEntry>(`/diary/${id}`, changes));
}

export function useAnalyzeEntry(id: number) {
  return useDiaryMutation(() => api.post<EntryResult>(`/diary/${id}/analyze`));
}

export function useDeleteEntry(id: number) {
  return useDiaryMutation(() => api.delete(`/diary/${id}`));
}
