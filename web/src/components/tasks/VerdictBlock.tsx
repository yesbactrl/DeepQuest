import {
  Alert,
  Anchor,
  Button,
  Group,
  Image,
  NumberInput,
  Paper,
  SimpleGrid,
  Stack,
  Table,
  Text,
  Textarea,
  Title,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useState, type ReactNode } from "react";

import { type TaskDetail, useChangeTime, useDispute } from "../../api/tasks";
import { formatMinutes } from "../../lib/format";
import { VERDICT, formatMult, xpSplit } from "../../lib/tasks";
import { useDraft } from "../../lib/drafts";
import { VoiceButton } from "../VoiceButton";

// Сколько ушло на задачу: можно поправить, XP пересчитается тем же вердиктом.
function TimeValue({ task, text }: { task: TaskDetail; text: string }) {
  const change = useChangeTime(task.id);
  const [editing, setEditing] = useState(false);
  const [minutes, setMinutes] = useState<number | string>(task.spent_min);
  if (!editing) {
    return (
      <Group gap="xs" wrap="nowrap">
        <span>{text}</span>
        <Button size="compact-xs" variant="subtle" onClick={() => setEditing(true)}>
          Изменить
        </Button>
      </Group>
    );
  }
  const save = () => {
    if (typeof minutes !== "number" || minutes < 1) return;
    change.mutate(minutes, {
      onSuccess: (result) => {
        setEditing(false);
        notifications.show({
          color: "teal",
          message: `Время ${formatMinutes(minutes)} · ${xpSplit(result.xp_delta, result.stat, result.skill)}`,
        });
      },
      onError: (error) => notifications.show({ color: "red", message: error.message }),
    });
  };
  return (
    <Group gap="xs" wrap="nowrap">
      <NumberInput
        size="xs"
        w={110}
        min={1}
        max={24 * 60}
        step={15}
        allowDecimal={false}
        suffix=" мин"
        value={minutes}
        onChange={setMinutes}
        aria-label="Сколько ушло, минут"
        data-autofocus
      />
      <Button size="xs" loading={change.isPending} onClick={save}>
        Сохранить
      </Button>
      <Button size="xs" variant="subtle" color="gray" onClick={() => setEditing(false)}>
        Отмена
      </Button>
    </Group>
  );
}

function Breakdown({ task }: { task: TaskDetail }) {
  const b = task.breakdown;
  if (!b) return null;
  const rows: [string, ReactNode][] = [
    [
      "Время",
      <TimeValue
        key="time"
        task={task}
        text={
          formatMinutes(b.counted_min) +
          (b.capped ? ` (ушло ${formatMinutes(b.actual_min)}, засчитываю не больше двух оценок)` : "")
        }
      />,
    ],
    ["Ценность задачи", `${formatMult(b.value_mult)}${task.mult_reason ? ` — ${task.mult_reason}` : ""}`],
    [
      "Проверка отчёта",
      `${task.validation?.self_check ? "без агента" : VERDICT[b.verdict].label} ${formatMult(b.validation_mult)}`,
    ],
    ["Пруф", `${b.honor_mode ? "нет" : "есть, бонус за данные"} ${formatMult(b.proof_mult)}`],
    ...(b.weak_mult !== 1
      ? [["Самый слабый стат", `${formatMult(b.weak_mult)} — бонус отстающей цели`] as [string, ReactNode]]
      : []),
  ];
  return (
    <Stack gap={4}>
      <Title order={5}>Почему {b.amount} XP</Title>
      <Table withRowBorders={false} verticalSpacing={4}>
        <Table.Tbody>
          {rows.map(([label, value]) => (
            <Table.Tr key={label}>
              <Table.Td c="dimmed" w={150}>
                {label}
              </Table.Td>
              <Table.Td>{value}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      <Text size="sm" ff="monospace" c="dimmed">
        {b.counted_min} мин × {b.value_mult} × {b.validation_mult} × {b.proof_mult}
        {b.weak_mult !== 1 && ` × ${b.weak_mult}`} = {b.amount} XP
      </Text>
    </Stack>
  );
}

function ReportView({ task }: { task: TaskDetail }) {
  const report = task.report;
  if (!report) return null;
  const images = report.proofs.filter((p) => p.is_image && p.url);
  const links = report.proofs.filter((p) => p.kind === "link" && p.url);
  return (
    <Stack gap="xs">
      <Title order={5}>Отчёт</Title>
      {report.text && <Text style={{ whiteSpace: "pre-line" }}>{report.text}</Text>}
      {images.length > 0 && (
        <SimpleGrid cols={{ base: 2, sm: 3 }} spacing="xs">
          {images.map((proof) => (
            <Anchor key={proof.index} href={proof.url!} target="_blank">
              <Image src={proof.url!} alt={proof.name ?? "скриншот"} h={100} fit="cover" radius="sm" />
            </Anchor>
          ))}
        </SimpleGrid>
      )}
      {links.map((proof) => (
        <Anchor key={proof.index} href={proof.url!} target="_blank" size="sm" style={{ wordBreak: "break-all" }}>
          {proof.url}
        </Anchor>
      ))}
      {report.honor_mode && (
        <Text size="xs" c="dimmed">
          Без пруфа.
        </Text>
      )}
    </Stack>
  );
}

function DisputeForm({ task }: { task: TaskDetail }) {
  const dispute = useDispute(task.id);
  // Черновик: аргумент переживает уход со страницы и обновление вкладки.
  const [argument, setArgument] = useDraft(`dispute:${task.id}`);
  return (
    <Stack gap="xs">
      <Textarea
        label="Не согласен с вердиктом?"
        description="Оспорить можно один раз. Напиши, что агент упустил: факты, ссылки, что именно сделано."
        autosize
        minRows={2}
        value={argument}
        onChange={(e) => setArgument(e.currentTarget.value)}
      />
      {dispute.error && (
        <Alert color="red" variant="light">
          {dispute.error.message}
        </Alert>
      )}
      <Group gap="xs" wrap="nowrap">
        <VoiceButton
          draftKey={`dispute:${task.id}`}
          disabled={dispute.isPending}
        />
        <Button
          style={{ flex: 1 }}
          variant="light"
          color="orange"
          loading={dispute.isPending}
          disabled={!argument.trim()}
          onClick={() =>
            dispute.mutate(argument, {
              onSuccess: (result) => {
                setArgument("");
                notifications.show({
                  color: "orange",
                  title: "Пересмотрено",
                  message: `${VERDICT[result.task.validation!.verdict].title} · ${xpSplit(result.xp_delta, result.stat, result.skill)}`,
                });
              },
            })
          }
        >
          Оспорить
        </Button>
      </Group>
    </Stack>
  );
}

export function VerdictBlock({ task }: { task: TaskDetail }) {
  const validation = task.validation;
  if (!validation) return null;
  const verdict = VERDICT[validation.verdict];
  return (
    <Stack gap="lg">
      <Paper withBorder p="md" style={{ borderColor: `var(--mantine-color-${verdict.color}-filled)` }}>
        <Stack gap={6}>
          <Text fw={700} c={verdict.color}>
            {validation.is_dispute ? "Пересмотрено. " : ""}
            {validation.self_check ? "Засчитано без проверки" : verdict.title} · {task.xp} XP
          </Text>
          {validation.comment && <Text>{validation.comment}</Text>}
          <Text size="sm" c="dimmed">
            {validation.reason}
          </Text>
        </Stack>
      </Paper>
      <Breakdown task={task} />
      <ReportView task={task} />
      {task.can_dispute && <DisputeForm task={task} />}
    </Stack>
  );
}

export { ReportView };
