import { Badge, Button, Group, Popover, ScrollArea, Stack, Text } from "@mantine/core";
import { IconMoodSad, IconMoodSmile } from "@tabler/icons-react";

import type { DiarySphere } from "../../api/diary";
import type { Goal } from "../../api/goals";
import { SCORE_MAX, scoreColor } from "../../lib/diary";
import { goalIcon, useGoalColor } from "../../lib/goalLook";

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
      <Group gap={6} wrap="nowrap" w="max-content">
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

// Оценка 1–10 кнопками — для сфер и общего состояния; повторное нажатие на выбранную —
// убрать оценку.
export function ScorePicker({
  value,
  onChange,
  color,
}: {
  value: number | null;
  onChange: (value: number | null) => void;
  color?: string;
}) {
  return (
    <Group gap={4} wrap="nowrap">
      {Array.from({ length: SCORE_MAX }, (_, i) => i + 1).map((n) => (
        <Button
          key={n}
          size="compact-xs"
          w={28}
          px={0}
          color={color}
          variant={value === n ? "filled" : "default"}
          aria-pressed={value === n}
          onClick={() => onChange(value === n ? null : n)}
        >
          {n}
        </Button>
      ))}
    </Group>
  );
}

// Заметки записи по сферам: цвет и название цели, оценка, что радует и что огорчает.
// Оценку можно поправить прямо здесь: нажать на метку и выбрать число.
export function SphereNotes({
  spheres,
  goals,
  onScore,
}: {
  spheres: DiarySphere[];
  goals: Goal[];
  onScore?: (goalId: number, score: number | null) => void;
}) {
  const toHex = useGoalColor();
  const byId = new Map(goals.map((goal) => [goal.id, goal]));
  const known = spheres.filter((sphere) => byId.has(sphere.goal_id));
  if (known.length === 0) return null;
  return (
    <Stack gap={4}>
      {known.map((sphere) => {
        const goal = byId.get(sphere.goal_id)!;
        const color = toHex(goal.color);
        const badge = (
          <Badge
            variant="light"
            color={color}
            size="sm"
            tt="none"
            style={{ flexShrink: 0, cursor: onScore ? "pointer" : undefined }}
            component={onScore ? "button" : undefined}
            aria-label={onScore ? `Оценка сферы ${goal.title}: изменить` : undefined}
          >
            {goal.title}
            {sphere.score !== null ? ` · ${sphere.score}/${SCORE_MAX}` : onScore ? " · оценить" : ""}
          </Badge>
        );
        return (
          <Group key={sphere.goal_id} gap={6} wrap="nowrap" align="flex-start">
            {onScore ? (
              <Popover position="bottom-start" withinPortal shadow="md">
                <Popover.Target>{badge}</Popover.Target>
                <Popover.Dropdown>
                  <Stack gap={6}>
                    <Text size="xs" c="dimmed">
                      {goal.title}: как сейчас, от 1 до {SCORE_MAX}
                    </Text>
                    <ScorePicker
                      value={sphere.score}
                      color={color}
                      onChange={(score) => onScore(sphere.goal_id, score)}
                    />
                  </Stack>
                </Popover.Dropdown>
              </Popover>
            ) : (
              badge
            )}
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
