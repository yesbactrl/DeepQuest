import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Group,
  List,
  Paper,
  SegmentedControl,
  SimpleGrid,
  Skeleton,
  Stack,
  Text,
  ThemeIcon,
  Title,
  Tooltip,
  useComputedColorScheme,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconChevronLeft, IconChevronRight, IconSparkles } from "@tabler/icons-react";
import { useMemo, useState, type ReactNode } from "react";
import { useSearchParams } from "react-router";

import { useGoals } from "../api/goals";
import {
  type DayGroup,
  type DayPoint,
  type PeriodKind,
  type Review,
  type SphereReview,
  useAnalyzeReview,
  useReview,
} from "../api/review";
import { EChart, type EChartOption } from "../components/charts/EChart";
import { TaskDrawer } from "../components/tasks/TaskDrawer";
import { DAY_STATUS, chartTheme } from "../lib/chartTheme";
import { SCALES, formatScore, scoreColor } from "../lib/diary";
import { formatMinutes } from "../lib/format";
import { goalIcon, useGoalColor } from "../lib/goalLook";

const PERIOD_NAME: Record<PeriodKind, { current: string; previous: string }> = {
  week: { current: "Эта неделя", previous: "прошлой недели" },
  month: { current: "Этот месяц", previous: "прошлого месяца" },
};

// Цвет средней оценки: средние оставляем обычным текстом — серый в тёмной теме плохо читается.
function scoreText(value: number | null): string | undefined {
  if (value === null) return undefined;
  const color = scoreColor(value);
  return color === "gray" ? undefined : `${color}.7`;
}

// Разница с прошлым периодом: зелёная, если лучше, красная, если хуже.
function Delta({
  now,
  before,
  format = (v) => String(Math.round(v)),
}: {
  now: number | null;
  before: number | null;
  format?: (value: number) => string;
}) {
  if (now === null || before === null) return null;
  const diff = Math.round((now - before) * 10) / 10;
  if (diff === 0) {
    return (
      <Text size="xs" c="dimmed">
        как раньше
      </Text>
    );
  }
  return (
    <Text size="xs" c={diff > 0 ? "teal" : "red"} fw={500}>
      {diff > 0 ? "+" : "−"}
      {format(Math.abs(diff))}
    </Text>
  );
}

function Tile({ label, value, delta }: { label: string; value: ReactNode; delta?: ReactNode }) {
  return (
    <Paper withBorder p="md">
      <Stack gap={4}>
        <Text size="xs" c="dimmed" tt="uppercase" fw={600}>
          {label}
        </Text>
        <Text fz={26} fw={700} lh={1.1}>
          {value}
        </Text>
        {delta}
      </Stack>
    </Paper>
  );
}

function Totals({ review }: { review: Review }) {
  const { totals: t, prev_totals: p } = review;
  return (
    <SimpleGrid cols={{ base: 2, sm: 3, lg: 5 }}>
      <Tile label="Опыт" value={`${t.xp} XP`} delta={<Delta now={t.xp} before={p.xp} />} />
      <Tile
        label="Фокус"
        value={formatMinutes(t.minutes)}
        delta={<Delta now={t.minutes} before={p.minutes} format={formatMinutes} />}
      />
      <Tile label="Задач закрыто" value={t.done_tasks} delta={<Delta now={t.done_tasks} before={p.done_tasks} />} />
      <Tile label="Записей" value={t.entries} delta={<Delta now={t.entries} before={p.entries} />} />
      <Tile
        label="Норма"
        value={t.norm_days ? `${t.norm_met} из ${t.norm_days}` : "—"}
        delta={
          <Text size="xs" c="dimmed">
            {t.norm_days ? "закрытых дней" : "дни ещё не закрыты"}
          </Text>
        }
      />
    </SimpleGrid>
  );
}

function StateTiles({ review }: { review: Review }) {
  return (
    <SimpleGrid cols={{ base: 1, xs: 3 }}>
      {SCALES.map((scale) => {
        const now = review.state[scale.key];
        return (
          <Tile
            key={scale.key}
            label={`${scale.icon} ${scale.label}`}
            value={
              now === null ? (
                "—"
              ) : (
                <Text span inherit c={scoreText(now)}>
                  {formatScore(now)}
                  <Text span size="sm" c="dimmed" fw={500}>
                    {" "}
                    / 10
                  </Text>
                </Text>
              )
            }
            delta={<Delta now={now} before={review.prev_state[scale.key]} format={formatScore} />}
          />
        );
      })}
    </SimpleGrid>
  );
}

function shortDay(day: string, kind: PeriodKind): string {
  const date = new Date(`${day}T12:00:00`);
  return kind === "week"
    ? date.toLocaleDateString("ru-RU", { weekday: "short" })
    : String(date.getDate());
}

