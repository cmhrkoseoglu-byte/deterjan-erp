import {
  AppShell,
  Avatar,
  Badge,
  Box,
  Burger,
  Group,
  Menu,
  NavLink,
  ScrollArea,
  Text,
  UnstyledButton,
} from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { IconChevronDown, IconLogout, IconShieldLock } from "@tabler/icons-react";
import { Link, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { SECURITY_PATH } from "../auth/paths";
import { displayName } from "../auth/roles";
import { tr } from "../i18n/tr";
import { InncosLogo } from "../components/brand/InncosLogo";
import { ProblemReportButton } from "../components/problem/ProblemReportButton";
import { NotificationBell } from "../workflow/NotificationBell";
import { RealtimeProvider } from "../workflow/realtime";
import classes from "./AppLayout.module.css";
import { HeaderSearch } from "./HeaderSearch";
import { visibleMenu } from "./menu";
import { roleBar } from "./roleBar";
import { ThemeMenuItem, ThemeToggle } from "./ThemeToggle";

/** Sol menü zemini: DentMesher kenar çubuğu gibi iki temada da koyu lacivert. */
const NAV_BACKGROUND = "#0a0f1c";

export function AppLayout() {
  const { user, logout } = useAuth();
  const [opened, { toggle, close }] = useDisclosure(false);
  const location = useLocation();
  const navigate = useNavigate();

  if (!user) return null;
  const items = visibleMenu(user);
  const name = displayName(user);
  const bar = roleBar(user);

  const isActive = (path: string) =>
    path === "/" ? location.pathname === "/" : location.pathname.startsWith(path);

  async function handleLogout() {
    await logout();
    navigate("/login", { replace: true });
  }

  return (
    <RealtimeProvider>
      <AppShell
        header={{ height: 68 }}
        // 768 px (sm) ve üstünde menü sabit açık; daha dar ekranda hamburger menü.
        navbar={{ width: 240, breakpoint: "sm", collapsed: { mobile: !opened } }}
        padding="md"
      >
        <AppShell.Header
          className={classes.header}
          data-role={bar.role}
          style={{
            background: `linear-gradient(100deg, ${bar.from}, ${bar.to})`,
            borderBottom: "1px solid rgba(255, 255, 255, 0.14)",
          }}
        >
          <Group h="100%" px="md" justify="space-between" wrap="nowrap">
            <Group gap="sm" wrap="nowrap">
              <Burger
                opened={opened}
                onClick={toggle}
                hiddenFrom="sm"
                size="md"
                color="white"
                aria-label={tr.layout.openMenu}
              />
              <Link to="/" className={classes.brand} aria-label={tr.appName}>
                <InncosLogo part="mark" className={classes.logoMark} />
                <span className={classes.brandText}>
                  <InncosLogo part="wordmark" className={classes.logoWord} />
                  <span className={classes.panel}>{tr.layout.panels[bar.role]}</span>
                </span>
              </Link>
              <HeaderSearch />
            </Group>
            <Group gap={4} wrap="nowrap">
              <ProblemReportButton />
              <NotificationBell />
              {/* Telefonda çubukta yer kalmadığı için tema düğmesi kullanıcı menüsüne geçer. */}
              <Box visibleFrom="xs">
                <ThemeToggle />
              </Box>
              <Menu position="bottom-end" width={240}>
                <Menu.Target>
                  <UnstyledButton className={classes.user}>
                    <Group gap="xs" wrap="nowrap">
                      <Avatar radius="xl" variant="white" color="dark">
                        {name.charAt(0).toLocaleUpperCase("tr-TR")}
                      </Avatar>
                      <Text fw={500} visibleFrom="sm">
                        {name}
                      </Text>
                      <Box visibleFrom="sm" display="flex">
                        <IconChevronDown size={16} />
                      </Box>
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
                  <ThemeMenuItem />
                  <Menu.Item leftSection={<IconLogout size={18} />} onClick={handleLogout} py="sm">
                    {tr.auth.logout}
                  </Menu.Item>
                </Menu.Dropdown>
              </Menu>
            </Group>
          </Group>
        </AppShell.Header>

        <AppShell.Navbar
          p="sm"
          style={{
            backgroundColor: NAV_BACKGROUND,
            borderRight: "1px solid rgba(255, 255, 255, 0.06)",
          }}
        >
          <ScrollArea>
            <nav>
              {items.map((item) => {
                const Icon = item.icon;
                const common = {
                  label: item.label,
                  leftSection: <Icon size={22} stroke={1.6} />,
                  onClick: close,
                  py: "sm",
                  className: classes.navLink,
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
