import { Alert, Anchor, Paper, SimpleGrid, Stack, Text, Title } from "@mantine/core";
import { Link } from "react-router";

import { useGoals } from "../api/goals";
import { StatItem } from "../components/StatItem";
import { formatMinutes } from "../lib/format";

export function DashboardPage() {
  const goals = useGoals();
  const totals = (goals.data ?? []).reduce(
    (sum, goal) => ({
      minutes: sum.minutes + goal.stats.minutes,
      xp: sum.xp + goal.stats.xp,
      done: sum.done + goal.stats.done_tasks,
    }),
    { minutes: 0, xp: 0, done: 0 },
  );

  return (
    <Stack gap="lg">
      <Title order={2}>Дашборд</Title>
      {goals.isError && (
        <Alert color="red" title="Не удалось загрузить данные">
          {goals.error.message}
        </Alert>
      )}
      <Paper withBorder p="lg">
        <SimpleGrid cols={{ base: 2, sm: 4 }}>
          <StatItem label="Целей" value={goals.data?.length ?? "—"} />
          <StatItem label="Время по целям" value={formatMinutes(totals.minutes)} />
          <StatItem label="XP" value={totals.xp} />
          <StatItem label="Задач закрыто" value={totals.done} />
        </SimpleGrid>
      </Paper>
      <Text c="dimmed">
        Здесь появятся уровень, стрик, норма на сегодня и графики, которые можно настраивать. Пока
        загляни в <Anchor component={Link} to="/goals">цели</Anchor>.
      </Text>
    </Stack>
  );
}