// По дням: столбики — фокус (цвет — норма), линия — среднее состояние по дневнику.
function DaysChart({ days, kind }: { days: DayPoint[]; kind: PeriodKind }) {
  const scheme = useComputedColorScheme("light");
  const option = useMemo<EChartOption>(() => {
    const theme = chartTheme(scheme);
    const axisLabel = { color: theme.textSecondary };
    return {
      animation: false,
      grid: { left: 40, right: 36, top: 24, bottom: 24 },
      tooltip: {
        trigger: "axis",
        valueFormatter: (value: number | null) => (value === null ? "—" : String(value)),
      },
      legend: { top: 0, right: 0, textStyle: { color: theme.textSecondary } },
      xAxis: {
        type: "category",
        data: days.map((d) => shortDay(d.day, kind)),
        axisLabel,
        axisLine: { lineStyle: { color: theme.grid } },
      },
      yAxis: [
        {
          type: "value",
          name: "ч",
          axisLabel,
          nameTextStyle: axisLabel,
          splitLine: { lineStyle: { color: theme.grid } },
        },
        { type: "value", min: 1, max: 10, interval: 3, axisLabel, splitLine: { show: false } },
      ],
      series: [
        {
          name: "Фокус, ч",
          type: "bar",
          barMaxWidth: 28,
          data: days.map((d) => ({
            value: Math.round((d.focus_min / 60) * 10) / 10,
            itemStyle: { color: d.status ? DAY_STATUS[d.status].color : theme.neutral, borderRadius: [3, 3, 0, 0] },
          })),
        },
        {
          name: "Состояние",
          type: "line",
          yAxisIndex: 1,
          connectNulls: true,
          symbolSize: 7,
          itemStyle: { color: theme.series(6) },
          data: days.map((d) => d.state),
        },
      ],
    };
  }, [days, kind, scheme]);
  return (
    <Paper withBorder p="md">
      <Stack gap="xs">
        <Text fw={600}>По дням</Text>
        <EChart option={option} height={220} />
        <Text size="xs" c="dimmed">
          Цвет столбика — норма: зелёный выполнена, синий заморозка, красный пропуск, серый — день ещё
          не закрыт или пауза. Линия — среднее настроения, энергии и желания из дневника.
        </Text>
      </Stack>
    </Paper>
  );
}

function AnalysisCard({ review, kind, offset }: { review: Review; kind: PeriodKind; offset: number }) {
  const analyze = useAnalyzeReview(kind, offset);
  const run = () =>
    analyze.mutate(undefined, {
      onSuccess: (result) =>
        result.agent_failed &&
        notifications.show({ color: "yellow", message: "Агент сейчас недоступен. Попробуй позже." }),
      onError: (error) => notifications.show({ color: "red", message: error.message }),
    });
  const a = review.analysis;
  const sections: [string, string[]][] = a
    ? [
        ["Получилось", a.wins],
        ["Буксовало", a.struggles],
        ["Связи", a.patterns],
        ["Фокус дальше", a.next_steps],
      ]
    : [];
  return (
    <Paper withBorder p="md">
      <Stack gap="sm">
        <Group justify="space-between">
          <Group gap="xs">
            <ThemeIcon variant="light" color="violet" size="md">
              <IconSparkles size={16} />
            </ThemeIcon>
            <Text fw={600}>Разбор агентом</Text>
          </Group>
          <Button
            size="xs"
            variant={a ? "default" : "filled"}
            color="violet"
            loading={analyze.isPending}
            onClick={run}
          >
            {a ? "Разобрать заново" : "Разобрать"}
          </Button>
        </Group>
        {!a && (
          <Text size="sm" c="dimmed">
            Агент посмотрит на цифры, сферы и записи дневника: что получилось, что буксовало, какие
            связи видны и на чём сосредоточиться дальше. Займёт около минуты.
          </Text>
        )}
        {a && (
          <>
            <Text>{a.summary}</Text>
            <SimpleGrid cols={{ base: 1, sm: 2 }}>
              {sections
                .filter(([, items]) => items.length > 0)
                .map(([title, items]) => (
                  <Stack key={title} gap={4}>
                    <Text size="sm" fw={600}>
                      {title}
                    </Text>
                    <List size="sm" spacing={2}>
                      {items.map((item) => (
                        <List.Item key={item}>{item}</List.Item>
                      ))}
                    </List>
                  </Stack>
                ))}
            </SimpleGrid>
            {review.analyzed_at && (
              <Text size="xs" c="dimmed">
                Разобрано{" "}
                {new Date(review.analyzed_at).toLocaleString("ru-RU", {
                  day: "numeric",
                  month: "short",
                  hour: "2-digit",
                  minute: "2-digit",
                })}
                {review.in_progress && " — период ещё идёт, цифры с тех пор могли измениться"}
              </Text>
            )}
          </>
        )}
      </Stack>
    </Paper>
  );
}

