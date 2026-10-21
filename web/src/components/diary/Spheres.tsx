import { Badge, Button, Group, ScrollArea, Stack, Text } from "@mantine/core";
import { IconMoodSad, IconMoodSmile } from "@tabler/icons-react";

import type { DiarySphere } from "../../api/diary";
import type { Goal } from "../../api/goals";
import { goalIcon, useGoalColor } from "../../lib/goalLook";
import { formatScore, scoreColor } from "../../lib/diary";

// Чипы сфер — целей. `multiple` — у новой записи можно отметить несколько,
// иначе это фильтр ленты: «все записи» или одна сфера.
export function SphereChips({
  goals,
  selected,
  onChange,
  allLabel,
}: {
  goals: Goal[];
  selected: number[];
  onChange: (ids: number[]) => void;
  allLabel?: string;
}) {
  const toHex = useGoalColor();
  const toggle = (id: number) =>
    allLabel
      ? onChange(selected.includes(id) ? [] : [id])
      : onChange(selected.includes(id) ? selected.filter((g) => g !== id) : [...selected, id]);
  return (
    <ScrollArea type="never">
      <Group gap={6} wrap="nowrap">
        {allLabel && (
          <Button
            size="compact-sm"
            radius="xl"
            color="gray"
            variant={selected.length === 0 ? "filled" : "subtle"}
            onClick={() => onChange([])}
          >
            {allLabel}
          </Button>
        )}
        {goals.map((goal) => {
          const Icon = goalIcon(goal.icon);
          const active = selected.includes(goal.id);
          return (
            <Button
              key={goal.id}
              size="compact-sm"
              radius="xl"
              color={toHex(goal.color)}
              variant={active ? "filled" : "light"}
              leftSection={<Icon size={14} />}
              onClick={() => toggle(goal.id)}
              aria-pressed={active}
            >
              {goal.title}
            </Button>
          );
        })}
      </Group>
    </ScrollArea>
  );
}

// Заметки записи по сферам: цвет и название цели, оценка, что радует и что огорчает.
export function SphereNotes({ spheres, goals }: { spheres: DiarySphere[]; goals: Goal[] }) {
  const toHex = useGoalColor();
  const byId = new Map(goals.map((goal) => [goal.id, goal]));
  const known = spheres.filter((sphere) => byId.has(sphere.goal_id));
  if (known.length === 0) return null;
  return (
    <Stack gap={4}>
      {known.map((sphere) => {
        const goal = byId.get(sphere.goal_id)!;
        const color = toHex(goal.color);
        return (
          <Group key={sphere.goal_id} gap={6} wrap="nowrap" align="flex-start">
            <Badge variant="light" color={color} size="sm" tt="none" style={{ flexShrink: 0 }}>
              {goal.title}
              {sphere.score !== null && ` · ${formatScore(sphere.score)}`}
            </Badge>
            <Stack gap={0} style={{ minWidth: 0 }}>
              {sphere.good && (
                <Text size="xs">
                  <IconMoodSmile size={12} style={{ verticalAlign: "middle", marginRight: 4 }} color="var(--mantine-color-teal-6)" />
                  {sphere.good}
                </Text>
              )}
              {sphere.bad && (
                <Text size="xs">
                  <IconMoodSad size={12} style={{ verticalAlign: "middle", marginRight: 4 }} color={`var(--mantine-color-${scoreColor(1)}-6)`} />
                  {sphere.bad}
                </Text>
              )}
            </Stack>
          </Group>
        );
      })}
    </Stack>
  );
}
