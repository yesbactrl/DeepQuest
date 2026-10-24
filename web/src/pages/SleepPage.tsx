import {
  Alert,
  Button,
  Group,
  Paper,
  SegmentedControl,
  Select,
  SimpleGrid,
  Skeleton,
  Stack,
  Text,
  Title,
  useComputedColorScheme,
  useMantineTheme,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconPlus } from "@tabler/icons-react";
import { useMemo, useState, type ReactNode } from "react";

import { type SleepKind, type SleepOverview, type SleepStats, useSleep, useSleepGoal } from "../api/sleep";
import { EChart, type EChartOption } from "../components/charts/EChart";
import { SleepForm, type SleepDraft } from "../components/sleep/SleepForm";
import { SleepTimeline } from "../components/sleep/SleepTimeline";
import { chartTheme } from "../lib/chartTheme";
import { formatScore } from "../lib/diary";
import { formatMinutes } from "../lib/format";
import { NAP_COLOR, NIGHT_COLOR, clockOfMinutes, hours, shiftDay } from "../lib/sleep";

const SPANS = [
  { value: "7", label: "Неделя" },
  { value: "30", label: "Месяц" },
  { value: "90", label: "3 месяца" },
];

// Норма сна: от 6 до 10 часов с шагом в полчаса.
const GOALS = Array.from({ length: 9 }, (_, i) => 360 + i * 30).map((minutes) => ({
  value: String(minutes),
  label: hours(minutes),
}));

function Tile({ label, value, hint }: { label: string; value: ReactNode; hint?: ReactNode }) {
  return (
    <Paper withBorder p="md">
      <Stack gap={4}>
        <Text size="xs" c="dimmed" tt="uppercase" fw={600}>
          {label}
        </Text>
        <Text fz={24} fw={700} lh={1.1}>
          {value}
        </Text>
        {hint && (
          <Text size="xs" c="dimmed">
            {hint}
          </Text>
        )}
      </Stack>
    </Paper>
  );
}

function StatTiles({ stats, goal }: { stats: SleepStats; goal: number }) {
  const avg = stats.avg_total_min;
  return (
    <SimpleGrid cols={{ base: 2, sm: 3, lg: 6 }}>
      <Tile
        label="В среднем"
        value={avg === null ? "—" : hours(avg)}
        hint={
          avg === null
            ? "нет записей"
            : stats.avg_nap_min
              ? `ночь ${hours(stats.avg_night_min ?? 0)} + день ${hours(stats.avg_nap_min)}`
              : avg >= goal
                ? "не меньше нормы"
                : `на ${hours(goal - avg)} меньше нормы`
        }
      />
      <Tile
        label="Отбой"
        value={stats.avg_bedtime === null ? "—" : clockOfMinutes(stats.avg_bedtime)}
        hint={stats.bedtime_spread_min !== null ? `± ${formatMinutes(stats.bedtime_spread_min)}` : "в среднем"}
      />
      <Tile label="Подъём" value={stats.avg_wake === null ? "—" : clockOfMinutes(stats.avg_wake)} hint="в среднем" />
      <Tile label="Норма" value={`${stats.goal_met} из ${stats.days}`} hint="дней выспался" />
      <Tile label="Недосып" value={stats.debt_min ? hours(stats.debt_min) : "нет"} hint="за дни с записями" />
      <Tile
        label="Качество"
        value={stats.avg_quality === null ? "—" : `${formatScore(stats.avg_quality)}/10`}
        hint="как выспался"
      />
    </SimpleGrid>
  );
}

// Связь с днём: состояние по дневнику и фокус в дни с недосыпом и когда выспался.
function SleepAndDay({ stats }: { stats: SleepStats }) {
  const rows = [
    { title: "Не выспался", hint: "меньше нормы больше чем на час", group: stats.short, color: "red" },
    { title: "Выспался", hint: "не меньше нормы", group: stats.enough, color: "teal" },
  ];
  if (stats.short.days + stats.enough.days === 0) return null;
  return (
    <Paper withBorder p="md">
      <Stack gap="xs">
        <Text fw={600}>Сон и день</Text>
        <SimpleGrid cols={{ base: 1, sm: 2 }}>
          {rows.map(({ title, hint, group, color }) => (
            <Stack key={title} gap={2}>
              <Text size="sm" fw={600} c={color}>
                {title} · {group.days}
              </Text>
              <Text size="xs" c="dimmed">
                {hint}
              </Text>
              {group.days > 0 && (
                <Text size="sm">
                  состояние {group.state === null ? "—" : `${formatScore(group.state)}/10`}, фокус{" "}
                  {formatMinutes(Math.round(group.focus_min ?? 0))}
                </Text>
              )}
            </Stack>
          ))}
        </SimpleGrid>
        <Text size="xs" c="dimmed">
          Состояние — среднее настроения, энергии и желания из дневника в тот день, когда проснулся.
        </Text>
      </Stack>
    </Paper>
  );
}

