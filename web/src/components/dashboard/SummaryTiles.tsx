import { Box, Group, Paper, Progress, SimpleGrid, Skeleton, Stack, Text, ThemeIcon, Tooltip } from "@mantine/core";
import { IconCheck, IconFlame } from "@tabler/icons-react";
import type { ReactNode } from "react";

import type { DayMark, Summary } from "../../api/dashboard";
import { DAY_STATUS } from "../../lib/chartTheme";
import { formatMinutes, plural } from "../../lib/format";

const MONTHS = [
  "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
  "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
];

function Tile({ label, children }: { label: string; children: ReactNode }) {
  return (
    <Paper withBorder p="md">
      <Stack gap={6}>
        <Text size="xs" c="dimmed" tt="uppercase" fw={600}>
          {label}
        </Text>
        {children}
      </Stack>
    </Paper>
  );
}

function Big({ children }: { children: ReactNode }) {
  return (
    <Text fz={32} fw={700} lh={1.1}>
      {children}
    </Text>
  );
}

function dayLabel(mark: DayMark): string {
  const date = new Date(`${mark.day}T00:00:00`).toLocaleDateString("ru-RU", { day: "numeric", month: "short" });
  const status =
    mark.status === "today"
      ? mark.focus_min >= mark.norm_min
        ? "сегодня, норма выполнена"
        : "сегодня, в процессе"
      : DAY_STATUS[mark.status].label;
  return `${date}: ${formatMinutes(mark.focus_min)} из ${formatMinutes(mark.norm_min)} — ${status}`;
}

function DayStrip({ days }: { days: DayMark[] }) {
  return (
    <Stack gap={6}>
      <Group gap={4} wrap="nowrap">
        {days.map((mark) => {
          const today = mark.status === "today";
          const color =
            mark.status === "today"
              ? mark.focus_min >= mark.norm_min
                ? DAY_STATUS.met.color
                : "transparent"
              : DAY_STATUS[mark.status].color;
          return (
            <Tooltip key={mark.day} label={dayLabel(mark)}>
              <Box
                w={16}
                h={16}
                style={{
                  borderRadius: 4,
                  background: color,
                  border: today ? "2px dashed var(--mantine-color-dimmed)" : undefined,
                }}
              />
            </Tooltip>
          );
        })}
      </Group>
      <Group gap="sm">
        {Object.values(DAY_STATUS).map((status) => (
          <Group key={status.label} gap={4} wrap="nowrap">
            <Box w={8} h={8} style={{ borderRadius: 2, background: status.color }} />
            <Text size="xs" c="dimmed">
              {status.label}
            </Text>
          </Group>
        ))}
      </Group>
    </Stack>
  );
}

export function SummaryTiles({ summary }: { summary: Summary | undefined }) {
  if (!summary) {
    return (
      <SimpleGrid cols={{ base: 1, sm: 2, lg: 4 }}>
        {[1, 2, 3, 4].map((i) => (
          <Skeleton key={i} h={130} />
        ))}
      </SimpleGrid>
    );
  }
  const { total, season_level: season, streak } = summary;
  const month = MONTHS[Number(summary.season.slice(5, 7)) - 1];
  const todayShare = Math.min(streak.today_focus_min / streak.norm_min, 1) * 100;

  return (
    <SimpleGrid cols={{ base: 1, sm: 2, lg: 4 }}>
      <Tile label="Уровень">
        <Big>{total.level}</Big>
        <Progress value={total.progress * 100} size="sm" aria-label="Прогресс до следующего уровня" />
        <Text size="sm" c="dimmed">
          {total.xp.toLocaleString("ru-RU")} XP · до {total.level + 1}-го ещё{" "}
          {(total.next_xp - total.xp).toLocaleString("ru-RU")}
        </Text>
      </Tile>

      <Tile label={`Сезон · ${month}`}>
        <Big>{season.level}</Big>
        <Progress value={season.progress * 100} size="sm" aria-label="Прогресс уровня сезона" />
        <Text size="sm" c="dimmed">
          {season.xp.toLocaleString("ru-RU")} XP за месяц · до {season.level + 1}-го ещё{" "}
          {season.next_xp - season.xp}
        </Text>
      </Tile>

      <Tile label="Сегодня">
        <Group gap="xs" align="center">
          <Big>{formatMinutes(streak.today_focus_min)}</Big>
          {streak.today_met && (
            <ThemeIcon color="green" radius="xl" size="sm">
              <IconCheck size={14} />
            </ThemeIcon>
          )}
        </Group>
        <Progress
          value={todayShare}
          size="sm"
          color={streak.today_met ? "green" : undefined}
          aria-label="Норма на сегодня"
        />
        <Text size="sm" c="dimmed">
          {streak.today_met
            ? `норма ${formatMinutes(streak.norm_min)} выполнена`
            : `из ${formatMinutes(streak.norm_min)} нормы, осталось ${formatMinutes(streak.norm_min - streak.today_focus_min)}`}
        </Text>
      </Tile>

      <Tile label="Стрик">
        <Group gap={6} align="center">
          <IconFlame size={28} stroke={1.6} color="var(--mantine-color-orange-6)" />
          <Big>
            {streak.current} {plural(streak.current, "день", "дня", "дней")}
          </Big>
        </Group>
        <Text size="sm" c="dimmed">
          лучший {streak.best} · заморозок {streak.freezes_left} из {streak.freezes_per_week}
        </Text>
        <DayStrip days={streak.recent} />
      </Tile>
    </SimpleGrid>
  );
}
