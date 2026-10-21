import { useQuery } from "@tanstack/react-query";

import type { GoalColor } from "../lib/chartTheme";
import { api } from "./client";
import type { Level, Summary } from "./dashboard";

export interface Skill {
  id: number;
  title: string;
  level: Level;
}

export interface Stat {
  id: number;
  title: string;
  color: GoalColor;
  icon: string | null;
  growth_only: boolean;
  level: Level;
  season_xp: number;
  // Самый слабый стат за сезон получает бонус к XP.
  weakest: boolean;
  skills: Skill[];
}

export interface Award {
  kind: "task" | "correction";
  amount: number;
  task_title: string | null;
  stat: string | null;
  skill: string | null;
  created_at: string;
}

export interface Character {
  summary: Summary;
  stats: Stat[];
  last_award: Award | null;
  weak_stat_mult: number;
}

export function useCharacter() {
  return useQuery({
    queryKey: ["character"],
    queryFn: () => api.get<Character>("/character"),
  });
}

export interface LevelStep {
  level: number;
  // Сколько XP стоит взять уровень с предыдущего и сколько нужно всего с нуля.
  cost: number;
  total: number;
}

export interface XpRules {
  xp_per_minute: number;
  cap_factor: number;
  value_mults: number[];
  validation_mults: Record<"accepted" | "partial" | "rejected", number>;
  honor_mode_mult: number;
  weak_stat_mult: number;
}

export interface Levels {
  steps: LevelStep[];
  rules: XpRules;
  daily_norm_min: number;
}

export function useLevels() {
  return useQuery({
    queryKey: ["levels"],
    queryFn: () => api.get<Levels>("/levels"),
    // Шкала меняется только вместе с кодом.
    staleTime: Infinity,
  });
}
