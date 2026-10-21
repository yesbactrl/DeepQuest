import type { CheckResult, Task, TaskStatus, Verdict } from "../api/tasks";

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
  // Вкладки идут в порядке жизни задачи: черновик → бэклог → работа → готово.
  // В работе — то, что начато: таймер идёт или ждёт отчёта. Сохранённое, но не начатое — в бэклоге.
  { value: "drafts", label: "Черновики", statuses: ["draft", "clarifying"] },
  { value: "backlog", label: "В бэклоге", statuses: ["open"] },
  { value: "work", label: "В работе", statuses: ["running", "awaiting_report"] },
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

// «+60 XP общий · +60 Здоровье · +60 Спорт»: XP идёт сразу в уровень, стат и скилл.
export function xpSplit(amount: number, stat: string | null, skill: string | null): string {
  const signed = signedXp(amount);
  if (amount === 0 || !stat) return signed;
  const number = signed.replace(/ XP$/, "");
  // Неразрывный пробел: «+60» не отрывается от названия при переносе строки.
  const part = (label: string) => `${number}\u00a0${label}`;
  return [`${signed}\u00a0общий`, part(stat), ...(skill ? [part(skill)] : [])].join(" · ");
}

// Текст уведомления после проверки: куда пошёл XP и был ли бонус слабому стату.
export function awardMessage(result: CheckResult): string {
  const split = xpSplit(result.xp_delta, result.stat, result.skill);
  return result.weak_mult > 1 && result.xp_delta > 0 && result.stat
    ? `${split}\n«${result.stat}» — самый слабый стат: ${formatMult(result.weak_mult)} к XP`
    : split;
}

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

// Сколько XP даст задача: за закрытую — начисленное, иначе — оценка × множитель
// (если отчёт засчитают целиком и с пруфом). Бонус слабому стату сюда не входит.
export function taskXp(task: Task): number | null {
  if (task.status === "done" || task.status === "rejected") return task.xp;
  if (task.estimate_min === null || task.value_mult === null) return null;
  return Math.round(task.estimate_min * task.value_mult);
}

// Сортировка списка: по умолчанию свежие сверху (как отдаёт сервер), можно по оценке
// времени или по XP. Задачи без оценки при такой сортировке уходят в конец.
export const SORTS = [
  { value: "recent", label: "Сначала свежие" },
  { value: "short", label: "Сначала короткие" },
  { value: "long", label: "Сначала длинные" },
  { value: "xp_high", label: "Больше XP" },
  { value: "xp_low", label: "Меньше XP" },
] as const;

export type SortValue = (typeof SORTS)[number]["value"];

const SORT_KEYS: Record<Exclude<SortValue, "recent">, [(task: Task) => number | null, 1 | -1]> = {
  short: [(task) => task.estimate_min, 1],
  long: [(task) => task.estimate_min, -1],
  xp_high: [taskXp, -1],
  xp_low: [taskXp, 1],
};

export function sortTasks(tasks: Task[], sort: SortValue): Task[] {
  if (sort === "recent") return tasks;
  const [key, sign] = SORT_KEYS[sort];
  return [...tasks].sort((a, b) => {
    const x = key(a);
    const y = key(b);
    if (x === null || y === null) return (x === null ? 1 : 0) - (y === null ? 1 : 0);
    return sign * (x - y);
  });
}
