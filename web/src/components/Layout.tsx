import {
  ActionIcon,
  AppShell,
  Burger,
  Group,
  NavLink,
  Text,
  Tooltip,
  useComputedColorScheme,
  useMantineColorScheme,
} from "@mantine/core";
import { useDisclosure, useHotkeys } from "@mantine/hooks";
import {
  IconBed,
  IconMessageChatbot,
  IconCalendarWeek,
  IconLayoutDashboard,
  IconListCheck,
  IconMoon,
  IconNotebook,
  IconReportAnalytics,
  IconSearch,
  IconSun,
  IconTarget,
  IconUserStar,
} from "@tabler/icons-react";
import { NavLink as RouterLink, Outlet, useLocation, useNavigate } from "react-router";

import { TimerWidget } from "./TimerWidget";

const SECTIONS = [
  { to: "/", label: "Дашборд", icon: IconLayoutDashboard },
  { to: "/character", label: "Персонаж", icon: IconUserStar },
  { to: "/tasks", label: "Задачи", icon: IconListCheck },
  { to: "/plan", label: "План", icon: IconCalendarWeek },
  { to: "/diary", label: "Дневник", icon: IconNotebook },
  { to: "/sleep", label: "Сон", icon: IconBed },
  { to: "/review", label: "Итоги", icon: IconReportAnalytics },
  { to: "/advisor", label: "Советник", icon: IconMessageChatbot },
  { to: "/goals", label: "Цели", icon: IconTarget },
  { to: "/search", label: "Поиск", icon: IconSearch },
];

function ColorSchemeToggle() {
  const { setColorScheme } = useMantineColorScheme();
  const scheme = useComputedColorScheme("light");
  const next = scheme === "dark" ? "light" : "dark";
  return (
    <Tooltip label={next === "dark" ? "Тёмная тема" : "Светлая тема"}>
      <ActionIcon
        variant="subtle"
        color="gray"
        size="lg"
        aria-label="Сменить тему"
        onClick={() => setColorScheme(next)}
      >
        {scheme === "dark" ? <IconSun size={18} /> : <IconMoon size={18} />}
      </ActionIcon>
    </Tooltip>
  );
}

export function Layout() {
  const [opened, { toggle, close }] = useDisclosure();
  const { pathname } = useLocation();
  const navigate = useNavigate();
  // ⌘K / Ctrl+K — поиск с любой страницы, даже из поля ввода.
  useHotkeys([["mod+K", () => navigate("/search")]], []);

  return (
    <AppShell
      header={{ height: 56 }}
      navbar={{ width: 220, breakpoint: "sm", collapsed: { mobile: !opened } }}
      padding="lg"
    >
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between">
          <Group gap="sm">
            <Burger opened={opened} onClick={toggle} hiddenFrom="sm" size="sm" />
            <img src="/favicon.svg" alt="" width={26} height={26} />
            <Text fw={700} size="lg">
              DeepQuest
            </Text>
          </Group>
          <Group gap="sm" wrap="nowrap">
            <TimerWidget />
            <Tooltip label="Поиск · ⌘K">
              <ActionIcon
                variant="subtle"
                color="gray"
                size="lg"
                aria-label="Поиск"
                component={RouterLink}
                to="/search"
              >
                <IconSearch size={18} />
              </ActionIcon>
            </Tooltip>
            <ColorSchemeToggle />
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p="sm">
        {SECTIONS.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            component={RouterLink}
            to={to}
            label={label}
            leftSection={<Icon size={18} stroke={1.6} />}
            active={to === "/" ? pathname === "/" : pathname.startsWith(to)}
            onClick={close}
          />
        ))}
      </AppShell.Navbar>

      <AppShell.Main>
        <Outlet />
      </AppShell.Main>
    </AppShell>
  );
}
