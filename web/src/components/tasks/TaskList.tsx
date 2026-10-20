import { Badge, Group, Paper, Skeleton, Stack, Text, UnstyledButton } from "@mantine/core";

import type { Task } from "../../api/tasks";
import { formatMinutes } from "../../lib/format";
import { STATUS, formatMult } from "../../lib/tasks";

function meta(task: Task): string {
  const parts = [];
  if (task.goal_path) parts.push(task.goal_path);
  if (task.estimate_min !== null) parts.push(`оценка ${formatMinutes(task.estimate_min)}`);
  if (task.value_mult !== null) parts.push(formatMult(task.value_mult));
  if (task.spent_min) parts.push(`потрачено ${formatMinutes(task.spent_min)}`);
  if (task.xp) parts.push(`${task.xp} XP`);
  return parts.join(" · ");
}

function Row({ task, onOpen }: { task: Task; onOpen: (id: number) => void }) {
  const status = STATUS[task.status];
  return (
    <UnstyledButton onClick={() => onOpen(task.id)} style={{ display: "block" }}>
      <Paper withBorder p="sm" className="task-row">
        <Group justify="space-between" wrap="nowrap" align="flex-start">
          <Stack gap={2} style={{ minWidth: 0 }}>
            <Text fw={500} truncate>
              {task.title}
            </Text>
            <Text size="xs" c="dimmed" truncate>
              {meta(task) || "без оценки"}
            </Text>
          </Stack>
          <Badge color={status.color} variant="light" style={{ flexShrink: 0 }}>
            {status.label}
          </Badge>
        </Group>
      </Paper>
    </UnstyledButton>
  );
}

export function TaskList({
  tasks,
  loading,
  empty,
  onOpen,
}: {
  tasks: Task[] | undefined;
  loading: boolean;
  empty: string;
  onOpen: (id: number) => void;
}) {
  if (loading) {
    return (
      <Stack gap="xs">
        <Skeleton h={58} />
        <Skeleton h={58} />
        <Skeleton h={58} />
      </Stack>
    );
  }
  if (!tasks || tasks.length === 0) {
    return (
      <Text c="dimmed" ta="center" py="xl">
        {empty}
      </Text>
    );
  }
  return (
    <Stack gap="xs">
      {tasks.map((task) => (
        <Row key={task.id} task={task} onOpen={onOpen} />
      ))}
    </Stack>
  );
}
