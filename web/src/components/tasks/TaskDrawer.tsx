import {
  Alert,
  Badge,
  Blockquote,
  Button,
  Divider,
  Drawer,
  Group,
  Loader,
  Select,
  SimpleGrid,
  Stack,
  Text,
  Textarea,
  Title,
} from "@mantine/core";
import { modals } from "@mantine/modals";
import { notifications } from "@mantine/notifications";
import {
  IconCheck,
  IconPencil,
  IconPlayerPause,
  IconPlayerPlay,
  IconSparkles,
} from "@tabler/icons-react";
import { useState, type ReactNode } from "react";

import {
  type PlanOutcome,
  type SimpleAction,
  type TaskDetail,
  useClarify,
  useRecheck,
  useRevise,
  useStart,
  useTask,
  useTaskAction,
} from "../../api/tasks";
import { useSummary } from "../../api/dashboard";
import { useSchedule } from "../../api/plan";
import { formatMinutes } from "../../lib/format";
import { ACTIVE_STATUSES, scheduleOptions } from "../../lib/plan";
import { STATUS, formatMult, taskXp } from "../../lib/tasks";
import { formatClock, formatTime, useNow } from "../../lib/time";
import { StatItem } from "../StatItem";
import { useDraft } from "../../lib/drafts";
import { VoiceButton } from "../VoiceButton";
import { ReportForm } from "./ReportForm";
import { TaskEditForm } from "./TaskEditForm";
import { VerdictBlock } from "./VerdictBlock";

const showError = (error: Error) => notifications.show({ color: "red", message: error.message });

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <Stack gap={2}>
      <Text size="xs" c="dimmed" tt="uppercase" fw={600}>
        {label}
      </Text>
      <Text>{children}</Text>
    </Stack>
  );
}

// Когда делать: день в плане или «когда-нибудь». Только у задач из бэклога и в работе.
function WhenSelect({ task }: { task: TaskDetail }) {
  const schedule = useSchedule();
  const today = useSummary().data?.streak.today;
  if (!today || !ACTIVE_STATUSES.has(task.status)) return null;
  return (
    <Stack gap={2}>
      <Text size="xs" c="dimmed" tt="uppercase" fw={600}>
        Когда
      </Text>
      <Select
        size="xs"
        w={200}
        aria-label="Когда делать"
        data={scheduleOptions(today, task.planned_for)}
        value={task.planned_for ?? ""}
        allowDeselect={false}
        disabled={schedule.isPending}
        onChange={(value) =>
          schedule.mutate(
            { id: task.id, day: value || null },
            { onError: (error) => notifications.show({ color: "red", message: error.message }) },
          )
        }
      />
    </Stack>
  );
}

function Summary({ task }: { task: TaskDetail }) {
  const xp = taskXp(task);
  return (
    <Stack gap="sm">
      {task.expected_result && <Field label="Результат">{task.expected_result}</Field>}
      <SimpleGrid cols={{ base: 2, sm: 3 }}>
        <Field label="Цель">{task.goal_path ?? "не выбрана"}</Field>
        <Field label="Оценка">
          {task.estimate_min !== null ? formatMinutes(task.estimate_min) : "нет оценки"}
        </Field>
        {/* Как в квадратике списка: у закрытой — начисленное, иначе — оценка × множитель. */}
        <Field label={task.status === "done" || task.status === "rejected" ? "Начислено" : "Принесёт"}>
          {xp !== null ? `${xp > 0 ? "+" : ""}${xp} XP` : "нет оценки"}
        </Field>
      </SimpleGrid>
      {task.value_mult !== null && (
        <Field label="Множитель">
          {formatMult(task.value_mult)}
          {task.mult_reason ? ` — ${task.mult_reason}` : ""}
        </Field>
      )}
      <WhenSelect task={task} />
    </Stack>
  );
}

