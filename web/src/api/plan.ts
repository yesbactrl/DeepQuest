import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import type { Task } from "./tasks";

export interface PlanDay {
  day: string;
  tasks: Task[];
  // Нагрузка — только незакрытые: сумма оценок и XP, если всё засчитают.
  load_min: number;
  load_xp: number;
}

export interface Plan {
  today: string;
  norm_min: number;
  days: PlanDay[];
  unplanned: Task[];
  overdue: Task[];
  energy_today: number | null;
  drive_today: number | null;
}

export function usePlan() {
  return useQuery({ queryKey: ["plan"], queryFn: () => api.get<Plan>("/plan") });
}

// Поставить задачу на день или вернуть в «когда-нибудь» (day = null).
export function useSchedule() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, day }: { id: number; day: string | null }) =>
      api.post<Task>(`/tasks/${id}/schedule`, { day }),
    onSuccess: (task) => {
      void client.invalidateQueries({ queryKey: ["plan"] });
      void client.invalidateQueries({ queryKey: ["tasks"] });
      void client.invalidateQueries({ queryKey: ["task", task.id] });
    },
  });
}