function SphereCard({ sphere, color, icon }: { sphere: SphereReview; color: string; icon: string | null }) {
  const Icon = goalIcon(icon);
  const idle = sphere.xp === 0 && sphere.mentions === 0;
  return (
    <Paper withBorder p="md" style={{ borderLeft: `4px solid ${color}` }}>
      <Stack gap="xs">
        <Group justify="space-between" wrap="nowrap">
          <Group gap="xs" wrap="nowrap">
            <Icon size={18} color={color} />
            <Text fw={600}>{sphere.title}</Text>
          </Group>
          {idle && (
            <Badge color="gray" variant="light">
              без движения
            </Badge>
          )}
        </Group>
        <Group gap="lg">
          <Stack gap={0}>
            <Text size="xs" c="dimmed">
              опыт
            </Text>
            <Group gap={6} align="baseline">
              <Text fw={600}>{sphere.xp} XP</Text>
              <Delta now={sphere.xp} before={sphere.prev_xp} />
            </Group>
          </Stack>
          <Stack gap={0}>
            <Text size="xs" c="dimmed">
              фокус · задач
            </Text>
            <Text fw={600}>
              {formatMinutes(sphere.minutes)} · {sphere.done_tasks}
            </Text>
          </Stack>
          <Stack gap={0}>
            <Text size="xs" c="dimmed">
              оценка в дневнике
            </Text>
            <Group gap={6} align="baseline">
              <Text fw={600} c={scoreText(sphere.score)}>
                {sphere.score !== null ? `${formatScore(sphere.score)}/10` : "—"}
              </Text>
              <Delta now={sphere.score} before={sphere.prev_score} format={formatScore} />
            </Group>
          </Stack>
        </Group>
        {sphere.good.map((note) => (
          <Text key={`g-${note}`} size="sm">
            <Text span c="teal" fw={600}>
              +{" "}
            </Text>
            {note}
          </Text>
        ))}
        {sphere.bad.map((note) => (
          <Text key={`b-${note}`} size="sm">
            <Text span c="red" fw={600}>
              −{" "}
            </Text>
            {note}
          </Text>
        ))}
      </Stack>
    </Paper>
  );
}

function Spheres({ review }: { review: Review }) {
  const goals = useGoals();
  const toHex = useGoalColor();
  if (review.spheres.length === 0) return null;
  return (
    <Stack gap="xs">
      <Title order={4}>Сферы</Title>
      <SimpleGrid cols={{ base: 1, md: 2 }}>
        {review.spheres.map((sphere) => {
          const goal = goals.data?.find((g) => g.id === sphere.goal_id);
          return (
            <SphereCard
              key={sphere.goal_id}
              sphere={sphere}
              color={toHex(goal?.color ?? "blue")}
              icon={goal?.icon ?? null}
            />
          );
        })}
      </SimpleGrid>
    </Stack>
  );
}

function Tags({ items, color }: { items: [string, number][]; color: string }) {
  if (items.length === 0) {
    return (
      <Text size="sm" c="dimmed">
        факторов не отмечено
      </Text>
    );
  }
  return (
    <Group gap={6}>
      {items.map(([name, count]) => (
        <Badge key={name} color={color} variant="light" tt="none">
          {name}
          {count > 1 ? ` ×${count}` : ""}
        </Badge>
      ))}
    </Group>
  );
}

function GroupCard({ title, hint, group, color }: { title: string; hint: string; group: DayGroup; color: string }) {
  return (
    <Paper withBorder p="md">
      <Stack gap="xs">
        <Group justify="space-between">
          <Text fw={600}>{title}</Text>
          <Tooltip label={hint}>
            <Badge color={color} variant="light">
              {group.days}
            </Badge>
          </Tooltip>
        </Group>
        {group.days > 0 ? (
          <>
            <Text size="sm" c="dimmed">
              В среднем фокус {formatMinutes(Math.round(group.focus_min ?? 0))}, {Math.round(group.xp ?? 0)} XP за день
            </Text>
            <Tags items={group.factors} color={color} />
          </>
        ) : (
          <Text size="sm" c="dimmed">
            Таких дней не было.
          </Text>
        )}
      </Stack>
    </Paper>
  );
}