function ReviseBox({ task }: { task: TaskDetail }) {
  const revise = useRevise(task.id);
  const [correction, setCorrection] = useDraft(`revise:${task.id}`);
  const run = (text: string | null) =>
    revise.mutate(text, {
      onSuccess: (result) => {
        if (result.agent_failed) {
          notifications.show({ color: "yellow", message: "Агент сейчас недоступен, карточка прежняя." });
        } else {
          setCorrection("");
          notifications.show({ color: "teal", message: "Агент обновил карточку" });
        }
      },
      onError: showError,
    });
  return (
    <Stack gap="xs">
      <Textarea
        placeholder="Поправить словами: «не 2 часа, а 4», «это к цели Рилсы»…"
        autosize
        minRows={1}
        value={correction}
        onChange={(e) => setCorrection(e.currentTarget.value)}
        disabled={revise.isPending}
      />
      <Group gap="xs">
        <VoiceButton
          size={30}
          draftKey={`revise:${task.id}`}
          disabled={revise.isPending}
        />
        <Button
          size="xs"
          variant="light"
          leftSection={<IconSparkles size={14} />}
          loading={revise.isPending && revise.variables !== null}
          disabled={!correction.trim()}
          onClick={() => run(correction)}
        >
          Поправить через агента
        </Button>
        {!task.estimate_min && (
          <Button
            size="xs"
            variant="subtle"
            loading={revise.isPending && revise.variables === null}
            onClick={() => run(null)}
          >
            Оценить заново
          </Button>
        )}
      </Group>
    </Stack>
  );
}

function ClarifyBox({ task, onPlanned }: { task: TaskDetail; onPlanned: (o: PlanOutcome) => void }) {
  const clarify = useClarify(task.id);
  const [answer, setAnswer] = useDraft(`clarify:${task.id}`);
  return (
    <Stack gap="sm">
      <Alert color="yellow" title="Агент спрашивает">
        {task.clarify_question}
      </Alert>
      <Textarea
        placeholder="Твой ответ"
        autosize
        minRows={2}
        value={answer}
        onChange={(e) => setAnswer(e.currentTarget.value)}
      />
      <Group justify="flex-end" gap="xs">
        <VoiceButton
          draftKey={`clarify:${task.id}`}
          disabled={clarify.isPending}
        />
        <Button
          loading={clarify.isPending}
          disabled={!answer.trim()}
          onClick={() =>
            clarify.mutate(answer, {
              onSuccess: (outcome) => {
                setAnswer("");
                onPlanned(outcome);
              },
              onError: showError,
            })
          }
        >
          Ответить
        </Button>
      </Group>
    </Stack>
  );
}

function RunningClock({ task, fetchedAt }: { task: TaskDetail; fetchedAt: number }) {
  const now = useNow();
  const seconds = task.spent_min * 60 + (now - fetchedAt) / 1000;
  return (
    <Stack gap={0} align="center" py="sm">
      <Text size="2.4rem" fw={700} ff="monospace">
        {formatClock(seconds)}
      </Text>
      {task.running_since && (
        <Text size="sm" c="dimmed">
          таймер идёт с {formatTime(task.running_since)}
        </Text>
      )}
    </Stack>
  );
}

