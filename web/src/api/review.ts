import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";

export type PeriodKind = "week" | "month";
export type DayStatus = "met" | "missed" | "frozen" | "paused";

export interface Totals {
  xp: number;
  minutes: number;
  done_tasks: number;
  entries: number;
  // Закрытые дни: норма выполнена / все, кроме паузы.
  norm_met: number;
  norm_days: number;
}

export interface State {
  mood: number | null;
  energy: number | null;
  drive: number | null;
}

export interface SphereReview {
  goal_id: number;
  title: string;
  xp: number;
  prev_xp: number;
  minutes: number;
  done_tasks: number;
  // Средняя оценка сферы в дневнике, 1–10.
  score: number | null;
  prev_score: number | null;
  mentions: number;
  good: string[];
  bad: string[];
}

export interface DayPoint {
  day: string;
  // Среднее состояние дня 1–10; null — записей нет.
  state: number | null;
  focus_min: number;
  xp: number;
  status: DayStatus | null;
}

export interface DayGroup {
  days: number;
  focus_min: number | null;
  xp: number | null;
  factors: [string, number][];
}

export interface ReviewAnalysis {
  summary: string;
  wins: string[];
  struggles: string[];
  patterns: string[];
  next_steps: string[];
}

export interface Review {
  kind: PeriodKind;
  first: string;
  last: string;
  // Последний учтённый день: сегодня, если период идёт.
  end: string;
  label: string;
  in_progress: boolean;
  totals: Totals;
  // Тот же отрезок прошлого периода.
  prev_totals: Totals;
  state: State;
  prev_state: State;
  spheres: SphereReview[];
  days: DayPoint[];
  bad_days: DayGroup;
  good_days: DayGroup;
  emotions: [string, number][];
  factors: [string, number][];
  top_tasks: { id: number; title: string; goal_id: number | null; xp: number }[];
  analysis: ReviewAnalysis | null;
  analyzed_at: string | null;
}

const key = (kind: PeriodKind, offset: number) => ["review", kind, offset] as const;

export function useReview(kind: PeriodKind, offset: number) {
  return useQuery({
    queryKey: key(kind, offset),
    queryFn: () => api.get<Review>(`/review?kind=${kind}&offset=${offset}`),
  });
}

export function useAnalyzeReview(kind: PeriodKind, offset: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () =>
      api.post<{ review: Review; agent_failed: boolean }>(`/review/analyze?kind=${kind}&offset=${offset}`),
    onSuccess: (result) => client.setQueryData(key(kind, offset), result.review),
  });
}
