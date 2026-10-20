import { ActionIcon, Badge, Group, Text, Tooltip, UnstyledButton } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconCheck, IconPlayerPause } from "@tabler/icons-react";
import { useNavigate } from "react-router";

import { useTimer, useTimerAction } from "../api/tasks";
import { formatClock, useNow } from "../lib/time";

// Идущий таймер виден на любой странице: его можно остановить, не открывая задачу.
export function TimerWidget() {
  const timer = useTimer();
  const action = useTimerAction();
  const navigate = useNavigate();
  const running = timer.data ?? null;
  const now = useNow(running !== null);

  if (!running) return null;
  const elapsed = running.before_min * 60 + (now - new Date(running.started_at).getTime()) / 1000;
  const open = () => navigate(`/tasks?task=${running.task_id}`);

  return (
    <Group gap="xs" wrap="nowrap">
      <Badge variant="dot" color="violet" size="lg" style={{ textTransform: "none" }}>
        <UnstyledButton onClick={open}>
          <Group gap={8} wrap="nowrap">
            <Text size="sm" fw={500} maw={260} truncate>
              {running.title}
            </Text>
            <Text size="sm" ff="monospace">
              {formatClock(elapsed)}
            </Text>
          </Group>
        </UnstyledButton>
      </Badge>
      <Tooltip label="Пауза">
        <ActionIcon
          variant="subtle"
          aria-label="Пауза"
          loading={action.isPending && action.variables?.action === "pause"}
          onClick={() => action.mutate({ id: running.task_id, action: "pause" })}
        >
          <IconPlayerPause size={18} />
        </ActionIcon>
      </Tooltip>
      <Tooltip label="Готово — сдать отчёт">
        <ActionIcon
          variant="subtle"
          color="teal"
          aria-label="Готово"
          loading={action.isPending && action.variables?.action === "done"}
          onClick={() =>
            action.mutate(
              { id: running.task_id, action: "done" },
              {
                onSuccess: open,
                onError: (error) => notifications.show({ message: error.message, color: "red" }),
              },
            )
          }
        >
          <IconCheck size={18} />
        </ActionIcon>
      </Tooltip>
    </Group>
  );
}
