import {
  Alert,
  Anchor,
  Badge,
  Card,
  Group,
  SimpleGrid,
  Skeleton,
  Stack,
  Table,
  Text,
  Title,
} from "@mantine/core";
import { IconArrowLeft, IconCheck } from "@tabler/icons-react";
import type { ReactNode } from "react";
import { Link } from "react-router";

import { type Character, type Levels, type Stat, useCharacter, useLevels } from "../api/character";
import { formatMinutes } from "../lib/format";
import { useGoalColor } from "../lib/goalLook";
import { VALUE_SCALE, VERDICT, formatMult } from "../lib/tasks";

const number = (value: number, digits = 0) =>
  value.toLocaleString("ru-RU", { maximumFractionDigits: digits });

function Tile({ label, value, hint }: { label: string; value: ReactNode; hint: ReactNode }) {
  return (
    <Card withBorder padding="md">
      <Stack gap={4}>
        <Text size="xs" c="dimmed" tt="uppercase" fw={600}>
          {label}
        </Text>
        <Text fz={26} fw={700} lh={1.2}>
          {value}
        </Text>
        <Text size="sm" c="dimmed">
          {hint}
        </Text>
      </Stack>
    </Card>
  );
}

// Сколько XP в день даёт норма при обычной задаче (×1, засчитано, с пруфом).
function dailyXp(levels: Levels): number {
  return levels.daily_norm_min * levels.rules.xp_per_minute;
}

function Summary({ levels, character }: { levels: Levels; character: Character }) {
  const { total } = character.summary;
  const left = total.next_xp - total.xp;
  const perDay = dailyXp(levels);
  const perHour = 60 * levels.rules.xp_per_minute;
  const mults = levels.rules.value_mults;
  return (
    <SimpleGrid cols={{ base: 1, sm: 3 }}>
      <Tile
        label="Ты сейчас"
        value={`Уровень ${total.level}`}
        hint={`${number(total.xp)} XP · до ${total.level + 1}-го ещё ${number(left)}`}
      />
      <Tile
        label="Темп по норме"
        value={`≈ ${number(perDay)} XP в день`}
        hint={`Норма ${formatMinutes(levels.daily_norm_min)} обычных задач (×1). До следующего уровня ≈ ${number(Math.ceil(left / perDay))} дн.`}
      />
      <Tile
        label="Час работы"
        value={`${number(perHour)} XP`}
        hint={`При ×1. Рутина ×${mults[0]} — ${number(perHour * mults[0])} XP, ключевой шаг ×${mults[mults.length - 1]} — ${number(perHour * mults[mults.length - 1])} XP.`}
      />
    </SimpleGrid>
  );
}

