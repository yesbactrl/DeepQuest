import {
  ActionIcon,
  Alert,
  Button,
  FileButton,
  Group,
  Image,
  NumberInput,
  Paper,
  SimpleGrid,
  Stack,
  Text,
  Textarea,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconPhotoPlus, IconX } from "@tabler/icons-react";
import { useEffect, useMemo, useState, type ClipboardEvent } from "react";

import { type TaskDetail, useReport } from "../../api/tasks";
import { formatMinutes } from "../../lib/format";
import { VERDICT, awardMessage } from "../../lib/tasks";
import { useDraft } from "../../lib/drafts";
import { VoiceButton } from "../VoiceButton";

const MAX_FILES = 5;

function Previews({ files, onRemove }: { files: File[]; onRemove: (index: number) => void }) {
  const urls = useMemo(() => files.map((file) => URL.createObjectURL(file)), [files]);
  useEffect(() => () => urls.forEach((url) => URL.revokeObjectURL(url)), [urls]);
  if (files.length === 0) return null;
  return (
    <SimpleGrid cols={{ base: 2, sm: 3 }} spacing="xs">
      {files.map((file, index) => (
        <Paper key={urls[index]} withBorder pos="relative" style={{ overflow: "hidden" }}>
          <Image src={urls[index]} alt={file.name} h={90} fit="cover" />
          <ActionIcon
            size="sm"
            color="dark"
            variant="filled"
            pos="absolute"
            top={4}
            right={4}
            aria-label="Убрать скриншот"
            onClick={() => onRemove(index)}
          >
            <IconX size={12} />
          </ActionIcon>
        </Paper>
      ))}
    </SimpleGrid>
  );
}

// Отчёт: что сделал и пруф. Скриншот можно вставить прямо в поле через ⌘+V.
export function ReportForm({ task }: { task: TaskDetail }) {
  const report = useReport(task.id);
  // Черновик: отчёт переживает уход со страницы и обновление вкладки.
  const [text, setText] = useDraft(`report:${task.id}`);
  // Таймер не обязателен: без него предлагаем оценку, и её можно поправить.
  const [spent, setSpent] = useState<number | string>(task.spent_min || task.estimate_min || "");
  const [files, setFiles] = useState<File[]>([]);

  function addFiles(added: File[]) {
    const images = added.filter((file) => file.type.startsWith("image/"));
    setFiles((current) => [...current, ...images].slice(0, MAX_FILES));
  }

  function onPaste(event: ClipboardEvent<HTMLTextAreaElement>) {
    const pasted = Array.from(event.clipboardData.files);
    if (pasted.length > 0) {
      event.preventDefault();
      addFiles(pasted);
    }
  }

  function submit(selfCheck: boolean) {
    report.mutate(
      { text, files, spentMin: typeof spent === "number" && spent >= 1 ? spent : null, selfCheck },
      {
        onSuccess: (result) => {
          // Отчёт сохранён на сервере (даже если агент недоступен) — черновик больше не нужен.
          setText("");
          if (result.agent_failed) return;
          const verdict = result.task.validation?.verdict;
          notifications.show({
            color: verdict ? VERDICT[verdict].color : "teal",
            title: selfCheck ? "Засчитано без проверки" : verdict ? VERDICT[verdict].title : "Проверено",
            message: awardMessage(result),
            style: { whiteSpace: "pre-line" },
          });
        },
      },
    );
  }

  const hasLink = /https?:\/\//.test(text);
  return (
    <Stack gap="sm">
      <NumberInput
        label="Сколько ушло, минут"
        description={
          task.spent_min
            ? `По таймеру ${formatMinutes(task.spent_min)}. Ушло иначе — поправь.`
            : "Таймер не запускался — подставил оценку. Ушло иначе — поправь."
        }
        min={1}
        max={24 * 60}
        step={15}
        allowDecimal={false}
        value={spent}
        onChange={setSpent}
        disabled={report.isPending}
        w={{ base: "100%", sm: 320 }}
      />
      <Textarea
        label="Что получилось?"
        description="Что сделал и что понял. Скриншот можно вставить прямо сюда через ⌘+V"
        placeholder="Например: запустил кампанию на $20, первые 300 показов, CTR 1.2%"
        autosize
        minRows={3}
        value={text}
        onChange={(e) => setText(e.currentTarget.value)}
        onPaste={onPaste}
        disabled={report.isPending}
      />
      <Previews files={files} onRemove={(i) => setFiles((current) => current.filter((_, j) => j !== i))} />
      <Group justify="space-between">
        <Group gap="xs">
          <FileButton onChange={addFiles} accept="image/png,image/jpeg,image/gif,image/webp" multiple>
            {(props) => (
              <Button
                {...props}
                variant="default"
                leftSection={<IconPhotoPlus size={16} />}
                disabled={files.length >= MAX_FILES || report.isPending}
              >
                Скриншот
              </Button>
            )}
          </FileButton>
          <VoiceButton
            draftKey={`report:${task.id}`}
            disabled={report.isPending}
          />
        </Group>
        <Group gap="xs">
          {/* Без агента: задача засчитывается сразу, отчёт и пруф необязательны. */}
          <Button
            variant="default"
            onClick={() => submit(true)}
            loading={report.isPending && report.variables?.selfCheck === true}
            disabled={report.isPending}
          >
            Засчитать без проверки
          </Button>
          <Button
            onClick={() => submit(false)}
            loading={report.isPending && !report.variables?.selfCheck}
            disabled={(!text.trim() && files.length === 0) || report.isPending}
          >
            Сдать на проверку
          </Button>
        </Group>
      </Group>
      <Text size="xs" c="dimmed">
        {report.isPending && !report.variables?.selfCheck
          ? "Агент проверяет отчёт — обычно 5–10 секунд"
          : files.length === 0 && !hasLink
            ? "Пруф необязателен. Скриншот или ссылка — для истории и +10% к XP."
            : "Пруф есть: ×1.1 к XP."}
      </Text>
      {report.error && (
        <Alert color="red" variant="light">
          {report.error.message}
        </Alert>
      )}
    </Stack>
  );
}
