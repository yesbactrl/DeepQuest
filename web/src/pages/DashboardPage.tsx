import { Alert, Button, Grid, Group, Paper, Skeleton, Stack, Text, Title } from "@mantine/core";
import { modals } from "@mantine/modals";
import { notifications } from "@mantine/notifications";
import { IconChartBar, IconPlus } from "@tabler/icons-react";
import { useState } from "react";

import {
  type ChartConfig,
  NEW_CHART,
  useDashboard,
  useSaveDashboard,
  useSummary,
} from "../api/dashboard";
import { ChartEditor } from "../components/charts/ChartEditor";
import { ChartWidget } from "../components/charts/ChartWidget";
import { SummaryTiles } from "../components/dashboard/SummaryTiles";

const MAX_WIDGETS = 12;

export function DashboardPage() {
  const summary = useSummary();
  const dashboard = useDashboard();
  const save = useSaveDashboard();
  // Редактируемый график: его индекс (null — новый) и черновик настроек.
  const [editing, setEditing] = useState<{ index: number | null; config: ChartConfig } | null>(null);

  const configs = dashboard.data?.map((widget) => widget.config) ?? [];

  function persist(next: ChartConfig[], message?: string) {
    save.mutate(next, {
      onSuccess: () => message && notifications.show({ color: "teal", message }),
      onError: (error) => notifications.show({ color: "red", message: error.message }),
    });
  }

  function saveEdited(config: ChartConfig) {
    if (!editing) return;
    const next = [...configs];
    if (editing.index === null) next.push(config);
    else next[editing.index] = config;
    persist(next, "График сохранён");
    setEditing(null);
  }

  function move(index: number, delta: -1 | 1) {
    const next = [...configs];
    [next[index], next[index + delta]] = [next[index + delta], next[index]];
    persist(next);
  }

  function remove(index: number) {
    modals.openConfirmModal({
      title: "Удалить график?",
      children: <Text size="sm">«{configs[index].title}» пропадёт с дашборда. Данные останутся.</Text>,
      labels: { confirm: "Удалить", cancel: "Отмена" },
      confirmProps: { color: "red" },
      onConfirm: () => persist(configs.filter((_, i) => i !== index)),
    });
  }

  function toggleSize(index: number) {
    const next = [...configs];
    next[index] = { ...next[index], size: next[index].size === "full" ? "half" : "full" };
    persist(next);
  }

  return (
    <Stack gap="lg">
      <Group justify="space-between" align="flex-end">
        <Title order={2}>Дашборд</Title>
        <Button
          leftSection={<IconPlus size={16} />}
          variant="light"
          disabled={configs.length >= MAX_WIDGETS}
          onClick={() => setEditing({ index: null, config: NEW_CHART })}
        >
          График
        </Button>
      </Group>

      {summary.isError && (
        <Alert color="red" title="Не удалось загрузить сводку">
          {summary.error.message}
        </Alert>
      )}
      <SummaryTiles summary={summary.data} />

      {dashboard.isPending && <Skeleton h={300} />}
      {dashboard.isError && (
        <Alert color="red" title="Не удалось загрузить графики">
          {dashboard.error.message}
        </Alert>
      )}
      {dashboard.data && configs.length === 0 && (
        <Paper withBorder p="xl">
          <Stack align="center" gap="xs">
            <IconChartBar size={32} stroke={1.4} />
            <Text c="dimmed">Графиков нет. Добавь свой: что считать, за какой период и как разбить.</Text>
          </Stack>
        </Paper>
      )}
      <Grid>
        {configs.map((config, index) => (
          <Grid.Col key={`${index}-${config.title}`} span={{ base: 12, lg: config.size === "full" ? 12 : 6 }}>
            <ChartWidget
              config={config}
              actions={{
                onEdit: () => setEditing({ index, config }),
                onRemove: () => remove(index),
                onMove: (delta) => move(index, delta),
                onToggleSize: () => toggleSize(index),
                isFirst: index === 0,
                isLast: index === configs.length - 1,
              }}
            />
          </Grid.Col>
        ))}
      </Grid>

      <ChartEditor config={editing?.config ?? null} onSave={saveEdited} onClose={() => setEditing(null)} />
    </Stack>
  );
}
