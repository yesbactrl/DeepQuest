import { Button, Group, Modal, Rating, Stack, TagsInput, Text, Textarea, TextInput } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useState } from "react";

import { type DiaryEntry, useEditEntry } from "../../api/diary";
import { SCALES, type ScaleKey } from "../../lib/diary";

function Body({ entry, onClose }: { entry: DiaryEntry; onClose: () => void }) {
  const edit = useEditEntry(entry.id);
  const [text, setText] = useState(entry.text);
  const [summary, setSummary] = useState(entry.summary ?? "");
  // 0 — оценки нет: «из записи не понять» или «не знаю».
  const [scores, setScores] = useState<Record<ScaleKey, number>>({
    mood: entry.mood ?? 0,
    energy: entry.energy ?? 0,
    drive: entry.drive ?? 0,
  });
  const [emotions, setEmotions] = useState(entry.emotions);
  const [factors, setFactors] = useState(entry.factors);

  function save() {
    edit.mutate(
      { text, summary, ...scores, emotions, factors },
      {
        onSuccess: () => {
          notifications.show({ color: "teal", message: "Запись обновлена" });
          onClose();
        },
        onError: (error) => notifications.show({ color: "red", message: error.message }),
      },
    );
  }

  return (
    <Stack>
      {SCALES.map((scale) => (
        <Stack key={scale.key} gap={2}>
          <Group justify="space-between">
            <Text size="sm" fw={500}>
              {scale.icon} {scale.label}
            </Text>
            {scores[scale.key] > 0 && (
              <Button size="compact-xs" variant="subtle" color="gray" onClick={() => setScores({ ...scores, [scale.key]: 0 })}>
                Не знаю
              </Button>
            )}
          </Group>
          <Group gap="sm">
            <Rating
              count={5}
              value={scores[scale.key]}
              onChange={(value) => setScores({ ...scores, [scale.key]: value })}
              aria-label={scale.label}
            />
            <Text size="xs" c="dimmed">
              {scale.hint}
            </Text>
          </Group>
        </Stack>
      ))}
      <TagsInput label="Эмоции" placeholder="Например, тревога — Enter" value={emotions} onChange={setEmotions} />
      <TagsInput label="Что повлияло" placeholder="Например, плохой сон — Enter" value={factors} onChange={setFactors} />
      <TextInput label="Суть одной строкой" value={summary} onChange={(e) => setSummary(e.currentTarget.value)} />
      <Textarea label="Запись" autosize minRows={2} value={text} onChange={(e) => setText(e.currentTarget.value)} />
      <Group justify="flex-end">
        <Button variant="default" onClick={onClose}>
          Отмена
        </Button>
        <Button loading={edit.isPending} onClick={save} disabled={!text.trim()}>
          Сохранить
        </Button>
      </Group>
    </Stack>
  );
}

export function EntryEditModal({ entry, onClose }: { entry: DiaryEntry | null; onClose: () => void }) {
  return (
    // Клик мимо окна не закрывает форму: иначе правка молча пропадает.
    <Modal opened={entry !== null} onClose={onClose} title="Запись дневника" size="lg" closeOnClickOutside={false}>
      {entry && <Body key={entry.id} entry={entry} onClose={onClose} />}
    </Modal>
  );
}
