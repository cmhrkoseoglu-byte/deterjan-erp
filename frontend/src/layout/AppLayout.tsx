import {
  AppShell,
  Avatar,
  Badge,
  Burger,
  Group,
  Menu,
  NavLink,
  ScrollArea,
  Text,
  Title,
  UnstyledButton,
} from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { IconChevronDown, IconLogout, IconShieldLock } from "@tabler/icons-react";
import { Link, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { SECURITY_PATH } from "../auth/paths";
import { displayName } from "../auth/roles";
import { tr } from "../i18n/tr";
import { ProblemReportButton } from "../components/problem/ProblemReportButton";
import { NotificationBell } from "../workflow/NotificationBell";
import { RealtimeProvider } from "../workflow/realtime";
import { visibleMenu } from "./menu";

export function AppLayout() {
  const { user, logout } = useAuth();
  const [opened, { toggle, close }] = useDisclosure(false);
  const location = useLocation();
  const navigate = useNavigate();

  if (!user) return null;
  const items = visibleMenu(user);
  const name = displayName(user);

  const isActive = (path: string) =>
    path === "/" ? location.pathname === "/" : location.pathname.startsWith(path);

  async function handleLogout() {
    await logout();
    navigate("/login", { replace: true });
  }

  return (
    <RealtimeProvider>
      <AppShell
        header={{ height: 64 }}
        // 768 px (sm) ve üstünde menü sabit açık; daha dar ekranda hamburger menü.
        navbar={{ width: 260, breakpoint: "sm", collapsed: { mobile: !opened } }}
        padding="md"
      >
        <AppShell.Header>
          <Group h="100%" px="md" justify="space-between" wrap="nowrap">
            <Group gap="sm" wrap="nowrap">
              <Burger
                opened={opened}
                onClick={toggle}
                hiddenFrom="sm"
                size="md"
                aria-label={tr.layout.openMenu}
              />
              <Link to="/" style={{ color: "inherit", textDecoration: "none" }}>
                <Title order={3}>{tr.appName}</Title>
              </Link>
            </Group>
            <Group gap="sm" wrap="nowrap">
              <ProblemReportButton />
              <NotificationBell />
              <Menu position="bottom-end" width={240}>
                <Menu.Target>
                  <UnstyledButton p={6} style={{ borderRadius: 8 }}>
                    <Group gap="xs" wrap="nowrap">
                      <Avatar radius="xl" color="blue">
                        {name.charAt(0).toLocaleUpperCase("tr-TR")}
                      </Avatar>
                      <Text fw={500} visibleFrom="xs">
                        {name}
                      </Text>
                      <IconChevronDown size={16} />
                    </Group>
                  </UnstyledButton>
                </Menu.Target>
                <Menu.Dropdown>
                  <Menu.Label>{tr.layout.roles}</Menu.Label>
                  <Group gap={4} px="sm" pb="xs">
                    {user.roles.map((role) => (
                      <Badge key={role} variant="light" size="sm">
                        {tr.roles[role] ?? role}
                      </Badge>
                    ))}
                  </Group>
                  <Menu.Divider />
                  <Menu.Item
                    component={Link}
                    to={SECURITY_PATH}
                    leftSection={<IconShieldLock size={18} />}
                    py="sm"
                  >
                    {tr.layout.security}
                  </Menu.Item>
                  <Menu.Item leftSection={<IconLogout size={18} />} onClick={handleLogout} py="sm">
                    {tr.auth.logout}
                  </Menu.Item>
                </Menu.Dropdown>
              </Menu>
            </Group>
          </Group>
        </AppShell.Header>

        <AppShell.Navbar p="sm">
          <ScrollArea>
            <nav>
              {items.map((item) => {
                const Icon = item.icon;
                const common = {
                  label: item.label,
                  leftSection: <Icon size={22} stroke={1.6} />,
                  onClick: close,
                  py: "sm",
                  style: { borderRadius: 8 },
                } as const;
                return item.external ? (
                  <NavLink key={item.key} component="a" href={item.path} {...common} />
                ) : (
                  <NavLink
                    key={item.key}
                    component={Link}
                    to={item.path}
                    active={isActive(item.path)}
                    {...common}
                  />
                );
              })}
            </nav>
          </ScrollArea>
        </AppShell.Navbar>

        <AppShell.Main>
          <Outlet />
        </AppShell.Main>
      </AppShell>
    </RealtimeProvider>
  );
}
