import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";

export type Metric = "minutes" | "xp" | "tasks";
export type Bucket = "day" | "week" | "month";
export type Split = "none" | "goal";
export type Period = "7d" | "30d" | "90d" | "365d" | "season";
export type ChartType = "bar" | "line" | "area" | "pie";
export type Size = "half" | "full";

export interface ChartConfig {
  title: string;
  metric: Metric;
  bucket: Bucket;
  split: Split;
  period: Period;
  chart: ChartType;
  size: Size;
  goal_id: number | null;
}

export interface Series {
  key: string;
  name: string;
  values: number[];
  // Постоянный номер цвета; -1 — нейтральная серия («Без цели»).
  slot: number;
}

export interface ChartData {
  buckets: string[];
  labels: string[];
  series: Series[];
  norm_min: number | null;
}

export interface Widget {
  id: number;
  position: number;
  config: ChartConfig;
}

export interface Level {
  level: number;
  xp: number;
  floor_xp: number;
  next_xp: number;
  progress: number;
}

export interface DayMark {
  day: string;
  status: "met" | "missed" | "frozen" | "today";
  focus_min: number;
  norm_min: number;
}

export interface Summary {
  total: Level;
  season: string;
  season_level: Level;
  streak: {
    current: number;
    best: number;
    today: string;
    today_focus_min: number;
    norm_min: number;
    today_met: boolean;
    freezes_left: number;
    freezes_per_week: number;
    recent: DayMark[];
  };
}

export const NEW_CHART: ChartConfig = {
  title: "Новый график",
  metric: "minutes",
  bucket: "day",
  split: "goal",
  period: "30d",
  chart: "bar",
  size: "half",
  goal_id: null,
};

export function useSummary() {
  return useQuery({
    queryKey: ["summary"],
    queryFn: () => api.get<Summary>("/summary"),
    // Норма на сегодня растёт, пока идёт таймер.
    refetchInterval: 60_000,
  });
}

export function useDashboard() {
  return useQuery({ queryKey: ["dashboard"], queryFn: () => api.get<Widget[]>("/dashboard") });
}

export function useSaveDashboard() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (configs: ChartConfig[]) => api.put<Widget[]>("/dashboard", configs),
    onSuccess: (widgets) => client.setQueryData(["dashboard"], widgets),
  });
}

export function useChartData(config: ChartConfig) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(config)) {
    if (value !== null && key !== "title" && key !== "size") params.set(key, String(value));
  }
  return useQuery({
    queryKey: ["chart", params.toString()],
    queryFn: () => api.get<ChartData>(`/stats/series?${params}`),
    // Пока в редакторе меняются настройки, старый график не исчезает.
    placeholderData: keepPreviousData,
    refetchInterval: 60_000,
  });
}
