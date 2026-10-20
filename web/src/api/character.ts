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