function Rules({ levels }: { levels: Levels }) {
  const { rules } = levels;
  const rows: [string, ReactNode][] = [
    ["Время", `${rules.xp_per_minute} XP за минуту; засчитывается не больше ${rules.cap_factor} оценок задачи`],
    [
      "Ценность задачи",
      <Stack key="value" gap={0}>
        {VALUE_SCALE.map((item) => (
          <Text key={item.value} size="sm">
            {item.label}
          </Text>
        ))}
      </Stack>,
    ],
    [
      "Проверка отчёта",
      (["accepted", "partial", "rejected"] as const)
        .map((verdict) => `${VERDICT[verdict].label} ${formatMult(rules.validation_mults[verdict])}`)
        .join(" · "),
    ],
    ["Пруф", `есть ×1 · на честном слове ${formatMult(rules.honor_mode_mult)}`],
    ["Самый слабый стат", `${formatMult(rules.weak_stat_mult)} — бонус цели, которая отстаёт за сезон`],
  ];
  return (
    <Card withBorder padding="md">
      <Stack gap="xs">
        <Title order={4}>Откуда XP</Title>
        <Text size="sm" ff="monospace" c="dimmed">
          XP = минуты × ценность × проверка × пруф × слабый стат
        </Text>
        <Table withRowBorders={false} verticalSpacing={4}>
          <Table.Tbody>
            {rows.map(([label, value]) => (
              <Table.Tr key={label}>
                <Table.Td c="dimmed" w={170} style={{ verticalAlign: "top" }}>
                  {label}
                </Table.Td>
                <Table.Td>{value}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
        <Text size="sm" c="dimmed">
          Одна шкала на всё: общий уровень, сезон, статы и скиллы. Уровни нигде не хранятся — они
          считаются из журнала XP, поэтому смена формулы пересчитает всё сама.
        </Text>
      </Stack>
    </Card>
  );
}

function StatBadge({ stat }: { stat: Stat }) {
  const color = useGoalColor()(stat.color);
  return (
    <Badge variant="light" color={color} size="sm">
      {stat.title}
    </Badge>
  );
}

function ScaleTable({ levels, character }: { levels: Levels; character: Character }) {
  const current = character.summary.total.level;
  const season = character.summary.season_level.level;
  const perDay = dailyXp(levels);
  const perHour = 60 * levels.rules.xp_per_minute;
  return (
    <Card withBorder padding={0}>
      <Table.ScrollContainer minWidth={640}>
        <Table striped={false} highlightOnHover verticalSpacing="xs" horizontalSpacing="md">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Уровень</Table.Th>
              <Table.Th ta="right">За уровень</Table.Th>
              <Table.Th ta="right">Всего XP</Table.Th>
              <Table.Th ta="right">Часов работы</Table.Th>
              <Table.Th ta="right">Дней по норме</Table.Th>
              <Table.Th>Кто здесь</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {levels.steps.map((step) => {
              const here = character.stats.filter((stat) => stat.level.level === step.level);
              const reached = step.level <= current;
              return (
                <Table.Tr
                  key={step.level}
                  bg={step.level === current ? "var(--mantine-color-violet-light)" : undefined}
                >
                  <Table.Td>
                    <Group gap={6} wrap="nowrap">
                      <Text fw={step.level === current ? 700 : 500}>{step.level}</Text>
                      {reached && step.level !== current && (
                        <IconCheck size={14} color="var(--mantine-color-dimmed)" aria-label="пройден" />
                      )}
                    </Group>
                  </Table.Td>
                  <Table.Td ta="right">{step.cost ? `+${number(step.cost)}` : "—"}</Table.Td>
                  <Table.Td ta="right">{number(step.total)}</Table.Td>
                  <Table.Td ta="right">{number(step.total / perHour, 1)}</Table.Td>
                  <Table.Td ta="right">{number(step.total / perDay, step.total / perDay < 10 ? 1 : 0)}</Table.Td>
                  <Table.Td>
                    <Group gap={4}>
                      {step.level === current && (
                        <Badge variant="filled" size="sm">
                          Ты
                        </Badge>
                      )}
                      {step.level === season && (
                        <Badge variant="outline" size="sm">
                          Сезон
                        </Badge>
                      )}
                      {here.map((stat) => (
                        <StatBadge key={stat.id} stat={stat} />
                      ))}
                    </Group>
                  </Table.Td>
                </Table.Tr>
              );
            })}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
    </Card>
  );
}

// Шкала уровней и баланс: сколько XP и сколько работы стоит каждый уровень.
export function LevelsPage() {
  const levels = useLevels();
  const character = useCharacter();
  const error = levels.error ?? character.error;
  return (
    <Stack gap="lg">
      <Stack gap={4}>
        <Anchor component={Link} to="/character" size="sm" c="dimmed">
          <Group gap={4}>
            <IconArrowLeft size={14} /> Персонаж
          </Group>
        </Anchor>
        <Title order={2}>Уровни</Title>
        <Text c="dimmed" size="sm">
          Сколько XP нужно до каждого уровня и сколько это работы. Часы — при обычной задаче (×1),
          дни — если каждый день выполнять норму.
        </Text>
      </Stack>
      {error && (
        <Alert color="red" title="Не удалось загрузить шкалу">
          {error.message}
        </Alert>
      )}
      {levels.data && character.data ? (
        <>
          <Summary levels={levels.data} character={character.data} />
          <ScaleTable levels={levels.data} character={character.data} />
          <Rules levels={levels.data} />
        </>
      ) : (
        !error && <Skeleton h={400} />
      )}
    </Stack>
  );
}
