import { ActionIcon, Badge, Group, Popover, Stack, Text, Tooltip, UnstyledButton } from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { notifications } from "@mantine/notifications";
import { IconCheck, IconPlayerPause } from "@tabler/icons-react";
import { useNavigate } from "react-router";

import { type RunningTimer, useTimerAction, useTimers } from "../api/tasks";
import { plural } from "../lib/format";
import { formatClock, useNow } from "../lib/time";

function elapsed(timer: RunningTimer, now: number): number {
  return timer.before_min * 60 + (now - new Date(timer.started_at).getTime()) / 1000;
}

// Один таймер: название, время, пауза и «Готово».
function TimerRow({ timer, now, onOpen }: { timer: RunningTimer; now: number; onOpen?: () => void }) {
  const action = useTimerAction();
  const navigate = useNavigate();
  const open = () => {
    onOpen?.();
    navigate(`/tasks?task=${timer.task_id}`);
  };
  const busy = (name: "pause" | "done") =>
    action.isPending && action.variables?.id === timer.task_id && action.variables.action === name;

  return (
    <Group gap="xs" wrap="nowrap" justify="space-between">
      <UnstyledButton onClick={open}>
        <Group gap={8} wrap="nowrap">
          <Text size="sm" fw={500} maw={240} truncate>
            {timer.title}
          </Text>
          <Text size="sm" ff="monospace">
            {formatClock(elapsed(timer, now))}
          </Text>
        </Group>
      </UnstyledButton>
      <Group gap={2} wrap="nowrap">
        <Tooltip label="Пауза">
          <ActionIcon
            variant="subtle"
            aria-label="Пауза"
            loading={busy("pause")}
            onClick={() => action.mutate({ id: timer.task_id, action: "pause" })}
          >
            <IconPlayerPause size={18} />
          </ActionIcon>
        </Tooltip>
        <Tooltip label="Готово — сдать отчёт">
          <ActionIcon
            variant="subtle"
            color="teal"
            aria-label="Готово"
            loading={busy("done")}
            onClick={() =>
              action.mutate(
                { id: timer.task_id, action: "done" },
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
    </Group>
  );
}

// Идущие таймеры видны на любой странице: их можно остановить, не открывая задачу.
// Таймеров может быть несколько — тогда в шапке счётчик, а список по клику.
export function TimerWidget() {
  const timers = useTimers().data ?? [];
  const now = useNow(timers.length > 0);
  const [opened, { toggle, close }] = useDisclosure();

  if (timers.length === 0) return null;
  if (timers.length === 1) {
    return (
      <Badge variant="dot" color="violet" size="lg" h={34} style={{ textTransform: "none" }} pr={4}>
        <TimerRow timer={timers[0]} now={now} />
      </Badge>
    );
  }
  return (
    <Popover opened={opened} onChange={toggle} onDismiss={close} position="bottom-end" shadow="md" withArrow>
      <Popover.Target>
        <UnstyledButton aria-label="Идущие таймеры" onClick={toggle}>
          <Badge variant="dot" color="violet" size="lg" style={{ textTransform: "none", cursor: "pointer" }}>
            {timers.length} {plural(timers.length, "таймер", "таймера", "таймеров")}
          </Badge>
        </UnstyledButton>
      </Popover.Target>
      <Popover.Dropdown>
        <Stack gap="xs" miw={300}>
          {timers.map((timer) => (
            <TimerRow key={timer.task_id} timer={timer} now={now} onOpen={close} />
          ))}
          <Text size="xs" c="dimmed">
            Время по таймеру — для истории. XP считается от оценки задачи.
          </Text>
        </Stack>
      </Popover.Dropdown>
    </Popover>
  );
}
