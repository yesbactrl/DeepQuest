import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";

import { api } from "./client";

export type TaskStatus =
  | "clarifying"
  | "draft"
  | "open"
  | "running"
  | "awaiting_report"
  | "done"
  | "rejected"
  | "cancelled";

export type Verdict = "accepted" | "partial" | "rejected";

export interface Task {
  id: number;
  title: string;
  expected_result: string | null;
  status: TaskStatus;
  goal_id: number | null;
  goal_path: string | null;
  estimate_min: number | null;
  value_mult: number | null;
  mult_reason: string | null;
  source_text: string;
  clarify_question: string | null;
  created_at: string;
  updated_at: string;
  spent_min: number;
  xp: number;
  running_since: string | null;
}

export interface Proof {
  index: number;
  kind: string;
  name: string | null;
  url: string | null;
  is_image: boolean;
}

export interface TaskDetail extends Task {
  report: { text: string; honor_mode: boolean; created_at: string; proofs: Proof[] } | null;
  validation: {
    verdict: Verdict;
    reason: string;
    comment: string;
    is_dispute: boolean;
    dispute_text: string | null;
    created_at: string;
  } | null;
  breakdown: {
    actual_min: number;
    estimate_min: number;
    counted_min: number;
    capped: boolean;
    value_mult: number;
    verdict: Verdict;
    validation_mult: number;
    honor_mode: boolean;
    proof_mult: number;
    amount: number;
    // ×1.2, если цель задачи была самым слабым статом.
    weak_mult: number;
  } | null;
  can_dispute: boolean;
}

export interface PlanOutcome {
  tasks: Task[];
  question: string | null;
  agent_failed: boolean;
}

export interface CheckResult {
  task: TaskDetail;
  agent_failed: boolean;
  xp_delta: number;
  total_xp: number;
  // Куда пошёл XP, кроме общего уровня.
  stat: string | null;
  skill: string | null;
  weak_mult: number;
}

export interface RunningTimer {
  task_id: number;
  title: string;
  goal_path: string | null;
  started_at: string;
  before_min: number;
}

export interface TaskEdit {
  title?: string;
  expected_result?: string | null;
  goal_id?: number | null;
  estimate_min?: number;
  value_mult?: number;
  mult_reason?: string | null;
}

export function useTasks(statuses: TaskStatus[], goalId: number | null) {
  const params = new URLSearchParams();
  statuses.forEach((status) => params.append("status", status));
  if (goalId !== null) params.set("goal_id", String(goalId));
  return useQuery({
    queryKey: ["tasks", statuses, goalId],
    queryFn: () => api.get<Task[]>(`/tasks?${params}`),
  });
}

export function useTask(id: number | null) {
  return useQuery({
    queryKey: ["task", id],
    queryFn: () => api.get<TaskDetail>(`/tasks/${id}`),
    enabled: id !== null,
  });
}

export function useTimer() {
  return useQuery({
    queryKey: ["timer"],
    queryFn: () => api.get<RunningTimer | null>("/timer"),
    // Таймер могли запустить или остановить в Telegram.
    refetchInterval: 30_000,
  });
}

// После любого действия с задачей меняются списки, таймер и статистика целей.
function refreshAfter(client: QueryClient, detail?: TaskDetail) {
  // Ответ с карточкой кладём в кэш сразу; без неё (мысль, ответ на вопрос) перечитываем
  // открытые карточки: ответ на вопрос превращает ту же задачу в черновик.
  if (detail) client.setQueryData(["task", detail.id], detail);
  else void client.invalidateQueries({ queryKey: ["task"] });
  void client.invalidateQueries({ queryKey: ["tasks"] });
  void client.invalidateQueries({ queryKey: ["timer"] });
  void client.invalidateQueries({ queryKey: ["goals"] });
  void client.invalidateQueries({ queryKey: ["summary"] });
  void client.invalidateQueries({ queryKey: ["character"] });
  void client.invalidateQueries({ queryKey: ["chart"] });
}

function useTaskMutation<I, O>(mutationFn: (input: I) => Promise<O>, detailOf: (output: O) => TaskDetail | undefined) {
  const client = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: (output) => refreshAfter(client, detailOf(output)),
  });
}

const itself = (detail: TaskDetail) => detail;
const nested = <O extends { task: TaskDetail }>(output: O) => output.task;

export function usePlan() {
  return useTaskMutation((text: string) => api.post<PlanOutcome>("/tasks/plan", { text }), () => undefined);
}

export function useClarify(id: number) {
  return useTaskMutation(
    (answer: string) => api.post<PlanOutcome>(`/tasks/${id}/clarify`, { answer }),
    () => undefined,
  );
}

export function useEditTask(id: number) {
  return useTaskMutation((edit: TaskEdit) => api.patch<TaskDetail>(`/tasks/${id}`, edit), itself);
}

export function useRevise(id: number) {
  return useTaskMutation(
    (correction: string | null) =>
      api.post<{ task: TaskDetail; agent_failed: boolean }>(`/tasks/${id}/revise`, { correction }),
    nested,
  );
}

export type SimpleAction = "save" | "cancel" | "pause" | "done";

export function useTaskAction(id: number) {
  return useTaskMutation(
    (action: SimpleAction) => api.post<TaskDetail>(`/tasks/${id}/${action}`),
    itself,
  );
}

export function useStart(id: number) {
  return useTaskMutation(
    () => api.post<{ task: TaskDetail; paused_task_id: number | null }>(`/tasks/${id}/start`),
    nested,
  );
}

export function useReport(id: number) {
  return useTaskMutation(
    ({ text, files, spentMin }: { text: string; files: File[]; spentMin: number | null }) => {
      const form = new FormData();
      form.set("text", text);
      // Сколько ушло на задачу; не указано — по таймеру, а без таймера — по оценке.
      if (spentMin !== null) form.set("spent_min", String(spentMin));
      files.forEach((file) => form.append("files", file));
      return api.upload<CheckResult>(`/tasks/${id}/report`, form);
    },
    nested,
  );
}

// Поправить, сколько ушло на задачу: у проверенной XP пересчитывается тем же вердиктом.
export function useChangeTime(id: number) {
  return useTaskMutation(
    (spentMin: number) => api.post<CheckResult>(`/tasks/${id}/time`, { spent_min: spentMin }),
    nested,
  );
}

export function useRecheck(id: number) {
  return useTaskMutation(() => api.post<CheckResult>(`/tasks/${id}/recheck`), nested);
}

export function useDispute(id: number) {
  return useTaskMutation(
    (argument: string) => api.post<CheckResult>(`/tasks/${id}/dispute`, { argument }),
    nested,
  );
}

// Таймер в шапке управляет задачей, не открывая её: те же действия по id.
export function useTimerAction() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, action }: { id: number; action: "pause" | "done" }) =>
      api.post<TaskDetail>(`/tasks/${id}/${action}`),
    onSuccess: (detail) => refreshAfter(client, detail),
  });
}
