import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";

export interface GoalStats {
  minutes: number;
  xp: number;
  done_tasks: number;
  last_activity_at: string | null;
  idle_days: number;
}

export interface Direction {
  id: number;
  title: string;
  why: string | null;
  created_at: string;
  stats: GoalStats;
}

export interface Goal extends Direction {
  status: "active" | "archived";
  directions: Direction[];
}

export interface GoalInput {
  title: string;
  why?: string | null;
  parent_id?: number | null;
}

const GOALS_KEY = ["goals"] as const;

export function useGoals() {
  return useQuery({ queryKey: GOALS_KEY, queryFn: () => api.get<Goal[]>("/goals") });
}

// Каждое изменение возвращает весь список целей: кладём его в кэш вместо повторного запроса.
function useGoalsMutation<T>(mutationFn: (input: T) => Promise<Goal[]>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: (goals) => client.setQueryData(GOALS_KEY, goals),
  });
}

export function useCreateGoal() {
  return useGoalsMutation((input: GoalInput) => api.post<Goal[]>("/goals", input));
}

export function useUpdateGoal() {
  return useGoalsMutation(({ id, ...changes }: { id: number; title?: string; why?: string }) =>
    api.patch<Goal[]>(`/goals/${id}`, changes),
  );
}

export function useArchiveGoal() {
  return useGoalsMutation((id: number) => api.post<Goal[]>(`/goals/${id}/archive`));
}
