import { Alert, Button, Group, Paper, ScrollArea, Skeleton, Stack, Text, Title } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconBolt } from "@tabler/icons-react";
import { useState, type DragEvent, type ReactNode } from "react";

import { type Plan, usePlan, useSchedule } from "../api/plan";
import type { Task } from "../api/tasks";
import { DRAG_TYPE, PlanCard } from "../components/plan/PlanCard";
import { TaskDrawer } from "../components/tasks/TaskDrawer";
import { formatMinutes } from "../lib/format";
import { isWeekend, planDayLabel } from "../lib/plan";

const COLUMN_WIDTH = 230;

// Колонка доски: сюда можно бросить задачу. `day = null` — «когда-нибудь».
function Column({
  title,
  subtitle,
  day,
  tasks,
  today,
  weekend,
  onOpen,
  footer,
}: {
  title: string;
  subtitle?: ReactNode;
  day: string | null;
  tasks: Task[];
  today: string;
  weekend?: boolean;
  onOpen: (id: number) => void;
  footer?: ReactNode;
}) {
  const schedule = useSchedule();
  const [over, setOver] = useState(false);

  function onDrop(event: DragEvent) {
    event.preventDefault();
    setOver(false);
    const id = Number(event.dataTransfer.getData(DRAG_TYPE));
    if (!id) return;
    schedule.mutate(
      { id, day },
      { onError: (error) => notifications.show({ color: "red", message: error.message }) },
    );
  }

  return (
    <Paper
      withBorder
      p="xs"
      w={COLUMN_WIDTH}
      miw={COLUMN_WIDTH}
      bg={over ? "var(--mantine-color-violet-light)" : weekend ? "var(--mantine-color-default-hover)" : undefined}
      onDragOver={(event) => {
        if (!event.dataTransfer.types.includes(DRAG_TYPE)) return;
        event.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={onDrop}
      style={{ alignSelf: "stretch", transition: "background-color 120ms ease" }}
    >
      <Stack gap="xs">
        <Stack gap={0}>
          <Text fw={700}>{title}</Text>
          {subtitle}
        </Stack>
        {tasks.map((task) => (
          <PlanCard key={task.id} task={task} today={today} onOpen={onOpen} />
        ))}
        {tasks.length === 0 && (
          <Text size="xs" c="dimmed" ta="center" py="md">
            Перетащи сюда задачу
          </Text>
        )}
        {footer}
      </Stack>
    </Paper>
  );
}

function Load({ minutes, xp, norm }: { minutes: number; xp: number; norm: number | null }) {
  if (minutes === 0) {
    return (
      <Text size="xs" c="dimmed">
        свободно
      </Text>
    );
  }
  const over = norm !== null && minutes > norm;
  return (
    <Text size="xs" c={over ? "red" : "dimmed"}>
      {formatMinutes(minutes)}
      {norm !== null && ` из ${formatMinutes(norm)}`}
      {xp ? ` · +${xp} XP` : ""}
      {over && ` · перебор ${formatMinutes(minutes - norm)}`}
    </Text>
  );
}

// Мало сил по дневнику — подсказка разгрузить сегодняшний день.
function EnergyHint({ plan }: { plan: Plan }) {
  const low = [
    plan.energy_today !== null && plan.energy_today <= 2 ? `энергия ${plan.energy_today}` : null,
    plan.drive_today !== null && plan.drive_today <= 2 ? `желание действовать ${plan.drive_today}` : null,
  ].filter(Boolean);
  if (low.length === 0) return null;
  return (
    <Alert color="yellow" variant="light" icon={<IconBolt size={18} />}>
      По дневнику сегодня {low.join(" и ")} из 5 — может, оставить на сегодня поменьше?
    </Alert>
  );
}

function Overdue({ plan, onOpen }: { plan: Plan; onOpen: (id: number) => void }) {
  const schedule = useSchedule();
  if (plan.overdue.length === 0) return null;
  const move = (day: string | null) =>
    plan.overdue.forEach((task) => schedule.mutate({ id: task.id, day }));
  return (
    <Paper withBorder p="sm">
      <Stack gap="xs">
        <Group justify="space-between">
          <Text fw={600}>Со вчера и раньше — не сделано</Text>
          <Group gap="xs">
            <Button size="xs" variant="light" onClick={() => move(plan.today)}>
              Все на сегодня
            </Button>
            <Button size="xs" variant="subtle" color="gray" onClick={() => move(null)}>
              Все в «когда-нибудь»
            </Button>
          </Group>
        </Group>
        <Group gap="xs" align="stretch">
          {plan.overdue.map((task) => (
            <div key={task.id} style={{ width: COLUMN_WIDTH }}>
              <PlanCard task={task} today={plan.today} onOpen={onOpen} />
            </div>
          ))}
        </Group>
      </Stack>
    </Paper>
  );
}

// План на неделю: «когда-нибудь» и семь дней вперёд, задачи перетаскиваются между колонками.
export function PlanPage() {
  const plan = usePlan();
  const [openTaskId, setOpenTaskId] = useState<number | null>(null);

  return (
    <Stack gap="lg">
      <Stack gap={4}>
        <Title order={2}>План</Title>
        <Text c="dimmed" size="sm">
          Перетаскивай задачи по дням или выбирай день в меню «⋯». План — намерение: XP даёт только
          сделанное. В боте — /today.
        </Text>
      </Stack>

      {plan.isError && (
        <Alert color="red" title="Не удалось загрузить план">
          {plan.error.message}
        </Alert>
      )}
      {plan.isPending && <Skeleton h={360} />}
      {plan.data && (
        <>
          <EnergyHint plan={plan.data} />
          <Overdue plan={plan.data} onOpen={setOpenTaskId} />
          <ScrollArea type="auto" offsetScrollbars>
            <Group gap="sm" wrap="nowrap" align="flex-start" pb="xs">
              <Column
                title="Когда-нибудь"
                subtitle={
                  <Text size="xs" c="dimmed">
                    бэклог без дня · {plan.data.unplanned.length}
                  </Text>
                }
                day={null}
                tasks={plan.data.unplanned}
                today={plan.data.today}
                onOpen={setOpenTaskId}
              />
              {plan.data.days.map((day) => (
                <Column
                  key={day.day}
                  title={planDayLabel(day.day, plan.data.today)}
                  subtitle={<Load minutes={day.load_min} xp={day.load_xp} norm={plan.data.norm_min} />}
                  day={day.day}
                  tasks={day.tasks}
                  today={plan.data.today}
                  weekend={isWeekend(day.day)}
                  onOpen={setOpenTaskId}
                />
              ))}
            </Group>
          </ScrollArea>
        </>
      )}

      <TaskDrawer taskId={openTaskId} onClose={() => setOpenTaskId(null)} onPlanned={() => setOpenTaskId(null)} />
    </Stack>
  );
}
