// Дни плана: даты — строки YYYY-MM-DD логического дня пользователя.

export function addDays(day: string, n: number): string {
  const date = new Date(`${day}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + n);
  return date.toISOString().slice(0, 10);
}

// «Сегодня», «Завтра» или «пт, 24 окт».
export function planDayLabel(day: string, today: string): string {
  if (day === today) return "Сегодня";
  if (day === addDays(today, 1)) return "Завтра";
  return new Date(`${day}T12:00:00Z`).toLocaleDateString("ru-RU", {
    weekday: "short",
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  });
}

export function isWeekend(day: string): boolean {
  const weekday = new Date(`${day}T12:00:00Z`).getUTCDay();
  return weekday === 0 || weekday === 6;
}

// Варианты «Когда»: когда-нибудь и две недели вперёд.
export function scheduleOptions(today: string, current: string | null): { value: string; label: string }[] {
  const days = Array.from({ length: 14 }, (_, i) => addDays(today, i));
  if (current && !days.includes(current)) days.push(current);
  return [
    { value: "", label: "Когда-нибудь" },
    ...days.map((day) => ({
      value: day,
      label: day === today || day === addDays(today, 1)
        ? planDayLabel(day, today)
        : planDayLabel(day, today).replace(/^./, (c) => c.toUpperCase()),
    })),
  ];
}

export const ACTIVE_STATUSES = new Set(["open", "running", "awaiting_report"]);