function Actions({ task, onPlanned }: { task: TaskDetail; onPlanned: (o: PlanOutcome) => void }) {
  const action = useTaskAction(task.id);
  const start = useStart(task.id);
  const recheck = useRecheck(task.id);
  const act = (name: SimpleAction, message?: string) =>
    action.mutate(name, {
      onSuccess: () => message && notifications.show({ color: "teal", message }),
      onError: showError,
    });
  const busy = (name: SimpleAction) => action.isPending && action.variables === name;
  const confirmCancel = (title: string) =>
    modals.openConfirmModal({
      title,
      children: <Text size="sm">«{task.title}» пропадёт из списков. Это нельзя отменить.</Text>,
      labels: { confirm: "Да", cancel: "Оставить" },
      confirmProps: { color: "red" },
      onConfirm: () => act("cancel"),
    });
  const startButton = (label: string) => (
    <Button
      leftSection={<IconPlayerPlay size={16} />}
      loading={start.isPending}
      disabled={!task.estimate_min}
      onClick={() =>
        start.mutate(undefined, {
          onSuccess: (result) =>
            result.paused_task_id &&
            notifications.show({ message: "Предыдущая задача встала на паузу", color: "gray" }),
          onError: showError,
        })
      }
    >
      {label}
    </Button>
  );
  const doneButton = (
    <Button variant="light" color="teal" leftSection={<IconCheck size={16} />} loading={busy("done")} onClick={() => act("done")}>
      Готово
    </Button>
  );

  switch (task.status) {
    case "clarifying":
      return <ClarifyBox task={task} onPlanned={onPlanned} />;
    case "draft":
      return (
        <Stack gap="md">
          <Group>
            <Button loading={busy("save")} disabled={!task.estimate_min} onClick={() => act("save", "Сохранено в бэклог")}>
              Сохранить в бэклог
            </Button>
            <Button variant="subtle" color="red" onClick={() => confirmCancel("Отменить черновик?")}>
              Отменить
            </Button>
          </Group>
          <ReviseBox task={task} />
        </Stack>
      );
    case "open":
      return (
        <Stack gap="md">
          <Group>
            {startButton(task.spent_min ? "Продолжить" : "Старт")}
            {doneButton}
            <Button variant="subtle" color="red" onClick={() => confirmCancel("Убрать задачу из бэклога?")}>
              Убрать
            </Button>
          </Group>
          <ReviseBox task={task} />
        </Stack>
      );
    case "running":
      return (
        <Group>
          <Button variant="default" leftSection={<IconPlayerPause size={16} />} loading={busy("pause")} onClick={() => act("pause")}>
            Пауза
          </Button>
          {doneButton}
        </Group>
      );
    case "awaiting_report":
      return task.report && !task.validation ? (
        <Alert color="yellow" title="Отчёт ждёт проверки">
          <Stack gap="xs" align="flex-start">
            <Text size="sm">Когда отчёт сдавали, агент был недоступен.</Text>
            <Button size="xs" loading={recheck.isPending} onClick={() => recheck.mutate(undefined, { onError: showError })}>
              Проверить ещё раз
            </Button>
          </Stack>
        </Alert>
      ) : (
        <ReportForm task={task} />
      );
    case "done":
    case "rejected":
      return <VerdictBlock task={task} />;
    case "cancelled":
      return <Text c="dimmed">Задача отменена.</Text>;
  }
}

const EDITABLE = new Set(["draft", "open", "running"]);

function Body({ task, fetchedAt, onPlanned }: { task: TaskDetail; fetchedAt: number; onPlanned: (o: PlanOutcome) => void }) {
  const [editing, setEditing] = useState(false);
  const status = STATUS[task.status];
  return (
    <Stack gap="lg">
      <Stack gap="xs">
        <Group justify="space-between">
          <Badge color={status.color} variant="light">
            {status.label}
          </Badge>
          {EDITABLE.has(task.status) && !editing && (
            <Button size="xs" variant="subtle" leftSection={<IconPencil size={14} />} onClick={() => setEditing(true)}>
              Изменить
            </Button>
          )}
        </Group>
        {!editing && <Title order={3}>{task.title}</Title>}
      </Stack>

      {editing ? <TaskEditForm task={task} onDone={() => setEditing(false)} /> : <Summary task={task} />}

      {(task.spent_min > 0 || task.xp !== 0) && task.status !== "running" && (
        <SimpleGrid cols={2}>
          <StatItem label="Потрачено" value={formatMinutes(task.spent_min)} />
          <StatItem label="XP" value={task.xp} />
        </SimpleGrid>
      )}
      {task.status === "running" && <RunningClock task={task} fetchedAt={fetchedAt} />}

      <Divider />
      <Actions task={task} onPlanned={onPlanned} />

      <Blockquote color="gray" p="sm" mt="md">
        <Text size="xs" c="dimmed" mb={4}>
          Что ты написал
        </Text>
        <Text size="sm" style={{ whiteSpace: "pre-line" }}>
          {task.source_text}
        </Text>
      </Blockquote>
    </Stack>
  );
}

export function TaskDrawer({
  taskId,
  onClose,
  onPlanned,
}: {
  taskId: number | null;
  onClose: () => void;
  onPlanned: (outcome: PlanOutcome) => void;
}) {
  const task = useTask(taskId);
  return (
    <Drawer opened={taskId !== null} onClose={onClose} position="right" size="lg" title="Задача">
      {task.isPending && taskId !== null && <Loader />}
      {task.isError && (
        <Alert color="red" title="Не удалось загрузить задачу">
          {task.error.message}
        </Alert>
      )}
      {task.data && (
        <Body key={task.data.id} task={task.data} fetchedAt={task.dataUpdatedAt} onPlanned={onPlanned} />
      )}
    </Drawer>
  );
}
