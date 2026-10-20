import { ActionIcon, Button, Card, Divider, Group, Menu, SimpleGrid, Stack, Text } from "@mantine/core";
import { IconArchive, IconDots, IconPencil, IconPlus } from "@tabler/icons-react";

import type { Direction, Goal } from "../../api/goals";
import { formatMinutes } from "../../lib/format";
import { StatItem } from "../StatItem";
import { IdleBadge } from "./IdleBadge";

interface Actions {
  onEdit: (target: Goal | Direction, isDirection: boolean) => void;
  onAddDirection: (goal: Goal) => void;
  onArchive: (target: Goal | Direction, isDirection: boolean) => void;
}

function ItemMenu({
  onEdit,
  onArchive,
  label,
}: {
  onEdit: () => void;
  onArchive: () => void;
  label: string;
}) {
  return (
    <Menu position="bottom-end" withinPortal>
      <Menu.Target>
        <ActionIcon variant="subtle" color="gray" aria-label={`Действия: ${label}`}>
          <IconDots size={18} />
        </ActionIcon>
      </Menu.Target>
      <Menu.Dropdown>
        <Menu.Item leftSection={<IconPencil size={16} />} onClick={onEdit}>
          Изменить
        </Menu.Item>
        <Menu.Item leftSection={<IconArchive size={16} />} color="red" onClick={onArchive}>
          В архив
        </Menu.Item>
      </Menu.Dropdown>
    </Menu>
  );
}

function DirectionRow({ direction, onEdit, onArchive }: { direction: Direction } & Pick<Actions, "onEdit" | "onArchive">) {
  const { stats } = direction;
  return (
    <Group justify="space-between" wrap="nowrap" align="flex-start">
      <Stack gap={2} style={{ minWidth: 0 }}>
        <Text fw={500}>{direction.title}</Text>
        {direction.why && (
          <Text size="sm" c="dimmed" lineClamp={2}>
            {direction.why}
          </Text>
        )}
        <Text size="xs" c="dimmed">
          {formatMinutes(stats.minutes)} · {stats.xp} XP · задач закрыто: {stats.done_tasks}
        </Text>
      </Stack>
      <ItemMenu
        label={direction.title}
        onEdit={() => onEdit(direction, true)}
        onArchive={() => onArchive(direction, true)}
      />
    </Group>
  );
}

export function GoalCard({ goal, onEdit, onAddDirection, onArchive }: { goal: Goal } & Actions) {
  const { stats } = goal;
  return (
    <Card withBorder padding="lg">
      <Group justify="space-between" wrap="nowrap" align="flex-start">
        <Stack gap={6} style={{ minWidth: 0 }}>
          <Text fw={700} size="lg">
            {goal.title}
          </Text>
          <IdleBadge days={stats.idle_days} />
        </Stack>
        <ItemMenu label={goal.title} onEdit={() => onEdit(goal, false)} onArchive={() => onArchive(goal, false)} />
      </Group>

      {goal.why && (
        <Text size="sm" c="dimmed" mt="sm" style={{ whiteSpace: "pre-line" }}>
          {goal.why}
        </Text>
      )}

      <SimpleGrid cols={3} mt="md">
        <StatItem label="Время" value={formatMinutes(stats.minutes)} />
        <StatItem label="XP" value={stats.xp} />
        <StatItem label="Задач закрыто" value={stats.done_tasks} />
      </SimpleGrid>

      <Divider my="md" label="Направления" labelPosition="left" />
      <Stack gap="sm">
        {goal.directions.length === 0 && (
          <Text size="sm" c="dimmed">
            Направление — конкретная линия работы внутри цели, например «Арбитраж трафика» в цели
            «Свой доход».
          </Text>
        )}
        {goal.directions.map((direction) => (
          <DirectionRow key={direction.id} direction={direction} onEdit={onEdit} onArchive={onArchive} />
        ))}
        <Group>
          <Button
            variant="subtle"
            size="xs"
            leftSection={<IconPlus size={14} />}
            onClick={() => onAddDirection(goal)}
          >
            Направление
          </Button>
        </Group>
      </Stack>
    </Card>
  );
}
