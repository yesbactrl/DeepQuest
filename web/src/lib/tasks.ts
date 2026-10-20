import type { TaskStatus, Verdict } from "../api/tasks";

export const STATUS: Record<TaskStatus, { label: string; color: string }> = {
  clarifying: { label: "Вопрос агента", color: "yellow" },
  draft: { label: "Черновик", color: "gray" },
  open: { label: "В бэклоге", color: "blue" },
  running: { label: "Идёт таймер", color: "violet" },
  awaiting_report: { label: "Ждёт отчёта", color: "orange" },
  done: { label: "Готово", color: "teal" },
  rejected: { label: "Не засчитано", color: "red" },
  cancelled: { label: "Отменена", color: "gray" },
};

export const FILTERS: { value: string; label: string; statuses: TaskStatus[] }[] = [
  { value: "work", label: "В работе", statuses: ["running", "open", "awaiting_report"] },
  { value: "drafts", label: "Черновики", statuses: ["draft", "clarifying"] },
  { value: "done", label: "Готово", statuses: ["done", "rejected"] },
  {
    value: "all",
    label: "Все",
    statuses: ["clarifying", "draft", "open", "running", "awaiting_report", "done", "rejected"],
  },
];

// Та же шкала, что в промпте агента: насколько задача двигает цель.
export const VALUE_SCALE = [
  { value: 0.5, label: "×0.5 — рутина и подготовка" },
  { value: 0.7, label: "×0.7 — изучение без своего результата" },
  { value: 1, label: "×1 — обычная работа по цели" },
  { value: 1.2, label: "×1.2 — осязаемый результат" },
  { value: 1.5, label: "×1.5 — реальный шаг вовне, некомфортно" },
  { value: 2, label: "×2 — ключевой рискованный шаг" },
];

export const VERDICT: Record<Verdict, { title: string; label: string; color: string }> = {
  accepted: { title: "Засчитано", label: "засчитано", color: "teal" },
  partial: { title: "Засчитано частично", label: "частично", color: "yellow" },
  rejected: { title: "Не засчитано", label: "не засчитано", color: "red" },
};

export function formatMult(value: number): string {
  return `×${Number(value.toFixed(2))}`;
}

export function signedXp(amount: number): string {
  return amount > 0 ? `+${amount} XP` : `${amount} XP`;
}
