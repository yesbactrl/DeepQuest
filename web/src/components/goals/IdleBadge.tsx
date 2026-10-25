import { Badge, Tooltip } from "@mantine/core";

import { formatDays } from "../../lib/format";

// Цель без движения неделю и больше — повод заметить, что она заброшена.
export function IdleBadge({ days }: { days: number }) {
  const color = days >= 7 ? "red" : days >= 3 ? "yellow" : "teal";
  const label = days === 0 ? "двигалась сегодня" : `${formatDays(days)} без движения`;
  return (
    <Tooltip label="Считается от последнего начисления XP по цели">
      <Badge color={color} variant="light" size="sm">
        {label}
      </Badge>
    </Tooltip>
  );
}
