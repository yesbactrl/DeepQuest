import type { DiaryEntry, PartOfDay } from "../api/diary";

// Три шкалы дневника — в том же порядке, что в промпте агента.
export const SCALES = [
  { key: "mood", label: "Настроение", short: "настр.", icon: "🙂", hint: "1 — подавлен, 10 — на подъёме" },
  { key: "energy", label: "Энергия", short: "энергия", icon: "⚡", hint: "1 — без сил, 10 — полон сил" },
  { key: "drive", label: "Желание действовать", short: "желание", icon: "🔥", hint: "1 — ничего не хочется, 10 — рвусь в бой" },
] as const;

export type ScaleKey = (typeof SCALES)[number]["key"];

export const PART_OF_DAY: Record<PartOfDay, string> = {
  morning: "утро",
  day: "день",
  evening: "вечер",
};

// Все оценки дневника — настроение, энергия, желание и сферы — по шкале 1–10.
export const SCORE_MAX = 10;

// Цвет оценки: низкие — тёплые, средние — серые, высокие — зелёные.
export function scoreColor(value: number): string {
  if (value < 5) return "red";
  if (value < 7) return "gray";
  return "teal";
}

export function formatScore(value: number): string {
  return value.toLocaleString("ru-RU", { maximumFractionDigits: 1 });
}

export function entryTime(entry: DiaryEntry): string {
  return new Date(entry.created_at).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
}

// «Сегодня», «Вчера» или «вт, 20 окт».
export function dayLabel(day: string, today: string): string {
  if (day === today) return "Сегодня";
  const yesterday = new Date(`${today}T12:00:00`);
  yesterday.setDate(yesterday.getDate() - 1);
  if (day === yesterday.toISOString().slice(0, 10)) return "Вчера";
  return new Date(`${day}T12:00:00`).toLocaleDateString("ru-RU", {
    weekday: "short",
    day: "numeric",
    month: "short",
  });
}
