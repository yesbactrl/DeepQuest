import {
  Alert,
  Anchor,
  Badge,
  Box,
  Group,
  List,
  Paper,
  SimpleGrid,
  Skeleton,
  Stack,
  Text,
  ThemeIcon,
  Title,
  Tooltip,
} from "@mantine/core";
import {
  IconBolt,
  IconBook,
  IconBrandTelegram,
  IconCalendarWeek,
  IconClock,
  IconCode,
  IconFlame,
  IconListCheck,
  IconMessageChatbot,
  IconMicrophone,
  IconMoon,
  IconReportAnalytics,
  IconRobot,
  IconSearch,
  IconServer,
  IconStairsUp,
  IconTarget,
  IconUserStar,
  IconWorld,
  type Icon,
} from "@tabler/icons-react";
import { useState } from "react";

import { type CommitKind, type DevCommit, type DevDay, useDevlog } from "../api/devlog";
import { plural } from "../lib/format";

// Раздел приложения: цвет и иконка — те же, что в меню, где можно.
const AREAS: Record<string, { color: string; icon: Icon }> = {
  Советник: { color: "violet", icon: IconMessageChatbot },
  Сон: { color: "indigo", icon: IconMoon },
  Итоги: { color: "cyan", icon: IconReportAnalytics },
  Поиск: { color: "gray", icon: IconSearch },
  Дневник: { color: "pink", icon: IconBook },
  План: { color: "teal", icon: IconCalendarWeek },
  Персонаж: { color: "grape", icon: IconUserStar },
  Уровни: { color: "yellow", icon: IconStairsUp },
  Голос: { color: "orange", icon: IconMicrophone },
  Задачи: { color: "blue", icon: IconListCheck },
  Таймер: { color: "lime", icon: IconClock },
  "Норма и стрик": { color: "red", icon: IconFlame },
  XP: { color: "yellow", icon: IconBolt },
  Цели: { color: "green", icon: IconTarget },
  Служба: { color: "dark", icon: IconServer },
  Агент: { color: "violet", icon: IconRobot },
  Веб: { color: "blue", icon: IconWorld },
  Бот: { color: "cyan", icon: IconBrandTelegram },
};
const OTHER = { color: "gray", icon: IconCode };

const KINDS: Record<CommitKind, { label: string; hint: string }> = {
  milestone: { label: "Веха", hint: "шаг из плана разработки" },
  feature: { label: "Новое", hint: "новая возможность" },
  polish: { label: "Доводка", hint: "небольшое улучшение" },
  fix: { label: "Исправление", hint: "починили" },
};

const MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"];
const WEEKDAYS = ["воскресенье", "понедельник", "вторник", "среда", "четверг", "пятница", "суббота"];

const area = (name: string | null) => (name && AREAS[name]) || OTHER;
const number = (n: number) => n.toLocaleString("ru-RU");

function wallDate(day: string): Date {
  return new Date(`${day}T12:00:00`);
}

function daysBetween(a: string, b: string): number {
  return Math.round((wallDate(b).getTime() - wallDate(a).getTime()) / 86400000);
}

// Время коммита по его собственным часам, а не по поясу браузера.
function clock(at: string): string {
  return at.slice(11, 16);
}

function Dot({ commit }: { commit: DevCommit }) {
  const color = `var(--mantine-color-${area(commit.area).color}-filled)`;
  if (commit.kind === "milestone") {
    return <div className="devlog-milestone">{commit.milestone}</div>;
  }
  if (commit.kind === "fix") {
    return (
      <div
        className="devlog-dot"
        style={{ width: 14, height: 14, background: "var(--mantine-color-body)", border: "3px solid var(--mantine-color-orange-filled)" }}
      />
    );
  }
  const size = commit.kind === "feature" ? 16 : 10;
  return <div className="devlog-dot" style={{ width: size, height: size, marginTop: commit.kind === "feature" ? 12 : 15, background: color }} />;
}

function Points({ points }: { points: string[] }) {
  const [open, setOpen] = useState(false);
  if (points.length === 0) return null;
  const shown = open ? points : points.slice(0, 3);
  return (
    <Stack gap={2}>
      <List size="sm" spacing={2} c="dimmed">
        {shown.map((point) => (
          <List.Item key={point}>{point}</List.Item>
        ))}
      </List>
      {points.length > 3 && (
        <Anchor component="button" size="xs" onClick={() => setOpen(!open)} ta="left">
          {open ? "свернуть" : `ещё ${points.length - 3}`}
        </Anchor>
      )}
    </Stack>
  );
}

