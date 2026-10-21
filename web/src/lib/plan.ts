// Дни плана: даты — строки YYYY-MM-DD логического дня пользователя.

export function addDays(day: string, n: number): string {
  const date = new Date(`${day}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + n);
  return date.toISOString().slice(0, 10);
}

// «пт, 24 окт.»
export function shortDate(day: string): string {
  return new Date(`${day}T12:00:00Z`).toLocaleDateString("ru-RU", {
    weekday: "short",
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  });
}

// «Сегодня · вт, 21 окт.», «Завтра · ср, 22 окт.» или просто «пт, 24 окт.».
export function planDayLabel(day: string, today: string): string {
  if (day === today) return `Сегодня · ${shortDate(day)}`;
  if (day === addDays(today, 1)) return `Завтра · ${shortDate(day)}`;
  return shortDate(day);
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
      label: planDayLabel(day, today).replace(/^./, (c) => c.toUpperCase()),
    })),
  ];
}

export const ACTIVE_STATUSES = new Set(["open", "running", "awaiting_report"]);
