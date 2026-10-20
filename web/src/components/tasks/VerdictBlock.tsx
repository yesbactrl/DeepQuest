import {
  Alert,
  Anchor,
  Button,
  Group,
  Image,
  Paper,
  SimpleGrid,
  Stack,
  Table,
  Text,
  Textarea,
  Title,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useState } from "react";

import { type TaskDetail, useDispute } from "../../api/tasks";
import { formatMinutes } from "../../lib/format";
import { VERDICT, formatMult, xpSplit } from "../../lib/tasks";
import { VoiceButton, appendText } from "../VoiceButton";

function Breakdown({ task }: { task: TaskDetail }) {
  const b = task.breakdown;
  if (!b) return null;
  const rows = [
    [
      "Время",
      formatMinutes(b.counted_min) +
        (b.capped ? ` (по таймеру ${formatMinutes(b.actual_min)}, засчитываю не больше двух оценок)` : ""),
    ],
    ["Ценность задачи", `${formatMult(b.value_mult)}${task.mult_reason ? ` — ${task.mult_reason}` : ""}`],
    ["Проверка отчёта", `${VERDICT[b.verdict].label} ${formatMult(b.validation_mult)}`],
    ["Пруф", `${b.honor_mode ? "на честном слове" : "есть"} ${formatMult(b.proof_mult)}`],
    ...(b.weak_mult !== 1 ? [["Самый слабый стат", `${formatMult(b.weak_mult)} — бонус отстающей цели`]] : []),
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
          Без пруфа — «на честном слове».
        </Text>
      )}
    </Stack>
  );
}

function DisputeForm({ task }: { task: TaskDetail }) {
  const dispute = useDispute(task.id);
  const [argument, setArgument] = useState("");
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
          onText={(spoken) => setArgument((current) => appendText(current, spoken))}
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
              onSuccess: (result) =>
                notifications.show({
                  color: "orange",
                  title: "Пересмотрено",
                  message: `${VERDICT[result.task.validation!.verdict].title} · ${xpSplit(result.xp_delta, result.stat, result.skill)}`,
                }),
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
            {verdict.title} · {task.xp} XP
          </Text>
          <Text>{validation.comment}</Text>
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
