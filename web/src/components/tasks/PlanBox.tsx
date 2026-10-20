import { Button, Group, Paper, Stack, Text, Textarea } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconSparkles } from "@tabler/icons-react";
import { useState, type KeyboardEvent } from "react";

import { type PlanOutcome, usePlan } from "../../api/tasks";
import { plural } from "../../lib/format";
import { VoiceButton, appendText } from "../VoiceButton";

// Поле «что сделать?»: агент превращает мысль в черновики задач или задаёт вопрос.
export function PlanBox({ onPlanned }: { onPlanned: (outcome: PlanOutcome) => void }) {
  const [text, setText] = useState("");
  const plan = usePlan();

  function submit() {
    const thought = text.trim();
    if (!thought || plan.isPending) return;
    plan.mutate(thought, {
      onSuccess: (outcome) => {
        setText("");
        if (outcome.agent_failed) {
          notifications.show({
            color: "yellow",
            title: "Агент недоступен",
            message: "Мысль сохранена черновиком без оценки: оцени её вручную или попробуй позже.",
          });
        } else if (outcome.question === null) {
          const n = outcome.tasks.length;
          notifications.show({
            color: "teal",
            message: `Оформлено ${n} ${plural(n, "задача", "задачи", "задач")}: проверь черновики`,
          });
        }
        onPlanned(outcome);
      },
      onError: (error) => notifications.show({ color: "red", message: error.message }),
    });
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
        <Textarea
          placeholder="Что хочешь сделать? Пиши или надиктуй как есть, можно несколько дел сразу"
          autosize
          minRows={2}
          maxRows={8}
          value={text}
          onChange={(event) => setText(event.currentTarget.value)}
          onKeyDown={onKeyDown}
          disabled={plan.isPending}
        />
        <Group justify="space-between">
          <Text size="xs" c="dimmed">
            {plan.isPending
              ? "Агент оформляет задачу — обычно 5–10 секунд"
              : "⌘ + Enter — отправить агенту"}
          </Text>
          <Group gap="xs" wrap="nowrap">
            <VoiceButton
              onText={(spoken) => setText((current) => appendText(current, spoken))}
              disabled={plan.isPending}
            />
            <Button
              leftSection={<IconSparkles size={16} />}
              onClick={submit}
              loading={plan.isPending}
              disabled={!text.trim()}
            >
              Оформить
            </Button>
          </Group>
        </Group>
      </Stack>
    </Paper>
  );
}
