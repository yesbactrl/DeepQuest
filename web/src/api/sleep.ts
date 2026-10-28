import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";

export type SleepKind = "night" | "nap";

// Время сна — местное время пользователя без пояса: «2026-10-24T07:00:00».
export interface SleepSession {
  id: number;
  kind: SleepKind;
  start: string;
  end: string;
  // День пробуждения.
  day: string;
  minutes: number;
  quality: number | null;
  note: string | null;
  // Сколько XP принесла правка: за день +10 за ночной сон и +5 за дневной.
  xp_delta: number;
}

export interface SleepDay {
  day: string;
  night_min: number;
  nap_min: number;
  total_min: number;
  bedtime: string | null;
  wake: string | null;
  quality: number | null;
  sessions: SleepSession[];
}

export interface SleepGroup {
  days: number;
  state: number | null;
  focus_min: number | null;
}

export interface SleepStats {
  days: number;
  avg_total_min: number | null;
  avg_night_min: number | null;
  avg_nap_min: number | null;
  // Минуты от полуночи.
  avg_bedtime: number | null;
  avg_wake: number | null;
  bedtime_spread_min: number | null;
  goal_met: number;
  debt_min: number;
  avg_quality: number | null;
  short: SleepGroup;
  enough: SleepGroup;
}

export interface SleepOverview {
  first: string;
  // Сегодня по поясу пользователя.
  last: string;
  goal_min: number;
  // Свежие сверху, только дни с записями.
  days: SleepDay[];
  stats: SleepStats;
}

export interface SleepInput {
  kind: SleepKind;
  start: string;
  end: string;
  quality: number | null;
  note: string | null;
}

const SLEEP_KEY = ["sleep"] as const;

export function useSleep(days: number) {
  return useQuery({
    queryKey: [...SLEEP_KEY, days],
    queryFn: () => api.get<SleepOverview>(`/sleep?days=${days}`),
  });
}

function useSleepMutation<I, O>(mutationFn: (input: I) => Promise<O>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: SLEEP_KEY });
      // Сон есть и в итогах периода, а XP за него — в уровне, персонаже и графиках.
      void client.invalidateQueries({ queryKey: ["review"] });
      void client.invalidateQueries({ queryKey: ["summary"] });
      void client.invalidateQueries({ queryKey: ["character"] });
      void client.invalidateQueries({ queryKey: ["chart"] });
      void client.invalidateQueries({ queryKey: ["diary"] });
    },
  });
}

export function useAddSleep() {
  return useSleepMutation((input: SleepInput) => api.post<SleepSession>("/sleep", input));
}

export function useEditSleep(id: number) {
  return useSleepMutation((input: SleepInput) => api.patch<SleepSession>(`/sleep/${id}`, input));
}

export function useDeleteSleep(id: number) {
  return useSleepMutation(() => api.delete(`/sleep/${id}`));
}

export function useSleepGoal() {
  return useSleepMutation((goalMin: number) =>
    api.patch<{ goal_min: number }>("/sleep/goal", { goal_min: goalMin }),
  );
}