function CommitCard({ commit }: { commit: DevCommit }) {
  const look = area(commit.area);
  const Icon = look.icon;
  const milestone = commit.kind === "milestone";
  return (
    <Paper
      withBorder
      p="sm"
      radius="md"
      style={{
        flex: 1,
        minWidth: 0,
        borderColor: milestone ? "var(--mantine-color-violet-filled)" : undefined,
        background: milestone ? "var(--mantine-color-violet-light)" : undefined,
      }}
    >
      <Stack gap={6}>
        <Group gap="xs" wrap="nowrap" align="flex-start" justify="space-between">
          <Text fw={milestone ? 700 : 600} size={commit.kind === "polish" ? "sm" : "md"} style={{ overflowWrap: "anywhere" }}>
            {commit.title}
          </Text>
          <Group gap={4} wrap="nowrap" style={{ flexShrink: 0 }}>
            {commit.kind !== "feature" && (
              <Badge size="xs" variant="outline" color={commit.kind === "fix" ? "orange" : milestone ? "violet" : "gray"}>
                {KINDS[commit.kind].label}
              </Badge>
            )}
            {commit.area && (
              <Badge size="xs" variant="light" color={look.color} leftSection={<Icon size={11} />} tt="none">
                {commit.area}
              </Badge>
            )}
          </Group>
        </Group>
        <Points points={commit.points} />
        <Text size="xs" c="dimmed">
          <Text span c="teal" inherit>
            +{number(commit.insertions)}
          </Text>{" "}
          <Text span c="red" inherit>
            −{number(commit.deletions)}
          </Text>{" "}
          · {commit.files} {plural(commit.files, "файл", "файла", "файлов")} · {commit.short}
        </Text>
      </Stack>
    </Paper>
  );
}

function DayBlock({ day, gapAfter }: { day: DevDay; gapAfter: number }) {
  const date = wallDate(day.day);
  const areas = [...new Set(day.commits.map((c) => c.area).filter((a): a is string => a !== null))];
  return (
    <Stack gap={0} id={`day-${day.day}`} style={{ scrollMarginTop: 72 }}>
      <Group gap="md" align="flex-end" mb="sm" wrap="wrap">
        <Group gap={8} align="baseline" wrap="nowrap">
          <Text fz={40} fw={800} lh={1} variant="gradient" gradient={{ from: "violet", to: "indigo" }}>
            {date.getDate()}
          </Text>
          <Stack gap={0}>
            <Text fw={700} lh={1.2}>
              {MONTHS[date.getMonth()]}
            </Text>
            <Text size="sm" c="dimmed" lh={1.2}>
              {WEEKDAYS[date.getDay()]}
            </Text>
          </Stack>
        </Group>
        <Text size="sm" c="dimmed" pb={2}>
          {day.commits.length} {plural(day.commits.length, "изменение", "изменения", "изменений")} · +
          {number(day.insertions)} строк
        </Text>
        <Group gap={4} pb={2}>
          {areas.map((name) => {
            const Icon = area(name).icon;
            return (
              <Badge key={name} size="sm" variant="light" color={area(name).color} tt="none" leftSection={<Icon size={12} />}>
                {name}
              </Badge>
            );
          })}
        </Group>
      </Group>
      {day.commits.map((commit, index) => (
        <Group key={commit.hash} gap="xs" wrap="nowrap" align="stretch" className="devlog-item" style={{ animationDelay: `${Math.min(index, 8) * 40}ms` }}>
          <Text size="xs" c="dimmed" w={40} ta="right" pt={14} style={{ flexShrink: 0 }}>
            {clock(commit.at)}
          </Text>
          <div
            className={[
              "devlog-rail",
              index === 0 && "devlog-rail--first",
              index === day.commits.length - 1 && "devlog-rail--last",
            ]
              .filter(Boolean)
              .join(" ")}
          >
            <Tooltip label={KINDS[commit.kind].hint} position="left">
              <div>
                <Dot commit={commit} />
              </div>
            </Tooltip>
          </div>
          <Box pb="sm" style={{ flex: 1, minWidth: 0 }}>
            <CommitCard commit={commit} />
          </Box>
        </Group>
      ))}
      {gapAfter > 1 && (
        <Text size="sm" c="dimmed" fs="italic" ta="center" py="md">
          · · · {gapAfter - 1} {plural(gapAfter - 1, "день", "дня", "дней")} без изменений · · ·
        </Text>
      )}
    </Stack>
  );
}

// Полоса активности: столбик на каждый календарный день, высота — сколько строк написано.
function Activity({ days }: { days: DevDay[] }) {
  const byDay = new Map(days.map((d) => [d.day, d]));
  const first = days[days.length - 1].day;
  const span = daysBetween(first, days[0].day) + 1;
  const all = Array.from({ length: span }, (_, i) => {
    const date = wallDate(first);
    date.setDate(date.getDate() + i);
    const key = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
    return { key, date, data: byDay.get(key) };
  });
  const max = Math.max(...days.map((d) => d.insertions), 1);
  return (
    <Group gap={4} align="flex-end" h={64} wrap="nowrap">
      {all.map(({ key, date, data }) => (
        <Tooltip
          key={key}
          label={
            data
              ? `${date.getDate()} ${MONTHS[date.getMonth()]}: ${data.commits.length} ${plural(data.commits.length, "изменение", "изменения", "изменений")}, +${number(data.insertions)}`
              : `${date.getDate()} ${MONTHS[date.getMonth()]}: без изменений`
          }
        >
          <div
            className="devlog-bar"
            onClick={() => document.getElementById(`day-${key}`)?.scrollIntoView({ behavior: "smooth" })}
            style={{
              height: data ? `${Math.max((data.insertions / max) * 100, 8)}%` : 4,
              maxWidth: 40,
              background: data
                ? "linear-gradient(to top, var(--mantine-color-indigo-filled), var(--mantine-color-violet-filled))"
                : "var(--mantine-color-default-border)",
            }}
          />
        </Tooltip>
      ))}
    </Group>
  );
}

