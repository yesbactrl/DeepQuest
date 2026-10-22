import { ActionIcon, Badge, Button, Group, Menu, Paper, Stack, Text, Tooltip } from "@mantine/core";
import { modals } from "@mantine/modals";
import { notifications } from "@mantine/notifications";
import { IconDots, IconPencil, IconRefresh, IconTrash } from "@tabler/icons-react";

import { type DiaryEntry, useAnalyzeEntry, useDeleteEntry, useEditEntry } from "../../api/diary";
import { useGoals } from "../../api/goals";
import { PART_OF_DAY, SCALES, entryTime, formatScore, scoreColor } from "../../lib/diary";
import { SphereNotes } from "./Spheres";

export function ScoreBadges({
  values,
}: {
  values: { mood: number | null; energy: number | null; drive: number | null };
}) {
  return (
    <Group gap={6}>
      {SCALES.map((scale) => {
        const value = values[scale.key];
        if (value === null) return null;
        return (
          <Tooltip key={scale.key} label={`${scale.label}: ${formatScore(value)} из 5`}>
            <Badge variant="light" color={scoreColor(value)} size="sm" tt="none">
              {scale.icon} {formatScore(value)}
            </Badge>
          </Tooltip>
        );
      })}
    </Group>
  );
}

export function EntryCard({ entry, onEdit }: { entry: DiaryEntry; onEdit: (entry: DiaryEntry) => void }) {
  const analyze = useAnalyzeEntry(entry.id);
  const remove = useDeleteEntry(entry.id);
  const goals = useGoals();
  const edit = useEditEntry(entry.id);

  // Быстрая правка оценки сферы прямо в ленте: остальные сферы отправляются как есть.
  const setSphereScore = (goalId: number, score: number | null) =>
    edit.mutate(
      {
        spheres: entry.spheres.map((s) => ({
          goal_id: s.goal_id,
          score: s.goal_id === goalId ? (score ?? 0) : (s.score ?? 0),
          good: s.good ?? "",
          bad: s.bad ?? "",
        })),
      },
      { onError: (error) => notifications.show({ color: "red", message: error.message }) },
    );

  const runAnalysis = () =>
    analyze.mutate(undefined, {
      onSuccess: (result) =>
        result.agent_failed &&
        notifications.show({ color: "yellow", message: "Агент всё ещё недоступен. Попробуй позже." }),
      onError: (error) => notifications.show({ color: "red", message: error.message }),
    });

  const confirmDelete = () =>
    modals.openConfirmModal({
      title: "Удалить запись?",
      children: <Text size="sm">Запись пропадёт из дневника и из статистики.</Text>,
      labels: { confirm: "Удалить", cancel: "Оставить" },
      confirmProps: { color: "red" },
      onConfirm: () => remove.mutate(),
    });

  return (
    <Paper withBorder p="sm">
      <Stack gap={6}>
        <Group justify="space-between" wrap="nowrap" align="flex-start">
          <Stack gap={2} style={{ minWidth: 0 }}>
            <Text size="xs" c="dimmed">
              {entryTime(entry)} · {PART_OF_DAY[entry.part_of_day]}
              {entry.edited && " · поправлено вручную"}
            </Text>
            {entry.summary && <Text fw={500}>{entry.summary}</Text>}
            <Text size="sm" c={entry.summary ? "dimmed" : undefined} style={{ whiteSpace: "pre-line" }}>
              {entry.text}
            </Text>
          </Stack>
          <Menu position="bottom-end" withinPortal>
            <Menu.Target>
              <ActionIcon variant="subtle" color="gray" aria-label="Действия с записью">
                <IconDots size={18} />
              </ActionIcon>
            </Menu.Target>
            <Menu.Dropdown>
              <Menu.Item leftSection={<IconPencil size={16} />} onClick={() => onEdit(entry)}>
                Изменить
              </Menu.Item>
              <Menu.Item leftSection={<IconRefresh size={16} />} onClick={runAnalysis}>
                Разобрать заново
              </Menu.Item>
              <Menu.Divider />
              <Menu.Item leftSection={<IconTrash size={16} />} color="red" onClick={confirmDelete}>
                Удалить
              </Menu.Item>
            </Menu.Dropdown>
          </Menu>
        </Group>

        <ScoreBadges values={entry} />
        <SphereNotes spheres={entry.spheres} goals={goals.data ?? []} onScore={setSphereScore} />
        {(entry.emotions.length > 0 || entry.factors.length > 0) && (
          <Group gap={4}>
            {entry.emotions.map((emotion) => (
              <Badge key={`e-${emotion}`} variant="dot" color="violet" size="sm" tt="none">
                {emotion}
              </Badge>
            ))}
            {entry.factors.map((factor) => (
              <Badge key={`f-${factor}`} variant="outline" color="gray" size="sm" tt="none">
                {factor}
              </Badge>
            ))}
          </Group>
        )}

        {entry.status !== "done" && (
          <Group gap="xs">
            <Text size="xs" c="dimmed">
              {entry.status === "failed" ? "Агент не разобрал запись." : "Без разбора агентом."}
            </Text>
            <Button size="compact-xs" variant="light" loading={analyze.isPending} onClick={runAnalysis}>
              Разобрать
            </Button>
          </Group>
        )}
      </Stack>
    </Paper>
  );
}
