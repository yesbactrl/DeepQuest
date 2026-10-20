import { ActionIcon, Card, Group, Menu, SegmentedControl, Stack, Text } from "@mantine/core";
import {
  IconArrowDown,
  IconArrowUp,
  IconArrowsHorizontal,
  IconDots,
  IconPencil,
  IconTrash,
} from "@tabler/icons-react";
import { useState } from "react";

import type { ChartConfig } from "../../api/dashboard";
import { useGoals } from "../../api/goals";
import { ChartBody } from "./ChartBody";
import { BUCKETS, CHARTS, METRICS, PERIODS } from "./ChartEditor";

const labelOf = (options: { value: string; label: string }[], value: string) =>
  options.find((option) => option.value === value)?.label ?? value;

function useDescription(config: ChartConfig): string {
  const goals = useGoals();
  const goal = goals.data?.find((g) => g.id === config.goal_id);
  const parts = [labelOf(METRICS, config.metric), labelOf(PERIODS, config.period).toLowerCase()];
  if (config.chart !== "pie") parts.push(labelOf(BUCKETS, config.bucket).toLowerCase());
  if (goal) parts.push(`цель «${goal.title}»`);
  parts.push(labelOf(CHARTS, config.chart).toLowerCase());
  return parts.join(" · ");
}

export interface WidgetActions {
  onEdit: () => void;
  onRemove: () => void;
  onMove: (delta: -1 | 1) => void;
  onToggleSize: () => void;
  isFirst: boolean;
  isLast: boolean;
}

export function ChartWidget({ config, actions }: { config: ChartConfig; actions: WidgetActions }) {
  const [view, setView] = useState<"chart" | "table">("chart");
  const description = useDescription(config);
  return (
    <Card withBorder padding="md" h="100%">
      <Stack gap="xs">
        <Group justify="space-between" wrap="nowrap" align="flex-start">
          <Stack gap={0} style={{ minWidth: 0 }}>
            <Text fw={600} truncate>
              {config.title}
            </Text>
            <Text size="xs" c="dimmed" truncate>
              {description}
            </Text>
          </Stack>
          <Group gap={4} wrap="nowrap">
            <SegmentedControl
              size="xs"
              data={[
                { value: "chart", label: "График" },
                { value: "table", label: "Таблица" },
              ]}
              value={view}
              onChange={(value) => setView(value as "chart" | "table")}
            />
            <Menu position="bottom-end" withinPortal>
              <Menu.Target>
                <ActionIcon variant="subtle" color="gray" aria-label={`Настройки: ${config.title}`}>
                  <IconDots size={18} />
                </ActionIcon>
              </Menu.Target>
              <Menu.Dropdown>
                <Menu.Item leftSection={<IconPencil size={16} />} onClick={actions.onEdit}>
                  Настроить
                </Menu.Item>
                <Menu.Item leftSection={<IconArrowsHorizontal size={16} />} onClick={actions.onToggleSize}>
                  {config.size === "full" ? "Половина ширины" : "Во всю ширину"}
                </Menu.Item>
                <Menu.Item leftSection={<IconArrowUp size={16} />} disabled={actions.isFirst} onClick={() => actions.onMove(-1)}>
                  Выше
                </Menu.Item>
                <Menu.Item leftSection={<IconArrowDown size={16} />} disabled={actions.isLast} onClick={() => actions.onMove(1)}>
                  Ниже
                </Menu.Item>
                <Menu.Divider />
                <Menu.Item leftSection={<IconTrash size={16} />} color="red" onClick={actions.onRemove}>
                  Удалить
                </Menu.Item>
              </Menu.Dropdown>
            </Menu>
          </Group>
        </Group>
        <ChartBody config={config} view={view} />
      </Stack>
    </Card>
  );
}
