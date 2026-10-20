import { Alert, Box, Card, Group, Progress, Stack, Text, ThemeIcon } from "@mantine/core";
import { IconTrendingUp } from "@tabler/icons-react";

import type { Stat } from "../../api/character";
import { goalIcon, useGoalColor } from "../../lib/goalLook";

function percent(mult: number): string {
  return `+${Math.round((mult - 1) * 100)}%`;
}

export function StatCard({ stat, weakMult }: { stat: Stat; weakMult: number }) {
  const color = useGoalColor()(stat.color);
  const Icon = goalIcon(stat.icon);
  const { level } = stat;
  return (
    <Card withBorder padding="lg" h="100%">
      <Stack gap="sm">
        <Group justify="space-between" wrap="nowrap">
          <Group gap="xs" wrap="nowrap" style={{ minWidth: 0 }}>
            <ThemeIcon variant="light" color={color} size="lg" radius="md">
              <Icon size={20} />
            </ThemeIcon>
            <Text fw={700} size="lg" truncate>
              {stat.title}
            </Text>
          </Group>
          <Text fw={700} style={{ whiteSpace: "nowrap" }}>
            ур. {level.level}
          </Text>
        </Group>

        <Stack gap={4}>
          <Progress value={level.progress * 100} color={color} size="sm" aria-label={`Прогресс стата ${stat.title}`} />
          <Text size="xs" c="dimmed">
            {(level.xp - level.floor_xp).toLocaleString("ru-RU")} /{" "}
            {(level.next_xp - level.floor_xp).toLocaleString("ru-RU")} XP · за сезон{" "}
            {stat.season_xp.toLocaleString("ru-RU")}
          </Text>
        </Stack>

        {stat.skills.length > 0 ? (
          <Box>
            {stat.skills.map((skill) => (
              <Group
                key={skill.id}
                justify="space-between"
                wrap="nowrap"
                py={6}
                style={{ borderTop: "1px solid var(--mantine-color-default-border)" }}
              >
                <Text size="sm" truncate>
                  {skill.title}
                </Text>
                <Text size="sm" c="dimmed" style={{ whiteSpace: "nowrap" }}>
                  ур. {skill.level.level}
                </Text>
              </Group>
            ))}
          </Box>
        ) : (
          <Text size="sm" c="dimmed">
            Скиллов нет: это направления цели, их можно добавить на странице «Цели».
          </Text>
        )}

        {stat.weakest && (
          <Alert color="yellow" variant="light" p="xs" icon={<IconTrendingUp size={18} />}>
            <Text size="sm">Самый слабый стат · {percent(weakMult)} XP</Text>
          </Alert>
        )}
      </Stack>
    </Card>
  );
}