function Patterns({ review }: { review: Review }) {
  const noDiary = review.totals.entries === 0;
  return (
    <Stack gap="xs">
      <Title order={4}>Плохие и хорошие дни</Title>
      {noDiary ? (
        <Text size="sm" c="dimmed">
          За этот период нет записей в дневнике — без них не видно, какие дни были плохими.
        </Text>
      ) : (
        <>
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <GroupCard title="Плохие дни" hint="Среднее состояние ниже 5" group={review.bad_days} color="red" />
            <GroupCard title="Хорошие дни" hint="Среднее состояние от 7" group={review.good_days} color="teal" />
          </SimpleGrid>
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <Stack gap={4}>
              <Text size="sm" fw={600}>
                Частые факторы
              </Text>
              <Tags items={review.factors} color="gray" />
            </Stack>
            <Stack gap={4}>
              <Text size="sm" fw={600}>
                Частые эмоции
              </Text>
              <Tags items={review.emotions} color="gray" />
            </Stack>
          </SimpleGrid>
        </>
      )}
    </Stack>
  );
}

function TopTasks({ review, onOpen }: { review: Review; onOpen: (id: number) => void }) {
  if (review.top_tasks.length === 0) return null;
  return (
    <Stack gap="xs">
      <Title order={4}>Самые весомые задачи</Title>
      <Paper withBorder>
        {review.top_tasks.map((task, index) => (
          <Group
            key={task.id}
            justify="space-between"
            wrap="nowrap"
            px="md"
            py="xs"
            style={{
              cursor: "pointer",
              borderTop: index ? "1px solid var(--mantine-color-default-border)" : undefined,
            }}
            onClick={() => onOpen(task.id)}
          >
            <Text truncate>{task.title}</Text>
            <Text fw={600} c="violet" style={{ flexShrink: 0 }}>
              +{task.xp} XP
            </Text>
          </Group>
        ))}
      </Paper>
    </Stack>
  );
}

// Итоги недели или месяца: цифры против того же отрезка прошлого периода, сферы, дни
// и разбор агентом. Период живёт в адресе: ссылку на прошлую неделю можно открыть сразу.
export function ReviewPage() {
  const [params, setParams] = useSearchParams();
  const kind: PeriodKind = params.get("kind") === "month" ? "month" : "week";
  const offset = Math.max(Number(params.get("offset") ?? 0) || 0, 0);
  const review = useReview(kind, offset);
  const [openTaskId, setOpenTaskId] = useState<number | null>(null);
  const go = (next: { kind?: PeriodKind; offset?: number }) => {
    const nextKind = next.kind ?? kind;
    const nextOffset = next.offset ?? offset;
    setParams({
      ...(nextKind === "month" ? { kind: "month" } : {}),
      ...(nextOffset ? { offset: String(nextOffset) } : {}),
    });
  };
  const data = review.data;

  return (
    <Stack gap="lg">
      <Stack gap={4}>
        <Title order={2}>Итоги</Title>
        <Text c="dimmed" size="sm">
          Как прошли неделя или месяц: работа, состояние и сферы рядом. Пока период идёт, он
          сравнивается с тем же числом дней {PERIOD_NAME[kind].previous}.
        </Text>
      </Stack>

      <Group justify="space-between">
        <SegmentedControl
          value={kind}
          onChange={(value) => go({ kind: value as PeriodKind, offset: 0 })}
          data={[
            { value: "week", label: "Неделя" },
            { value: "month", label: "Месяц" },
          ]}
        />
        <Group gap="xs" wrap="nowrap">
          <ActionIcon variant="default" aria-label="Раньше" onClick={() => go({ offset: offset + 1 })}>
            <IconChevronLeft size={16} />
          </ActionIcon>
          <Text fw={600} miw={170} ta="center">
            {data ? (offset === 0 ? `${PERIOD_NAME[kind].current} · ${data.label}` : data.label) : "…"}
          </Text>
          <ActionIcon
            variant="default"
            aria-label="Позже"
            disabled={offset === 0}
            onClick={() => go({ offset: offset - 1 })}
          >
            <IconChevronRight size={16} />
          </ActionIcon>
        </Group>
      </Group>

      {review.isError && (
        <Alert color="red" title="Не удалось посчитать итоги">
          {review.error.message}
        </Alert>
      )}
      {review.isPending && <Skeleton h={420} />}
      {data && (
        <>
          <Totals review={data} />
          <StateTiles review={data} />
          <DaysChart days={data.days} kind={kind} />
          <AnalysisCard review={data} kind={kind} offset={offset} />
          <Spheres review={data} />
          <Patterns review={data} />
          <TopTasks review={data} onOpen={setOpenTaskId} />
        </>
      )}

      <TaskDrawer taskId={openTaskId} onClose={() => setOpenTaskId(null)} onPlanned={() => setOpenTaskId(null)} />
    </Stack>
  );
}
