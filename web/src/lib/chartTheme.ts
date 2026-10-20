// Цвета графиков. Категориальная палитра — восемь оттенков в фиксированном порядке,
// отдельно подобранных для светлой и тёмной темы и проверенных валидатором на наших
// поверхностях (#ffffff и #242424): различимы в том числе при дальтонизме.
// Цвет серии берётся по её постоянному номеру (slot), а не по месту в рейтинге.

const SERIES = {
  light: ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"],
  dark: ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"],
};

export interface ChartTheme {
  surface: string;
  grid: string;
  textPrimary: string;
  textSecondary: string;
  neutral: string;
  series: (slot: number) => string;
}

export function chartTheme(scheme: "light" | "dark"): ChartTheme {
  const palette = SERIES[scheme];
  const dark = scheme === "dark";
  const neutral = dark ? "#7d7c78" : "#a3a29c";
  return {
    surface: dark ? "#242424" : "#ffffff",
    grid: dark ? "#353533" : "#ececea",
    textPrimary: dark ? "#f0efec" : "#0b0b0b",
    textSecondary: dark ? "#c3c2b7" : "#52514e",
    neutral,
    // Девятая цель цвет не придумывает: уходит в нейтральный серый.
    series: (slot) => (slot >= 0 && slot < palette.length ? palette[slot] : neutral),
  };
}

// Статусы дня — свои цвета, не пересекаются с цветами целей и всегда идут с подписью.
export const DAY_STATUS = {
  met: { color: "#0ca30c", label: "норма выполнена" },
  frozen: { color: "#6da7ec", label: "заморозка" },
  missed: { color: "#d03b3b", label: "пропуск" },
} as const;
