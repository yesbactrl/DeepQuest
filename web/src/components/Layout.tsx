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
import { useDisclosure } from "@mantine/hooks";
import {
  IconLayoutDashboard,
  IconListCheck,
  IconMoon,
  IconSun,
  IconTarget,
} from "@tabler/icons-react";
import { NavLink as RouterLink, Outlet, useLocation } from "react-router";

const SECTIONS = [
  { to: "/", label: "Дашборд", icon: IconLayoutDashboard },
  { to: "/tasks", label: "Задачи", icon: IconListCheck },
  { to: "/goals", label: "Цели", icon: IconTarget },
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
          <ColorSchemeToggle />
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
