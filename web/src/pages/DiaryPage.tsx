import {
  Alert,
  Button,
  Checkbox,
  Group,
  Paper,
  Skeleton,
  Stack,
  Text,
  Textarea,
  Title,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconCheck, IconNotebook } from "@tabler/icons-react";
import { useState, type KeyboardEvent } from "react";

import { type DiaryDay, type DiaryEntry, useAddEntry, useDiary } from "../api/diary";
import { useSummary } from "../api/dashboard";
import { useGoals } from "../api/goals";
import { SphereChips } from "../components/diary/Spheres";
import { VoiceButton, appendText } from "../components/VoiceButton";
import { EntryCard, ScoreBadges } from "../components/diary/EntryCard";
import { EntryEditModal } from "../components/diary/EntryEditModal";
import { SCALES, dayLabel, formatScore } from "../lib/diary";
import { formatMinutes } from "../lib/format";

function DiaryInput() {
  const add = useAddEntry();
  const goals = useGoals();
  const [text, setText] = useState("");
  const [privateEntry, setPrivateEntry] = useState(false);
  // Сферы, которые отметил сам: про них агент напишет обязательно. Не отметил — разложит сам.
  const [goalIds, setGoalIds] = useState<number[]>([]);

  function submit() {
    const value = text.trim();
    if (!value || add.isPending) return;
    add.mutate(
      { text: value, analyze: !privateEntry, goalIds },
      {
        onSuccess: (result) => {
          setText("");
          setGoalIds([]);
          if (result.agent_failed) {
            notifications.show({
              color: "yellow",
              message: `Записал · +${result.xp} XP. Агент сейчас недоступен — разбери запись позже.`,
            });
            return;
          }
          const { entry } = result;
          const scores = SCALES.filter((s) => entry[s.key] !== null)
            .map((s) => `${s.icon} ${formatScore(entry[s.key]!)}`)
            .join("  ");
          notifications.show({
            color: "teal",
            title: `Записал · +${result.xp} XP`,
            message: scores || entry.summary || "",
          });
        },
        onError: (error) => notifications.show({ color: "red", message: error.message }),
      },
    );
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
      event.preventDefault();
      submit();
    }
  }

  return (
    <Paper withBorder p="md">
      <Stack gap="xs">
        {(goals.data?.length ?? 0) > 0 && (
          <Group gap="xs" wrap="nowrap">
            <Text size="xs" c="dimmed" style={{ flexShrink: 0 }}>
              Про что:
            </Text>
            <SphereChips goals={goals.data ?? []} selected={goalIds} onChange={setGoalIds} />
          </Group>
        )}
        <Textarea
          placeholder="Как ты? Пара фраз: как начинается, проходит или заканчивается день, что на душе"
          autosize
          minRows={2}
          maxRows={8}
          value={text}
          onChange={(event) => setText(event.currentTarget.value)}
          onKeyDown={onKeyDown}
          disabled={add.isPending}
        />
        <Group justify="space-between">
          <Checkbox
            size="xs"
            label="Не отдавать агенту — оценю сам"
            checked={privateEntry}
            onChange={(event) => setPrivateEntry(event.currentTarget.checked)}
          />
          <Group gap="xs" wrap="nowrap">
            <VoiceButton onText={(spoken) => setText((current) => appendText(current, spoken))} disabled={add.isPending} />
            <Button onClick={submit} loading={add.isPending} disabled={!text.trim()}>
              Записать
            </Button>
          </Group>
        </Group>
        <Text size="xs" c="dimmed">
          {add.isPending
            ? "Агент размечает запись — несколько секунд"
            : "⌘ + Enter — записать. Агент сам оценит настроение, энергию и желание действовать и разложит запись по целям — поправить можно в меню записи."}
        </Text>
      </Stack>
    </Paper>
  );
}

function DayBlock({
  day,
  today,
  normMin,
  onEdit,
}: {
  day: DiaryDay;
  today: string;
  normMin: number;
  onEdit: (entry: DiaryEntry) => void;
}) {
  const normMet = day.focus_min >= normMin;
  return (
    <Stack gap="xs">
      <Group justify="space-between" align="center">
        <Group gap="sm">
          <Title order={4}>{dayLabel(day.day, today)}</Title>
          <ScoreBadges values={day} />
        </Group>
        <Text size="sm" c="dimmed">
          фокус {formatMinutes(day.focus_min)}
          {normMet && <IconCheck size={14} style={{ marginLeft: 4, verticalAlign: "middle" }} aria-label="норма выполнена" />}
          {day.xp !== 0 && ` · ${day.xp > 0 ? "+" : ""}${day.xp} XP`}
        </Text>
      </Group>
      {day.entries.map((entry) => (
        <EntryCard key={entry.id} entry={entry} onEdit={onEdit} />
      ))}
    </Stack>
  );
}

// Дневник состояния: записи, которые агент раскладывает на настроение, энергию и желание
// действовать, рядом с тем, сколько в этот день было работы.
export function DiaryPage() {
  // Фильтр ленты по сфере: пусто — все записи.
  const [filter, setFilter] = useState<number[]>([]);
  const goals = useGoals();
  const diary = useDiary(filter[0] ?? null);
  const summary = useSummary();
  const [editing, setEditing] = useState<DiaryEntry | null>(null);
  const today = summary.data?.streak.today ?? new Date().toISOString().slice(0, 10);

  return (
    <Stack gap="lg">
      <Stack gap={4}>
        <Title order={2}>Дневник</Title>
        <Text c="dimmed" size="sm">
          Пара фраз о том, как ты. Со временем станет видно, что связано с днями, когда ничего не
          хочется. В боте — команда /d.
        </Text>
      </Stack>

      <DiaryInput />

      {(goals.data?.length ?? 0) > 0 && (
        <SphereChips goals={goals.data ?? []} selected={filter} onChange={setFilter} allLabel="Все записи" />
      )}

      {diary.isError && (
        <Alert color="red" title="Не удалось загрузить дневник">
          {diary.error.message}
        </Alert>
      )}
      {diary.isPending && <Skeleton h={200} />}
      {diary.data && diary.data.days.length === 0 && (
        <Paper withBorder p="xl">
          <Stack align="center" gap="xs">
            <IconNotebook size={32} stroke={1.4} />
            <Text c="dimmed" ta="center" maw={460}>
              {filter.length > 0
                ? "Про эту цель записей пока нет."
                : "Записей пока нет. Начни с утра: как спал, какие силы, хочется ли браться за дела."}
            </Text>
          </Stack>
        </Paper>
      )}
      {diary.data?.days.map((day) => (
        <DayBlock key={day.day} day={day} today={today} normMin={diary.data.norm_min} onEdit={setEditing} />
      ))}

      <EntryEditModal entry={editing} onClose={() => setEditing(null)} />
    </Stack>
  );
}
