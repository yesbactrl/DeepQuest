import { useComputedColorScheme } from "@mantine/core";
import {
  IconBarbell,
  IconBook,
  IconBrain,
  IconBrandTelegram,
  IconBriefcase,
  IconCode,
  IconCoin,
  IconDental,
  IconFlame,
  IconHeartbeat,
  IconHome,
  IconLanguage,
  IconMoon,
  IconMusic,
  IconPalette,
  IconPigMoney,
  IconPlane,
  IconRocket,
  IconRun,
  IconSpeakerphone,
  IconTarget,
  IconTrendingUp,
  IconUsers,
  IconVideo,
  type Icon,
} from "@tabler/icons-react";

import { chartTheme, colorSlot } from "./chartTheme";

// Иконки статов. В базе хранится ключ, поэтому список можно менять, не трогая данные:
// неизвестный ключ показывается мишенью.
export const GOAL_ICONS: Record<string, Icon> = {
  target: IconTarget,
  megaphone: IconSpeakerphone,
  video: IconVideo,
  telegram: IconBrandTelegram,
  coin: IconCoin,
  "piggy-bank": IconPigMoney,
  "trending-up": IconTrendingUp,
  briefcase: IconBriefcase,
  rocket: IconRocket,
  code: IconCode,
  heart: IconHeartbeat,
  barbell: IconBarbell,
  run: IconRun,
  tooth: IconDental,
  moon: IconMoon,
  brain: IconBrain,
  book: IconBook,
  language: IconLanguage,
  palette: IconPalette,
  music: IconMusic,
  flame: IconFlame,
  home: IconHome,
  users: IconUsers,
  plane: IconPlane,
};

export function goalIcon(name: string | null): Icon {
  return (name && GOAL_ICONS[name]) || IconTarget;
}

// Цвет цели в текущей теме: в светлой и тёмной оттенки немного разные.
export function useGoalColor(): (color: string) => string {
  const theme = chartTheme(useComputedColorScheme("light"));
  return (color) => theme.series(colorSlot(color));
}
