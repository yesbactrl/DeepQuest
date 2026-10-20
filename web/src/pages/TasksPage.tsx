import { Group, SegmentedControl, Select, Stack, Text, Title } from "@mantine/core";
import { useSearchParams } from "react-router";

import { useGoals } from "../api/goals";
import { type PlanOutcome, useTasks } from "../api/tasks";
import { PlanBox } from "../components/tasks/PlanBox";
import { TaskDrawer } from "../components/tasks/TaskDrawer";
import { TaskList } from "../components/tasks/TaskList";
import { FILTERS } from "../lib/tasks";

const EMPTY: Record<string, string> = {
  work: "В работе пусто. Напиши мысль выше — агент оформит задачу, а ты сохранишь её в бэклог.",
  drafts: "Черновиков нет.",
  done: "Закрытых задач пока нет.",
  all: "Задач пока нет.",
};

// Фильтры и открытая задача живут в адресе: ссылку из шапки (таймер) можно открыть сразу.
export function TasksPage() {
  const [params, setParams] = useSearchParams();
  const filter = FILTERS.find((f) => f.value === params.get("filter")) ?? FILTERS[0];
  const goalId = params.get("goal") ? Number(params.get("goal")) : null;
  const openTaskId = params.get("task") ? Number(params.get("task")) : null;
  const goals = useGoals();
  const tasks = useTasks(filter.statuses, goalId);

  function update(changes: Record<string, string | null>) {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(changes)) {
      if (value === null) next.delete(key);
      else next.set(key, value);
    }
    setParams(next, { replace: true });
  }

  function onPlanned(outcome: PlanOutcome) {
    // Один черновик или вопрос — сразу открываем; несколько — показываем списком.
    const single = outcome.tasks.length === 1 ? String(outcome.tasks[0].id) : null;
    update({ filter: "drafts", task: single });
  }

  const goalOptions = (goals.data ?? []).map((g) => ({ value: String(g.id), label: g.title }));

  return (
    <Stack gap="lg">
      <Stack gap={4}>
        <Title order={2}>Задачи</Title>
        <Text c="dimmed" size="sm">
          Мысль → агент оформляет карточку → бэклог → таймер → отчёт → XP.
        </Text>
      </Stack>

      <PlanBox onPlanned={onPlanned} />

      <Group justify="space-between">
        <SegmentedControl
          data={FILTERS.map((f) => ({ value: f.value, label: f.label }))}
          value={filter.value}
          onChange={(value) => update({ filter: value })}
        />
        <Select
          placeholder="Все цели"
          data={goalOptions}
          value={goalId === null ? null : String(goalId)}
          onChange={(value) => update({ goal: value })}
          clearable
          w={220}
        />
      </Group>

      <TaskList
        tasks={tasks.data}
        loading={tasks.isPending}
        empty={EMPTY[filter.value]}
        onOpen={(id) => update({ task: String(id) })}
      />

      <TaskDrawer taskId={openTaskId} onClose={() => update({ task: null })} onPlanned={onPlanned} />
    </Stack>
  );
}
