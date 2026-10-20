import { Button, Group, Modal, SegmentedControl, Select, SimpleGrid, Stack, Text, TextInput } from "@mantine/core";
import { useState } from "react";

import type { ChartConfig } from "../../api/dashboard";
import { useGoals } from "../../api/goals";
import { ChartBody } from "./ChartBody";

export const METRICS = [
  { value: "minutes", label: "Время по таймеру" },
  { value: "xp", label: "XP" },
  { value: "tasks", label: "Закрытые задачи" },
];
export const CHARTS = [
  { value: "bar", label: "Столбцы" },
  { value: "line", label: "Линии" },
  { value: "area", label: "Области" },
  { value: "pie", label: "Кольцо" },
];
export const BUCKETS = [
  { value: "day", label: "По дням" },
  { value: "week", label: "По неделям" },
  { value: "month", label: "По месяцам" },
];
export const PERIODS = [
  { value: "7d", label: "7 дней" },
  { value: "30d", label: "30 дней" },
  { value: "90d", label: "90 дней" },
  { value: "365d", label: "Год" },
  { value: "season", label: "Этот сезон (месяц)" },
];
const ALL_GOALS = "all";

function Editor({
  initial,
  onSave,
  onClose,
}: {
  initial: ChartConfig;
  onSave: (config: ChartConfig) => void;
  onClose: () => void;
}) {
  const goals = useGoals();
  const [config, setConfig] = useState(initial);
  const set = <K extends keyof ChartConfig>(key: K, value: ChartConfig[K]) =>
    setConfig((current) => ({ ...current, [key]: value }));
  const goalOptions = [
    { value: ALL_GOALS, label: "Все цели" },
    ...(goals.data ?? []).map((goal) => ({ value: String(goal.id), label: goal.title })),
  ];
  const splitLabel = config.goal_id === null ? "По целям" : "По направлениям";

  return (
    <Stack>
      <TextInput label="Название" value={config.title} onChange={(e) => set("title", e.currentTarget.value)} maxLength={80} />
      <SimpleGrid cols={{ base: 1, sm: 2 }}>
        <Select
          label="Что считать"
          data={METRICS}
          value={config.metric}
          onChange={(value) => value && set("metric", value as ChartConfig["metric"])}
          allowDeselect={false}
        />
        <Select
          label="Период"
          data={PERIODS}
          value={config.period}
          onChange={(value) => value && set("period", value as ChartConfig["period"])}
          allowDeselect={false}
        />
        <Select
          label="Цели"
          data={goalOptions}
          value={config.goal_id === null ? ALL_GOALS : String(config.goal_id)}
          onChange={(value) => set("goal_id", !value || value === ALL_GOALS ? null : Number(value))}
          allowDeselect={false}
        />
        <Select
          label="Разбивка"
          data={[
            { value: "goal", label: splitLabel },
            { value: "none", label: "Общая сумма" },
          ]}
          value={config.split}
          onChange={(value) => value && set("split", value as ChartConfig["split"])}
          allowDeselect={false}
        />
      </SimpleGrid>
      <Stack gap={4}>
        <Text size="sm" fw={500}>
          Вид
        </Text>
        <SegmentedControl
          data={CHARTS}
          value={config.chart}
          onChange={(value) => set("chart", value as ChartConfig["chart"])}
        />
      </Stack>
      {config.chart !== "pie" && (
        <SegmentedControl
          data={BUCKETS}
          value={config.bucket}
          onChange={(value) => set("bucket", value as ChartConfig["bucket"])}
        />
      )}
      <Group justify="space-between" align="center">
        <Text size="sm" fw={500}>
          Ширина
        </Text>
        <SegmentedControl
          size="xs"
          data={[
            { value: "half", label: "Половина" },
            { value: "full", label: "Во всю ширину" },
          ]}
          value={config.size}
          onChange={(value) => set("size", value as ChartConfig["size"])}
        />
      </Group>
      <Text size="sm" fw={500}>
        Предпросмотр
      </Text>
      <ChartBody config={config} view="chart" height={220} />
      <Group justify="flex-end">
        <Button variant="default" onClick={onClose}>
          Отмена
        </Button>
        <Button onClick={() => onSave({ ...config, title: config.title.trim() || "График" })}>Сохранить</Button>
      </Group>
    </Stack>
  );
}

export function ChartEditor({
  config,
  onSave,
  onClose,
}: {
  config: ChartConfig | null;
  onSave: (config: ChartConfig) => void;
  onClose: () => void;
}) {
  return (
    <Modal opened={config !== null} onClose={onClose} title="Настройка графика" size="xl" closeOnClickOutside={false}>
      {config && <Editor initial={config} onSave={onSave} onClose={onClose} />}
    </Modal>
  );
}
