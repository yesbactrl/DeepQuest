import { Alert, Button, Group, NumberInput, Select, Stack, Textarea, TextInput } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useState, type FormEvent } from "react";

import { useGoals } from "../../api/goals";
import { type TaskDetail, useEditTask } from "../../api/tasks";
import { formatMinutes } from "../../lib/format";
import { VALUE_SCALE } from "../../lib/tasks";

const NO_GOAL = "none";

// Ручная правка карточки: агент предлагает оценку, последнее слово за тобой.
export function TaskEditForm({ task, onDone }: { task: TaskDetail; onDone: () => void }) {
  const goals = useGoals();
  const edit = useEditTask(task.id);
  const [title, setTitle] = useState(task.title);
  const [result, setResult] = useState(task.expected_result ?? "");
  const [goal, setGoal] = useState(task.goal_id === null ? NO_GOAL : String(task.goal_id));
  const [estimate, setEstimate] = useState<number | string>(task.estimate_min ?? 60);
  const [mult, setMult] = useState(String(task.value_mult ?? 1));
  const [reason, setReason] = useState(task.mult_reason ?? "");

  const goalOptions = [
    { value: NO_GOAL, label: "Без цели" },
    ...(goals.data ?? []).flatMap((g) => [
      { value: String(g.id), label: g.title },
      ...g.directions.map((d) => ({ value: String(d.id), label: `${g.title} → ${d.title}` })),
    ]),
  ];
  const minutes = typeof estimate === "number" ? estimate : Number.parseInt(estimate, 10);

  function submit(event: FormEvent) {
    event.preventDefault();
    edit.mutate(
      {
        title,
        expected_result: result,
        goal_id: goal === NO_GOAL ? null : Number(goal),
        estimate_min: minutes,
        value_mult: Number(mult),
        mult_reason: reason,
      },
      {
        onSuccess: () => {
          notifications.show({ message: "Карточка обновлена", color: "teal" });
          onDone();
        },
      },
    );
  }

  return (
    <form onSubmit={submit}>
      <Stack gap="sm">
        <TextInput label="Задача" value={title} onChange={(e) => setTitle(e.currentTarget.value)} />
        <Textarea
          label="Ожидаемый результат"
          autosize
          minRows={2}
          value={result}
          onChange={(e) => setResult(e.currentTarget.value)}
        />
        <Select
          label="Цель"
          data={goalOptions}
          value={goal}
          onChange={(value) => setGoal(value ?? NO_GOAL)}
          allowDeselect={false}
        />
        <Group grow align="flex-start">
          <NumberInput
            label="Оценка, минут"
            description={Number.isFinite(minutes) ? formatMinutes(minutes) : " "}
            min={5}
            max={480}
            step={15}
            value={estimate}
            onChange={setEstimate}
          />
          <Select
            label="Множитель ценности"
            data={VALUE_SCALE.map((s) => ({ value: String(s.value), label: s.label }))}
            value={mult}
            onChange={(value) => setMult(value ?? "1")}
            allowDeselect={false}
          />
        </Group>
        <TextInput
          label="Почему такой множитель"
          value={reason}
          onChange={(e) => setReason(e.currentTarget.value)}
        />
        {edit.error && (
          <Alert color="red" variant="light">
            {edit.error.message}
          </Alert>
        )}
        <Group justify="flex-end">
          <Button variant="default" onClick={onDone}>
            Отмена
          </Button>
          <Button type="submit" loading={edit.isPending}>
            Сохранить
          </Button>
        </Group>
      </Stack>
    </form>
  );
}
