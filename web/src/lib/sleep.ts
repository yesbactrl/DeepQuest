// Время сна — местное время пользователя без пояса («2026-10-24T07:00:00»). Считаем его
// «по часам на стене»: через Date.UTC, чтобы ни пояс, ни переход на летнее время браузера
// не сдвигали отрезки.

export const NIGHT_COLOR = "indigo";
export const NAP_COLOR = "teal";

// Минуты от начала эпохи по «настенным» часам.
export function wallMinutes(value: string): number {
  const [datePart, timePart = "00:00"] = value.split("T");
  const [y, m, d] = datePart.split("-").map(Number);
  const [hh, mm] = timePart.split(":").map(Number);
  return Date.UTC(y, m - 1, d, hh, mm) / 60000;
}

// Обратно в «YYYY-MM-DDTHH:MM» — формат поля datetime-local.
export function fromWallMinutes(minutes: number): string {
  return new Date(minutes * 60000).toISOString().slice(0, 16);
}

export function shiftDay(day: string, days: number): string {
  return fromWallMinutes(wallMinutes(day) + days * 24 * 60).slice(0, 10);
}

export function clock(value: string): string {
  return value.slice(11, 16);
}

// 435 → «07:15».
export function clockOfMinutes(minutes: number): string {
  const m = ((Math.round(minutes) % 1440) + 1440) % 1440;
  return `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
}

// 465 → «7 ч 45 мин», 480 → «8 ч».
export function hours(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  if (!h) return `${m} мин`;
  return m ? `${h} ч ${m} мин` : `${h} ч`;
}
