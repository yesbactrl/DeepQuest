import { Button, Group, ScrollArea, SegmentedControl, Select, Stack, Text, Title } from "@mantine/core";
import { useSearchParams } from "react-router";

import { type Goal, useGoals } from "../api/goals";
import { type PlanOutcome, useTasks } from "../api/tasks";
import { PlanBox } from "../components/tasks/PlanBox";
import { TaskDrawer } from "../components/tasks/TaskDrawer";
import { TaskList } from "../components/tasks/TaskList";
import { goalIcon, useGoalColor } from "../lib/goalLook";
import { FILTERS, SORTS, type SortValue, sortTasks } from "../lib/tasks";

// Все статусы, кроме отменённых: грузим их одним запросом, а вкладки статусов фильтруют
// список прямо здесь — так у каждой вкладки есть счётчик.
const ALL_STATUSES = FILTERS.find((f) => f.value === "all")!.statuses;

// Ряды «цель» и «направление»: кнопки-чипы, выбранная — залитая.
function GoalRow({
  goals,
  goalId,
  onSelect,
}: {
  goals: Goal[];
  goalId: number | null;
  onSelect: (id: number | null) => void;
}) {
  const toHex = useGoalColor();
  return (
    <ScrollArea type="never">
      {/* Ширина по содержимому: на телефоне кнопки не сжимаются, а ряд листается пальцем. */}
      <Group gap="xs" wrap="nowrap" w="max-content">
        <Button
          size="xs"
          radius="xl"
          color="gray"
          variant={goalId === null ? "filled" : "subtle"}
          onClick={() => onSelect(null)}
        >
          Все цели
        </Button>
        {goals.map((goal) => {
          const Icon = goalIcon(goal.icon);
          return (
            <Button
              key={goal.id}
              size="xs"
              radius="xl"
              color={toHex(goal.color)}
              variant={goalId === goal.id ? "filled" : "light"}
              leftSection={<Icon size={14} />}
              onClick={() => onSelect(goal.id)}
            >
              {goal.title}
            </Button>
          );
        })}
      </Group>
    </ScrollArea>
  );
}

function DirectionRow({
  goal,
  directionId,
  onSelect,
}: {
  goal: Goal;
  directionId: number | null;
  onSelect: (id: number | null) => void;
}) {
  const color = useGoalColor()(goal.color);
  return (
    <ScrollArea type="never">
      <Group gap={6} wrap="nowrap" w="max-content">
        <Button
          size="compact-sm"
          radius="xl"
          color={color}
          variant={directionId === null ? "light" : "subtle"}
          onClick={() => onSelect(null)}
        >
          Вся цель «{goal.title}»
        </Button>
        {goal.directions.map((direction) => (
          <Button
            key={direction.id}
            size="compact-sm"
            radius="xl"
            color={color}
            variant={directionId === direction.id ? "light" : "subtle"}
            onClick={() => onSelect(direction.id)}
          >
            {direction.title}
          </Button>
        ))}
      </Group>
    </ScrollArea>
  );
}

const EMPTY: Record<string, string> = {
  work: "Сейчас ничего не начато. Запусти таймер у задачи из бэклога.",
  backlog: "Бэклог пуст. Напиши мысль выше — агент оформит задачу, а ты сохранишь её в бэклог.",
  drafts: "Черновиков нет.",
  done: "Закрытых задач пока нет.",
  all: "Задач пока нет.",
};

// Фильтры и открытая задача живут в адресе: ссылку из шапки (таймер) можно открыть сразу.
export function TasksPage() {
  const [params, setParams] = useSearchParams();
  // По умолчанию — «В работе», хоть она и не первая по порядку.
  const filter =
    FILTERS.find((f) => f.value === (params.get("filter") ?? "work")) ?? FILTERS[0];
  const goalId = params.get("goal") ? Number(params.get("goal")) : null;
  const directionId = params.get("dir") ? Number(params.get("dir")) : null;
  const sort: SortValue = SORTS.find((s) => s.value === params.get("sort"))?.value ?? "recent";
  const openTaskId = params.get("task") ? Number(params.get("task")) : null;
  const goals = useGoals();
  const goal = goals.data?.find((g) => g.id === goalId) ?? null;
  // Цель — это её задачи вместе с задачами направлений; направление — только его задачи.
  const tasks = useTasks(ALL_STATUSES, directionId ?? goalId);
  const count = (statuses: readonly string[]) =>
    tasks.data?.filter((task) => statuses.includes(task.status)).length;
  const shown = tasks.data?.filter((task) => filter.statuses.includes(task.status));

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

  return (
    <Stack gap="lg">
      <Stack gap={4}>
        <Title order={2}>Задачи</Title>
        <Text c="dimmed" size="sm">
          Мысль → агент оформляет карточку → бэклог → таймер → отчёт → XP.
        </Text>
      </Stack>

      <PlanBox onPlanned={onPlanned} />

      <Stack gap="xs">
        <GoalRow
          goals={goals.data ?? []}
          goalId={goalId}
          onSelect={(id) => update({ goal: id === null ? null : String(id), dir: null })}
        />
        {goal && goal.directions.length > 0 && (
          <DirectionRow
            goal={goal}
            directionId={directionId}
            onSelect={(id) => update({ dir: id === null ? null : String(id) })}
          />
        )}
        <Group justify="space-between">
          {/* На узком экране вкладки прокручиваются, а не обрезаются у края. */}
          <ScrollArea type="never" maw="100%">
            <SegmentedControl
              data={FILTERS.map((f) => {
                const n = count(f.statuses);
                return {
                  value: f.value,
                  label: (
                    <>
                      {f.label}
                      {n !== undefined && (
                        <Text span size="xs" c="dimmed" ml={6}>
                          {n}
                        </Text>
                      )}
                    </>
                  ),
                };
              })}
              value={filter.value}
              onChange={(value) => update({ filter: value })}
            />
          </ScrollArea>
          <Select
            aria-label="Сортировка"
            data={SORTS.map((s) => ({ value: s.value, label: s.label }))}
            value={sort}
            onChange={(value) => update({ sort: value === "recent" ? null : value })}
            allowDeselect={false}
            w={190}
          />
        </Group>
      </Stack>

      <TaskList
        tasks={shown && sortTasks(shown, sort)}
        loading={tasks.isPending}
        empty={EMPTY[filter.value]}
        onOpen={(id) => update({ task: String(id) })}
      />

      <TaskDrawer taskId={openTaskId} onClose={() => update({ task: null })} onPlanned={onPlanned} />
    </Stack>
  );
}
