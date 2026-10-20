import {
  ActionIcon,
  Alert,
  Button,
  FileButton,
  Group,
  Image,
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
import { VERDICT, signedXp } from "../../lib/tasks";

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
  const [text, setText] = useState("");
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

  function submit() {
    report.mutate(
      { text, files },
      {
        onSuccess: (result) => {
          if (result.agent_failed) return;
          const verdict = result.task.validation?.verdict;
          notifications.show({
            color: verdict ? VERDICT[verdict].color : "teal",
            title: verdict ? VERDICT[verdict].title : "Проверено",
            message: signedXp(result.xp_delta),
          });
        },
      },
    );
  }

  const hasLink = /https?:\/\//.test(text);
  return (
    <Stack gap="sm">
      <Text size="sm">
        По таймеру: <b>{formatMinutes(task.spent_min)}</b>
        {task.spent_min === 0 && " — таймер не запускался, поэтому XP будет 0"}
      </Text>
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
        <Button onClick={submit} loading={report.isPending} disabled={!text.trim() && files.length === 0}>
          Сдать отчёт
        </Button>
      </Group>
      <Text size="xs" c="dimmed">
        {report.isPending
          ? "Агент проверяет отчёт — обычно 5–10 секунд"
          : files.length === 0 && !hasLink
            ? "Без скриншота или ссылки отчёт засчитается «на честном слове» с ×0.8."
            : "Пруф есть: без понижения за «честное слово»."}
      </Text>
      {report.error && (
        <Alert color="red" variant="light">
          {report.error.message}
        </Alert>
      )}
    </Stack>
  );
}
