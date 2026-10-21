import { ActionIcon, Badge, Group, Menu, Paper, Stack, Text } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconCalendarEvent, IconCheck, IconDots, IconPlayerPlay } from "@tabler/icons-react";

import { useSchedule } from "../../api/plan";
import type { Task } from "../../api/tasks";
import { formatMinutes } from "../../lib/format";
import { ACTIVE_STATUSES, planDayLabel, scheduleOptions } from "../../lib/plan";
import { taskXp } from "../../lib/tasks";

export const DRAG_TYPE = "application/x-deepquest-task";

// Карточка задачи на доске плана: перетаскивается по дням, меню «Когда» — для телефона.
export function PlanCard({ task, today, onOpen }: { task: Task; today: string; onOpen: (id: number) => void }) {
  const schedule = useSchedule();
  const active = ACTIVE_STATUSES.has(task.status);
  const xp = taskXp(task);

  const move = (day: string | null) =>
    schedule.mutate(
      { id: task.id, day },
      { onError: (error) => notifications.show({ color: "red", message: error.message }) },
    );

  return (
    <Paper
      withBorder
      p={8}
      className="task-row"
      draggable={active}
      onDragStart={(event) => {
        event.dataTransfer.setData(DRAG_TYPE, String(task.id));
        event.dataTransfer.effectAllowed = "move";
      }}
      onClick={() => onOpen(task.id)}
      style={{ cursor: active ? "grab" : "pointer", opacity: active ? 1 : 0.55 }}
    >
      <Stack gap={4}>
        <Group justify="space-between" wrap="nowrap" align="flex-start" gap={4}>
          <Text size="sm" fw={500} lineClamp={2} td={active ? undefined : "line-through"}>
            {task.status === "running" && <IconPlayerPlay size={12} style={{ marginRight: 4 }} />}
            {task.title}
          </Text>
          {active && (
            <Menu position="bottom-end" withinPortal>
              <Menu.Target>
                <ActionIcon
                  size="sm"
                  variant="subtle"
                  color="gray"
                  aria-label={`Когда: ${task.title}`}
                  onClick={(event) => event.stopPropagation()}
                >
                  <IconDots size={14} />
                </ActionIcon>
              </Menu.Target>
              <Menu.Dropdown onClick={(event) => event.stopPropagation()}>
                <Menu.Label>Когда</Menu.Label>
                {scheduleOptions(today, task.planned_for)
                  .slice(0, 9)
                  .map((option) => (
                    <Menu.Item
                      key={option.value || "someday"}
                      leftSection={
                        (option.value || null) === task.planned_for ? <IconCheck size={14} /> : <IconCalendarEvent size={14} />
                      }
                      onClick={() => move(option.value || null)}
                    >
                      {option.label}
                    </Menu.Item>
                  ))}
              </Menu.Dropdown>
            </Menu>
          )}
        </Group>
        <Group gap={6} wrap="nowrap">
          {xp !== null && (
            <Badge size="xs" variant="light" color="violet" tt="none">
              +{xp} XP
            </Badge>
          )}
          <Text size="xs" c="dimmed" truncate>
            {task.estimate_min !== null ? formatMinutes(task.estimate_min) : "без оценки"}
            {task.goal_path ? ` · ${task.goal_path}` : ""}
          </Text>
        </Group>
        {task.planned_for && task.planned_for < today && (
          <Text size="xs" c="orange">
            было на {planDayLabel(task.planned_for, today).toLowerCase()}
          </Text>
        )}
      </Stack>
    </Paper>
  );
}
