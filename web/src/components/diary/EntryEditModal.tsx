import {
  ActionIcon,
  Button,
  Group,
  Modal,
  Paper,
  Rating,
  Select,
  Stack,
  TagsInput,
  Text,
  Textarea,
  TextInput,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconX } from "@tabler/icons-react";
import { useState } from "react";

import { type DiaryEntry, useEditEntry } from "../../api/diary";
import { useGoals } from "../../api/goals";
import { SCALES, type ScaleKey } from "../../lib/diary";

interface SphereDraft {
  goal_id: number;
  // 0 — без оценки.
  score: number;
  good: string;
  bad: string;
}

// Сферы записи: оценка, что радует и что огорчает по каждой цели.
function SpheresEditor({ value, onChange }: { value: SphereDraft[]; onChange: (next: SphereDraft[]) => void }) {
  const goals = useGoals().data ?? [];
  const title = (id: number) => goals.find((goal) => goal.id === id)?.title ?? "Цель в архиве";
  const free = goals.filter((goal) => !value.some((sphere) => sphere.goal_id === goal.id));
  const update = (index: number, changes: Partial<SphereDraft>) =>
    onChange(value.map((sphere, i) => (i === index ? { ...sphere, ...changes } : sphere)));
  return (
    <Stack gap="xs">
      <Text size="sm" fw={500}>
        Сферы
      </Text>
      {value.map((sphere, index) => (
        <Paper key={sphere.goal_id} withBorder p="xs">
          <Stack gap={6}>
            <Group justify="space-between">
              <Group gap="sm">
                <Text size="sm" fw={600}>
                  {title(sphere.goal_id)}
                </Text>
                <Rating count={5} size="sm" value={sphere.score} onChange={(score) => update(index, { score })} />
              </Group>
              <ActionIcon
                size="sm"
                variant="subtle"
                color="gray"
                aria-label={`Убрать сферу ${title(sphere.goal_id)}`}
                onClick={() => onChange(value.filter((_, i) => i !== index))}
              >
                <IconX size={14} />
              </ActionIcon>
            </Group>
            <TextInput
              size="xs"
              placeholder="Что радует"
              value={sphere.good}
              onChange={(e) => update(index, { good: e.currentTarget.value })}
            />
            <TextInput
              size="xs"
              placeholder="Что огорчает"
              value={sphere.bad}
              onChange={(e) => update(index, { bad: e.currentTarget.value })}
            />
          </Stack>
        </Paper>
      ))}
      {free.length > 0 && (
        <Select
          size="xs"
          w={240}
          placeholder="Добавить сферу"
          data={free.map((goal) => ({ value: String(goal.id), label: goal.title }))}
          value={null}
          onChange={(id) => id && onChange([...value, { goal_id: Number(id), score: 0, good: "", bad: "" }])}
        />
      )}
    </Stack>
  );
}

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
  const [spheres, setSpheres] = useState<SphereDraft[]>(
    entry.spheres.map((s) => ({ goal_id: s.goal_id, score: s.score ?? 0, good: s.good ?? "", bad: s.bad ?? "" })),
  );

  function save() {
    edit.mutate(
      { text, summary, ...scores, emotions, factors, spheres },
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
      <SpheresEditor value={spheres} onChange={setSpheres} />
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
