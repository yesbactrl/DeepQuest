import { Alert, Anchor, Card, Group, Progress, Stack, Text, Title } from "@mantine/core";
import { IconCheck, IconScale } from "@tabler/icons-react";
import { Link } from "react-router";

import type { Award, Character } from "../../api/character";
import { plural } from "../../lib/format";
import { xpSplit } from "../../lib/tasks";

const MONTHS = [
  "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
  "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
];

function LastAward({ award }: { award: Award | null }) {
  if (!award) {
    return (
      <Text size="sm" c="dimmed">
        Закрой первую задачу — здесь появится, сколько XP она принесла и в какой стат.
      </Text>
    );
  }
  const correction = award.kind === "correction";
  const title = award.task_title ? `${award.task_title} · ` : "";
  return (
    <Alert
      color={award.amount > 0 ? "teal" : "red"}
      variant="light"
      p="xs"
      icon={correction ? <IconScale size={18} /> : <IconCheck size={18} />}
    >
      <Text size="sm">
        {correction && "Пересмотр: "}
        {title}
        {xpSplit(award.amount, award.stat, award.skill)}
      </Text>
    </Alert>
  );
}

export function CharacterHeader({ character }: { character: Character }) {
  const { total, streak, season } = character.summary;
  const month = MONTHS[Number(season.slice(5, 7)) - 1];
  const gained = total.xp - total.floor_xp;
  const needed = total.next_xp - total.floor_xp;
  return (
    <Card withBorder padding="lg">
      <Stack gap="sm">
        <Group justify="space-between" align="flex-end">
          <Stack gap={0}>
            <Text size="sm" c="dimmed">
              Персонаж · сезон {month}
            </Text>
            <Group gap="sm" align="baseline">
              <Title order={2}>Уровень {total.level}</Title>
              <Anchor component={Link} to="/levels" size="sm">
                Шкала уровней →
              </Anchor>
            </Group>
          </Stack>
          <Stack gap={0} align="flex-end">
            <Text size="sm" c="dimmed">
              Стрик
            </Text>
            <Title order={2} c={streak.paused ? "dimmed" : undefined}>
              {streak.paused ? "на паузе" : `${streak.current} ${plural(streak.current, "день", "дня", "дней")}`}
            </Title>
          </Stack>
        </Group>
        <Progress value={total.progress * 100} size="lg" aria-label="Прогресс до следующего уровня" />
        <Text size="sm" c="dimmed">
          {gained.toLocaleString("ru-RU")} / {needed.toLocaleString("ru-RU")} XP до {total.level + 1}{" "}
          уровня
        </Text>
        <LastAward award={character.last_award} />
      </Stack>
    </Card>
  );
}
