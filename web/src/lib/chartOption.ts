import type { ChartConfig, ChartData, Series } from "../api/dashboard";
import type { EChartOption } from "../components/charts/EChart";
import type { ChartTheme } from "./chartTheme";
import { formatMinutes } from "./format";

// Больше пяти долей на кольце уже не читается: остальное сворачиваем в «Другое».
const MAX_SLICES = 5;

export function formatValue(metric: ChartConfig["metric"], value: number): string {
  if (metric === "minutes") return formatMinutes(Math.round(value));
  if (metric === "xp") return `${Math.round(value).toLocaleString("ru-RU")} XP`;
  return `${Math.round(value)}`;
}

function axisValue(metric: ChartConfig["metric"], value: number, maxValue: number): string {
  if (metric === "minutes") return maxValue >= 120 ? `${Math.round(value / 60)} ч` : `${value} мин`;
  return value >= 1000 ? `${Math.round(value / 100) / 10}K` : `${value}`;
}

function hourInterval(metric: ChartConfig["metric"], maxValue: number): number | undefined {
  if (metric !== "minutes" || maxValue < 120) return undefined;
  const hours = Math.ceil(maxValue / 60);
  return Math.ceil(hours / 5) * 60;
}

export function isEmpty(data: ChartData): boolean {
  return data.series.every((series) => series.values.every((value) => value === 0));
}

function total(series: Series): number {
  return series.values.reduce((sum, value) => sum + value, 0);
}

function pieOption(config: ChartConfig, data: ChartData, theme: ChartTheme): EChartOption {
  const slices = data.series
    .map((series) => ({ name: series.name, value: total(series), color: theme.series(series.slot) }))
    .filter((slice) => slice.value > 0)
    .sort((a, b) => b.value - a.value);
  const shown = slices.slice(0, MAX_SLICES);
  const rest = slices.slice(MAX_SLICES).reduce((sum, slice) => sum + slice.value, 0);
  if (rest > 0) shown.push({ name: "Другое", value: rest, color: theme.neutral });
  return {
    tooltip: {
      trigger: "item",
      backgroundColor: theme.surface,
      borderColor: theme.grid,
      textStyle: { color: theme.textPrimary },
      formatter: (p: { name: string; value: number; percent: number }) =>
        `${p.name}: <b>${formatValue(config.metric, p.value)}</b> (${p.percent}%)`,
    },
    legend: {
      bottom: 0,
      icon: "roundRect",
      textStyle: { color: theme.textSecondary },
    },
    series: [
      {
        type: "pie",
        radius: ["52%", "78%"],
        center: ["50%", "44%"],
        avoidLabelOverlap: true,
        label: { show: false },
        itemStyle: { borderColor: theme.surface, borderWidth: 2, borderRadius: 4 },
        data: shown.map((slice) => ({
          name: slice.name,
          value: Math.round(slice.value * 10) / 10,
          itemStyle: { color: slice.color },
        })),
      },
    ],
  };
}

export function buildOption(config: ChartConfig, data: ChartData, theme: ChartTheme): EChartOption {
  if (config.chart === "pie") return pieOption(config, data, theme);

  const many = data.series.length > 1;
  const stacked = many && (config.chart === "bar" || config.chart === "area");
  const maxValue = Math.max(
    0,
    ...data.labels.map((_, i) =>
      stacked
        ? data.series.reduce((sum, s) => sum + s.values[i], 0)
        : Math.max(...data.series.map((s) => s.values[i])),
    ),
  );
  // У стопки скругляем только верхний ненулевой сегмент — данные «растут» от оси.
  const topSeries = data.labels.map((_, i) => {
    for (let s = data.series.length - 1; s >= 0; s--) if (data.series[s].values[i] > 0) return s;
    return -1;
  });

  const series = data.series.map((s, index) => {
    const color = theme.series(s.slot);
    if (config.chart === "bar") {
      return {
        type: "bar",
        name: s.name,
        stack: stacked ? "total" : undefined,
        barMaxWidth: 28,
        itemStyle: { color, borderColor: theme.surface, borderWidth: 1 },
        emphasis: { focus: "series" },
        data: s.values.map((value, i) => ({
          value,
          itemStyle: !stacked || topSeries[i] === index ? { borderRadius: [4, 4, 0, 0] } : undefined,
        })),
      };
    }
    return {
      type: "line",
      name: s.name,
      stack: stacked ? "total" : undefined,
      showSymbol: false,
      symbol: "circle",
      symbolSize: 8,
      lineStyle: { width: 2, cap: "round", join: "round", color },
      itemStyle: { color, borderColor: theme.surface, borderWidth: 2 },
      areaStyle: config.chart === "area" ? { color, opacity: many ? 0.35 : 0.18 } : undefined,
      emphasis: { focus: "series" },
      data: s.values,
    };
  });

  if (data.norm_min !== null && series.length > 0) {
    // Линия нормы — справочная: цвет текста, не цвет серии.
    Object.assign(series[series.length - 1], {
      markLine: {
        silent: true,
        symbol: "none",
        lineStyle: { color: theme.textSecondary, type: "dashed", width: 1 },
        label: { formatter: "норма", color: theme.textSecondary, position: "insideEndTop" },
        data: [{ yAxis: data.norm_min }],
      },
    });
  }

  return {
    grid: { left: 8, right: 16, top: 16, bottom: many ? 40 : 8, containLabel: true },
    tooltip: {
      trigger: "axis",
      axisPointer: { type: config.chart === "bar" ? "shadow" : "line" },
      backgroundColor: theme.surface,
      borderColor: theme.grid,
      textStyle: { color: theme.textPrimary },
      valueFormatter: (value: number) => formatValue(config.metric, value),
    },
    legend: many
      ? { bottom: 0, icon: "roundRect", textStyle: { color: theme.textSecondary } }
      : undefined,
    xAxis: {
      type: "category",
      data: data.labels,
      boundaryGap: config.chart === "bar",
      axisLine: { lineStyle: { color: theme.grid } },
      axisTick: { show: false },
      axisLabel: { color: theme.textSecondary },
    },
    yAxis: {
      type: "value",
      splitLine: { lineStyle: { color: theme.grid, width: 1, type: "solid" } },
      axisLabel: {
        color: theme.textSecondary,
        formatter: (value: number) => axisValue(config.metric, value, maxValue),
      },
      // Чтобы линия нормы всегда была видна, даже в пустые дни.
      max: data.norm_min !== null ? Math.max(maxValue, data.norm_min) : undefined,
      // Минуты подписываем целыми часами: шаг делений кратен часу, иначе «3 ч» повторится.
      interval: hourInterval(config.metric, Math.max(maxValue, data.norm_min ?? 0)),
    },
    series,
  };
}