function SleepChart({ data }: { data: SleepOverview }) {
  const scheme = useComputedColorScheme("light");
  const theme = useMantineTheme();
  const option = useMemo<EChartOption>(() => {
    const colors = chartTheme(scheme);
    const shade = scheme === "dark" ? 7 : 6;
    const byDay = new Map(data.days.map((d) => [d.day, d]));
    const span = Math.round((Date.parse(data.last) - Date.parse(data.first)) / 86400000) + 1;
    const days = Array.from({ length: span }, (_, i) => shiftDay(data.first, i));
    const toHours = (minutes: number | undefined) => (minutes ? Math.round((minutes / 60) * 10) / 10 : 0);
    const axisLabel = { color: colors.textSecondary };
    return {
      animation: false,
      grid: { left: 32, right: 12, top: 28, bottom: 24 },
      tooltip: { trigger: "axis", valueFormatter: (v: number) => `${v} ч` },
      legend: { top: 0, right: 0, textStyle: { color: colors.textSecondary } },
      xAxis: {
        type: "category",
        data: days.map((d) =>
          new Date(`${d}T12:00:00`).toLocaleDateString("ru-RU", span <= 7 ? { weekday: "short" } : { day: "numeric", month: "numeric" }),
        ),
        axisLabel,
        axisLine: { lineStyle: { color: colors.grid } },
      },
      yAxis: { type: "value", axisLabel, splitLine: { lineStyle: { color: colors.grid } } },
      series: [
        {
          name: "Ночь",
          type: "bar",
          stack: "sleep",
          barMaxWidth: 24,
          itemStyle: { color: theme.colors[NIGHT_COLOR][shade] },
          data: days.map((d) => toHours(byDay.get(d)?.night_min)),
          markLine: {
            symbol: "none",
            silent: true,
            label: { formatter: "норма", position: "insideEndTop", color: colors.textSecondary },
            lineStyle: { color: colors.neutral, type: "dashed" },
            data: [{ yAxis: data.goal_min / 60 }],
          },
        },
        {
          name: "Днём",
          type: "bar",
          stack: "sleep",
          barMaxWidth: 24,
          itemStyle: { color: theme.colors[NAP_COLOR][shade], borderRadius: [3, 3, 0, 0] },
          data: days.map((d) => toHours(byDay.get(d)?.nap_min)),
        },
      ],
    };
  }, [data, scheme, theme]);
  return (
    <Paper withBorder p="md">
      <Stack gap="xs">
        <Text fw={600}>Сон по дням</Text>
        <EChart option={option} height={220} />
      </Stack>
    </Paper>
  );
}

// Режим сна: ночной и дневной сон по дням, норма, средние время отбоя и подъёма и как сон
// связан с состоянием и работой.
export function SleepPage() {
  const [span, setSpan] = useState("30");
  const sleep = useSleep(Number(span));
  const goal = useSleepGoal();
  const [draft, setDraft] = useState<SleepDraft | null>(null);
  const data = sleep.data;

  // Новая ночь — по привычному времени отбоя и подъёма, иначе 23:00–07:00.
  function addNight() {
    if (!data) return;
    const bed = data.stats.avg_bedtime ?? 23 * 60;
    const wake = data.stats.avg_wake ?? 7 * 60;
    const bedDay = bed >= 12 * 60 ? shiftDay(data.last, -1) : data.last;
    setDraft({
      input: {
        kind: "night",
        start: `${bedDay}T${clockOfMinutes(bed)}`,
        end: `${data.last}T${clockOfMinutes(wake)}`,
        quality: null,
        note: null,
      },
    });
  }

  const addAt = (kind: SleepKind, start: string, end: string) =>
    setDraft({ input: { kind, start, end, quality: null, note: null } });

  return (
    <Stack gap="lg">
      <Group justify="space-between" align="flex-end">
        <Stack gap={4}>
          <Title order={2}>Сон</Title>
          <Text c="dimmed" size="sm">
            Ночь и дневной сон по дням. Сон относится к дню, когда проснулся.
          </Text>
        </Stack>
        <Group gap="sm">
          {data && (
            <Select
              w={130}
              size="sm"
              label="Норма"
              data={GOALS}
              value={String(data.goal_min)}
              allowDeselect={false}
              onChange={(value) =>
                value &&
                goal.mutate(Number(value), {
                  onError: (error) => notifications.show({ color: "red", message: error.message }),
                })
              }
            />
          )}
          <Button leftSection={<IconPlus size={16} />} onClick={addNight} disabled={!data} mt="lg">
            Записать сон
          </Button>
        </Group>
      </Group>

      {sleep.isError && (
        <Alert color="red" title="Не удалось загрузить сон">
          {sleep.error.message}
        </Alert>
      )}
      {sleep.isPending && <Skeleton h={360} />}
      {data && (
        <>
          <SleepTimeline
            days={data.days}
            today={data.last}
            span={7}
            onOpen={(session) => setDraft({ session })}
            onAdd={addAt}
          />
          <Group justify="space-between">
            <Title order={4}>Статистика</Title>
            <SegmentedControl size="xs" value={span} onChange={setSpan} data={SPANS} />
          </Group>
          {data.stats.days === 0 ? (
            <Text c="dimmed">За этот период сна не записано.</Text>
          ) : (
            <>
              <StatTiles stats={data.stats} goal={data.goal_min} />
              <SleepChart data={data} />
              <SleepAndDay stats={data.stats} />
            </>
          )}
        </>
      )}

      <SleepForm draft={draft} onClose={() => setDraft(null)} />
    </Stack>
  );
}
