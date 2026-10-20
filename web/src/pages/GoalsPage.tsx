import { Alert, Button, Group, Paper, SimpleGrid, Skeleton, Stack, Text, Title } from "@mantine/core";
import { modals } from "@mantine/modals";
import { notifications } from "@mantine/notifications";
import { IconPlus, IconTarget } from "@tabler/icons-react";
import { useState } from "react";

import { type Direction, type Goal, useArchiveGoal, useGoals } from "../api/goals";
import { GoalCard } from "../components/goals/GoalCard";
import { type GoalForm, GoalFormModal } from "../components/goals/GoalFormModal";

function EmptyState({ onCreate }: { onCreate: () => void }) {
  return (
    <Paper withBorder p="xl">
      <Stack align="center" gap="sm">
        <IconTarget size={36} stroke={1.4} />
        <Text fw={600}>Целей пока нет</Text>
        <Text c="dimmed" ta="center" maw={460}>
          Заведи 2–4 долгосрочные цели. Агент будет привязывать к ним задачи и по «зачем» оценивать,
          насколько задача реально двигает цель.
        </Text>
        <Button leftSection={<IconPlus size={16} />} onClick={onCreate}>
          Новая цель
        </Button>
      </Stack>
    </Paper>
  );
}

export function GoalsPage() {
  const goals = useGoals();
  const archive = useArchiveGoal();
  const [form, setForm] = useState<GoalForm | null>(null);

  function confirmArchive(target: Goal | Direction, isDirection: boolean) {
    const withDirections = !isDirection && (target as Goal).directions.length > 0;
    modals.openConfirmModal({
      title: "Убрать в архив?",
      children: (
        <Text size="sm">
          «{target.title}» уйдёт в архив{withDirections ? " вместе с направлениями" : ""}. Задачи и XP
          останутся.
        </Text>
      ),
      labels: { confirm: "В архив", cancel: "Отмена" },
      confirmProps: { color: "red" },
      onConfirm: () =>
        archive.mutate(target.id, {
          onSuccess: () => notifications.show({ message: "Убрано в архив", color: "gray" }),
          onError: (error) => notifications.show({ message: error.message, color: "red" }),
        }),
    });
  }

  let content;
  if (goals.isPending) {
    content = (
      <SimpleGrid cols={{ base: 1, lg: 2 }}>
        <Skeleton h={260} />
        <Skeleton h={260} />
      </SimpleGrid>
    );
  } else if (goals.isError) {
    content = (
      <Alert color="red" title="Не удалось загрузить цели">
        {goals.error.message}
      </Alert>
    );
  } else if (goals.data.length === 0) {
    content = <EmptyState onCreate={() => setForm({ mode: "create" })} />;
  } else {
    content = (
      <SimpleGrid cols={{ base: 1, lg: 2 }}>
        {goals.data.map((goal) => (
          <GoalCard
            key={goal.id}
            goal={goal}
            onEdit={(target, isDirection) => setForm({ mode: "edit", target, isDirection })}
            onAddDirection={(parent) => setForm({ mode: "direction", parent })}
            onArchive={confirmArchive}
          />
        ))}
      </SimpleGrid>
    );
  }

  return (
    <Stack gap="lg">
      <Group justify="space-between" align="flex-end">
        <Stack gap={4}>
          <Title order={2}>Цели</Title>
          <Text c="dimmed" size="sm">
            Долгосрочные цели и направления внутри них. Задачи привязываются к ним.
          </Text>
        </Stack>
        {goals.data && goals.data.length > 0 && (
          <Button leftSection={<IconPlus size={16} />} onClick={() => setForm({ mode: "create" })}>
            Новая цель
          </Button>
        )}
      </Group>
      {content}
      <GoalFormModal form={form} onClose={() => setForm(null)} />
    </Stack>
  );
}
