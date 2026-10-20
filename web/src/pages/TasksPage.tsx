import { Paper, Stack, Text, Title } from "@mantine/core";

export function TasksPage() {
  return (
    <Stack gap="lg">
      <Title order={2}>Задачи</Title>
      <Paper withBorder p="lg">
        <Text>
          Экран задач — следующий шаг: мысль через агента, бэклог, таймер и отчёты. Пока задачи
          добавляются в Telegram: просто напиши мысль боту @DeepQuestBot.
        </Text>
      </Paper>
    </Stack>
  );
}
