import {
  ActionIcon,
  Badge,
  Button,
  Group,
  Paper,
  Skeleton,
  Stack,
  Text,
  Tooltip,
  UnstyledButton,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconCheck, IconPlayerPause, IconPlayerPlay, type Icon } from "@tabler/icons-react";

import { type Task, useStart, useTaskAction } from "../../api/tasks";
import { formatMinutes } from "../../lib/format";
import { STATUS, formatMult, taskXp } from "../../lib/tasks";

const showError = (error: Error) => notifications.show({ color: "red", message: error.message });

function meta(task: Task): string {
  const parts = [];
  if (task.goal_path) parts.push(task.goal_path);
  if (task.spent_min) parts.push(`потрачено ${formatMinutes(task.spent_min)}`);
  return parts.join(" · ");
}

function formatDuration(minutes: number): string {
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (!hours) return `${rest} мин`;
  if (!rest) return `${hours} ч`;
  return `${hours}:${String(rest).padStart(2, "0")} ч`;
}

// Квадратик слева: XP видно сразу, а при наведении — длительность и множитель.
function XpTile({ task }: { task: Task }) {
  const xp = taskXp(task);
  const duration = task.estimate_min !== null ? formatDuration(task.estimate_min) : "без оценки";
  const mult = task.value_mult !== null ? formatMult(task.value_mult) : "—";
  return (
    <div
      className="xp-tile"
      tabIndex={0}
      aria-label={xp === null ? "Без оценки" : `${xp} XP: ${duration}, ${mult}`}
    >
      <div className="xp-tile__face xp-tile__face--xp">
        <Text fw={700} size="lg" lh={1.1} c="inherit">
          {xp === null ? "?" : `+${xp}`}
        </Text>
        <Text size="xs" lh={1.1} c="inherit" opacity={0.8}>
          XP
        </Text>
      </div>
      <div className="xp-tile__face xp-tile__face--details">
        <Text fw={600} size="sm" lh={1.2} c="inherit">
          {duration}
        </Text>
        <Text size="xs" lh={1.2} c="inherit" opacity={0.8}>
          {mult}
        </Text>
      </div>
    </div>
  );
}

// На широком экране — кнопка с подписью, на узком — только иконка.
function RowButton({
  label,
  icon: IconComponent,
  onClick,
  loading,
  disabled,
  variant,
  color,
}: {
  label: string;
  icon: Icon;
  onClick: () => void;
  loading: boolean;
  disabled?: boolean;
  variant: "filled" | "light" | "default";
  color?: string;
}) {
  return (
    <>
      <Button
        visibleFrom="sm"
        size="xs"
        variant={variant}
        color={color}
        leftSection={<IconComponent size={14} />}
        loading={loading}
        disabled={disabled}
        onClick={onClick}
      >
        {label}
      </Button>
      <Tooltip label={label}>
        <ActionIcon
          hiddenFrom="sm"
          size="lg"
          variant={variant}
          color={color}
          aria-label={label}
          loading={loading}
          disabled={disabled}
          onClick={onClick}
        >
          <IconComponent size={16} />
        </ActionIcon>
      </Tooltip>
    </>
  );
}

function Actions({ task, onOpen }: { task: Task; onOpen: (id: number) => void }) {
  const start = useStart(task.id);
  const action = useTaskAction(task.id);
  const busy = (name: "pause" | "done") => action.isPending && action.variables === name;
  // После «Готово» сразу открываем карточку: там форма отчёта.
  const done = () => action.mutate("done", { onSuccess: () => onOpen(task.id), onError: showError });
  const doneButton = (
    <RowButton label="Готово" icon={IconCheck} variant="light" color="teal" loading={busy("done")} onClick={done} />
  );

  if (task.status === "open") {
    return (
      <Group gap={6} wrap="nowrap">
        <RowButton
          label={task.spent_min ? "Продолжить" : "Старт"}
          icon={IconPlayerPlay}
          variant="filled"
          loading={start.isPending}
          disabled={task.estimate_min === null}
          onClick={() =>
            start.mutate(undefined, {
              onSuccess: (result) =>
                result.paused_task_id &&
                notifications.show({ message: "Предыдущая задача встала на паузу", color: "gray" }),
              onError: showError,
            })
          }
        />
        {doneButton}
      </Group>
    );
  }
  if (task.status === "running") {
    return (
      <Group gap={6} wrap="nowrap">
        <RowButton
          label="Пауза"
          icon={IconPlayerPause}
          variant="default"
          loading={busy("pause")}
          onClick={() => action.mutate("pause", { onError: showError })}
        />
        {doneButton}
      </Group>
    );
  }
  const status = STATUS[task.status];
  return (
    <Badge color={status.color} variant="light" style={{ flexShrink: 0 }}>
      {status.label}
    </Badge>
  );
}

function Row({ task, onOpen }: { task: Task; onOpen: (id: number) => void }) {
  return (
    <Paper withBorder p="sm" className="task-row">
      <Group wrap="nowrap" gap="sm">
        <XpTile task={task} />
        <UnstyledButton onClick={() => onOpen(task.id)} style={{ flex: 1, minWidth: 0 }}>
          <Stack gap={2}>
            <Text fw={500} truncate>
              {task.title}
            </Text>
            <Text size="xs" c="dimmed" truncate>
              {meta(task) || "без цели"}
            </Text>
          </Stack>
        </UnstyledButton>
        <Actions task={task} onOpen={onOpen} />
      </Group>
    </Paper>
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
        <Skeleton h={74} />
        <Skeleton h={74} />
        <Skeleton h={74} />
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