function Stat({ value, label }: { value: string; label: string }) {
  return (
    <Stack gap={0}>
      <Text fz={28} fw={800} lh={1.1}>
        {value}
      </Text>
      <Text size="xs" c="dimmed" tt="uppercase" fw={600}>
        {label}
      </Text>
    </Stack>
  );
}

function Legend() {
  return (
    <Group gap="lg">
      <Group gap={6}>
        <div className="devlog-milestone" style={{ width: 20, height: 20, fontSize: 8, marginTop: 0, boxShadow: "none" }}>
          M
        </div>
        <Text size="xs" c="dimmed">
          веха плана
        </Text>
      </Group>
      <Group gap={6}>
        <div className="devlog-dot" style={{ width: 14, height: 14, marginTop: 0, background: "var(--mantine-color-blue-filled)", boxShadow: "none" }} />
        <Text size="xs" c="dimmed">
          новое (цвет — раздел)
        </Text>
      </Group>
      <Group gap={6}>
        <div className="devlog-dot" style={{ width: 9, height: 9, marginTop: 0, background: "var(--mantine-color-blue-filled)", boxShadow: "none" }} />
        <Text size="xs" c="dimmed">
          доводка
        </Text>
      </Group>
      <Group gap={6}>
        <div
          className="devlog-dot"
          style={{ width: 13, height: 13, marginTop: 0, border: "3px solid var(--mantine-color-orange-filled)", boxShadow: "none" }}
        />
        <Text size="xs" c="dimmed">
          исправление
        </Text>
      </Group>
    </Group>
  );
}

// История разработки DeepQuest: каждый коммит — точка на линии, дни — свежие сверху.
// Данные — из git, страница обновляется сама с каждым коммитом.
export function DevlogPage() {
  const devlog = useDevlog();
  const data = devlog.data;
  const today = new Date();
  const todayKey = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;

  return (
    <Stack gap="xl" maw={920}>
      {devlog.isError && (
        <Alert color="red" title="Не удалось прочитать историю">
          {devlog.error.message}
        </Alert>
      )}
      {devlog.isPending && <Skeleton h={480} />}
      {data && data.days.length === 0 && (
        <Alert color="gray" title="Истории пока нет">
          DeepQuest запущен не из git-репозитория или в нём ещё нет коммитов.
        </Alert>
      )}
      {data && data.days.length > 0 && (
        <>
          <Paper withBorder p="xl" radius="lg" className="devlog-hero">
            <Stack gap="lg">
              <Group gap="sm">
                <ThemeIcon size={44} radius="md" variant="gradient" gradient={{ from: "violet", to: "indigo" }}>
                  <IconCode size={24} />
                </ThemeIcon>
                <Stack gap={0}>
                  <Title order={2}>Как рос DeepQuest</Title>
                  <Text c="dimmed" size="sm">
                    Каждая точка — изменение в коде, свежие сверху. С{" "}
                    {wallDate(data.days[data.days.length - 1].day).getDate()}{" "}
                    {MONTHS[wallDate(data.days[data.days.length - 1].day).getMonth()]}.
                  </Text>
                </Stack>
              </Group>
              <SimpleGrid cols={{ base: 2, sm: 4 }}>
                <Stat
                  value={String(daysBetween(data.days[data.days.length - 1].day, todayKey) + 1)}
                  label={`${plural(daysBetween(data.days[data.days.length - 1].day, todayKey) + 1, "день", "дня", "дней")} разработки`}
                />
                <Stat value={String(data.commits)} label={plural(data.commits, "изменение", "изменения", "изменений")} />
                <Stat value={String(data.milestones)} label={plural(data.milestones, "веха", "вехи", "вех")} />
                <Stat value={number(data.insertions)} label="строк написано" />
              </SimpleGrid>
              <Activity days={data.days} />
            </Stack>
          </Paper>
          <Legend />
          <Stack gap="xl">
            {data.days.map((day, index) => (
              <DayBlock
                key={day.day}
                day={day}
                gapAfter={index < data.days.length - 1 ? daysBetween(data.days[index + 1].day, day.day) : 0}
              />
            ))}
          </Stack>
        </>
      )}
    </Stack>
  );
}
