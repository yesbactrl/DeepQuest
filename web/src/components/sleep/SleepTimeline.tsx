import { Box, Group, Paper, Stack, Text, Tooltip } from "@mantine/core";
import { useMediaQuery } from "@mantine/hooks";
import type { MouseEvent } from "react";

import type { SleepDay, SleepKind, SleepSession } from "../../api/sleep";
import { NAP_COLOR, NIGHT_COLOR, clock, fromWallMinutes, hours, shiftDay, wallMinutes } from "../../lib/sleep";

// Строка дня — 30 часов: с 18:00 накануне до полуночи. Так в строку целиком входят ночь перед
// днём и весь дневной сон, а сон относится к дню пробуждения.
const WINDOW_START_H = 18;
const WINDOW_MIN = 30 * 60;
const TICKS = [18, 21, 0, 3, 6, 9, 12, 15, 18, 21, 24];
const ROW_H = 30;
const SNAP_MIN = 15;

function windowStart(day: string): number {
  return wallMinutes(shiftDay(day, -1)) + WINDOW_START_H * 60;
}

function percent(minutes: number): string {
  return `${(Math.min(Math.max(minutes, 0), WINDOW_MIN) / WINDOW_MIN) * 100}%`;
}

// У всех строк одна подпись — «сб, 31»: со «Сегодня» и «Вчера» не видно, какое сегодня число.
function weekday(day: string): string {
  return new Date(`${day}T12:00:00`).toLocaleDateString("ru-RU", { weekday: "short", day: "numeric" });
}

function Segment({ session, start, onOpen }: { session: SleepSession; start: number; onOpen: () => void }) {
  const from = wallMinutes(session.start) - start;
  const to = wallMinutes(session.end) - start;
  const color = session.kind === "night" ? NIGHT_COLOR : NAP_COLOR;
  const label = `${session.kind === "night" ? "Ночь" : "Дневной сон"}: ${clock(session.start)}–${clock(session.end)}, ${hours(session.minutes)}${
    session.quality ? ` · качество ${session.quality}/10` : ""
  }`;
  return (
    <Tooltip label={label} withinPortal>
      <Box
        component="button"
        type="button"
        aria-label={label}
        onClick={(event: MouseEvent) => {
          event.stopPropagation();
          onOpen();
        }}
        style={{
          position: "absolute",
          top: 4,
          bottom: 4,
          left: percent(from),
          width: `calc(${percent(to)} - ${percent(from)})`,
          minWidth: 4,
          border: 0,
          borderRadius: 4,
          cursor: "pointer",
          background: `var(--mantine-color-${color}-filled)`,
          color: "white",
          fontSize: 11,
          overflow: "hidden",
          whiteSpace: "nowrap",
          padding: "0 4px",
        }}
      >
        {to - from >= 120 ? hours(session.minutes) : ""}
      </Box>
    </Tooltip>
  );
}

// Неделя сна строками по дням. Клик по пустому месту — записать сон с этого времени,
// клик по отрезку — открыть его.
export function SleepTimeline({
  days,
  today,
  span,
  onOpen,
  onAdd,
}: {
  days: SleepDay[];
  today: string;
  span: number;
  onOpen: (session: SleepSession) => void;
  onAdd: (kind: SleepKind, start: string, end: string) => void;
}) {
  const byDay = new Map(days.map((d) => [d.day, d]));
  const rows = Array.from({ length: span }, (_, i) => shiftDay(today, -i));
  // На телефоне колонки подписей уже: шкале нужно каждое место.
  const narrow = useMediaQuery("(max-width: 36em)") ?? false;
  const labelW = narrow ? 60 : 84;
  const totalW = narrow ? 48 : 64;

  function addAt(day: string, event: MouseEvent<HTMLDivElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    const offset = ((event.clientX - rect.left) / rect.width) * WINDOW_MIN;
    const start = windowStart(day) + Math.round(offset / SNAP_MIN) * SNAP_MIN;
    const hour = Math.floor((((start % 1440) + 1440) % 1440) / 60);
    // Вечер и ночь — ночной сон на 8 часов, днём — час дневного.
    const night = hour >= 19 || hour < 6;
    onAdd(night ? "night" : "nap", fromWallMinutes(start), fromWallMinutes(start + (night ? 480 : 60)));
  }

  return (
    <Paper withBorder p={narrow ? "sm" : "md"}>
      <Stack gap={6}>
        <Group gap={0} wrap="nowrap">
          <Box w={labelW} style={{ flexShrink: 0 }} />
          <Box style={{ position: "relative", flex: 1, height: 16 }}>
            {/* На телефоне — каждые 6 часов: подписи через 3 часа налезают друг на друга. */}
            {TICKS.map((tick, i) =>
              narrow && i % 2 === 1 ? null : (
                <Text
                  key={i}
                  size="xs"
                  c="dimmed"
                  style={{ position: "absolute", left: percent(i * 180), transform: "translateX(-50%)" }}
                >
                  {String(tick % 24).padStart(2, "0")}
                </Text>
              ),
            )}
          </Box>
          <Box w={totalW} style={{ flexShrink: 0 }} />
        </Group>
        {rows.map((day) => {
          const data = byDay.get(day);
          const start = windowStart(day);
          return (
            <Group key={day} gap={0} wrap="nowrap">
              <Text
                size="sm"
                w={labelW}
                style={{ flexShrink: 0 }}
                fw={day === today ? 600 : undefined}
                c={day === today ? "violet" : undefined}
                title={day === today ? "Сегодня" : undefined}
              >
                {weekday(day)}
              </Text>
              <Box
                onClick={(event) => addAt(day, event)}
                title="Нажми, чтобы записать сон с этого времени"
                style={{
                  position: "relative",
                  flex: 1,
                  height: ROW_H,
                  cursor: "copy",
                  borderRadius: 6,
                  background: "var(--mantine-color-default-hover)",
                  // Полночь — тонкая линия: видно, где кончается вчера.
                  backgroundImage: `linear-gradient(to right, transparent calc(${percent(360)} - 0.5px), var(--mantine-color-default-border) calc(${percent(360)} - 0.5px), var(--mantine-color-default-border) calc(${percent(360)} + 0.5px), transparent calc(${percent(360)} + 0.5px))`,
                }}
              >
                {data?.sessions.map((session) => (
                  <Segment key={session.id} session={session} start={start} onOpen={() => onOpen(session)} />
                ))}
              </Box>
              <Text size="sm" w={totalW} ta="right" fw={500} c={data ? undefined : "dimmed"} style={{ flexShrink: 0 }}>
                {data ? hours(data.total_min).replace(" мин", "м").replace(" ч", "ч") : "—"}
              </Text>
            </Group>
          );
        })}
        <Group gap="md">
          <Group gap={6}>
            <Box w={12} h={12} style={{ borderRadius: 3, background: `var(--mantine-color-${NIGHT_COLOR}-filled)` }} />
            <Text size="xs" c="dimmed">
              ночной сон
            </Text>
          </Group>
          <Group gap={6}>
            <Box w={12} h={12} style={{ borderRadius: 3, background: `var(--mantine-color-${NAP_COLOR}-filled)` }} />
            <Text size="xs" c="dimmed">
              дневной сон
            </Text>
          </Group>
          <Text size="xs" c="dimmed">
            Строка — с 18:00 накануне до полуночи. Нажми на пустое место, чтобы записать сон.
          </Text>
        </Group>
      </Stack>
    </Paper>
  );
}
