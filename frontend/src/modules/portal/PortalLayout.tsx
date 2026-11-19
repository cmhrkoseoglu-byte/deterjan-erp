import { AppShell, Box, Burger, Group, NavLink, ScrollArea, Stack, Text } from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import {
  IconFileInvoice,
  IconLogout,
  IconPackageImport,
  IconReceipt,
  IconShieldLock,
  IconTruckDelivery,
} from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Link, Navigate, Outlet, useLocation, useNavigate } from "react-router-dom";
import { fetchPortalMe } from "../../api/portal";
import { useAuth } from "../../auth/AuthContext";
import { PORTAL_SECURITY_PATH } from "../../auth/paths";
import { InncosLogo } from "../../components/brand/InncosLogo";
import { ThemeToggle } from "../../layout/ThemeToggle";
import { PORTAL_PATHS, portalKind } from "./config";
import { pt } from "./strings";

interface MenuItem {
  path: string;
  label: string;
  icon: ReactNode;
}

const CUSTOMER_MENU: MenuItem[] = [
  { path: PORTAL_PATHS.orders, label: pt.menu.orders, icon: <IconReceipt size={18} /> },
  {
    path: PORTAL_PATHS.shipments,
    label: pt.menu.shipments,
    icon: <IconTruckDelivery size={18} />,
  },
  { path: PORTAL_PATHS.ledger, label: pt.menu.ledger, icon: <IconFileInvoice size={18} /> },
];

const SUPPLIER_MENU: MenuItem[] = [
  { path: PORTAL_PATHS.orders, label: pt.menu.orders, icon: <IconReceipt size={18} /> },
  {
    path: PORTAL_PATHS.receipts,
    label: pt.menu.receipts,
    icon: <IconPackageImport size={18} />,
  },
  { path: PORTAL_PATHS.ledger, label: pt.menu.ledger, icon: <IconFileInvoice size={18} /> },
];

/**
 * Portal düzeni (müşteri ve tedarikçi yetkilisi): firma adı, sade menü, Güvenlik ve çıkış.
 * Çalışan menüsü, bildirim zili, arama ve canlı bildirim bağlantısı yoktur.
 */
export function PortalLayout() {
  const { user, logout } = useAuth();
  const [opened, { toggle, close }] = useDisclosure(false);
  const location = useLocation();
  const navigate = useNavigate();
  const kind = portalKind(user);
  const me = useQuery({
    queryKey: ["portal", "me"],
    queryFn: fetchPortalMe,
    enabled: kind !== null && !user?.password_change_required,
  });

  if (!user || kind === null) return null;
  const items = kind === "customer" ? CUSTOMER_MENU : SUPPLIER_MENU;

  async function handleLogout() {
    await logout();
    navigate("/login", { replace: true });
  }

  const link = (item: MenuItem) => (
    <NavLink
      key={item.path}
      component={Link}
      to={item.path}
      label={item.label}
      leftSection={item.icon}
      active={location.pathname.startsWith(item.path)}
      onClick={close}
    />
  );

  return (
    <AppShell
      header={{ height: 60 }}
      navbar={{ width: 220, breakpoint: "sm", collapsed: { mobile: !opened } }}
      padding="md"
    >
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between" wrap="nowrap">
          <Group gap="sm" wrap="nowrap">
            <Burger opened={opened} onClick={toggle} hiddenFrom="sm" size="sm" />
            <Box w={28} c="var(--mantine-primary-color-filled)">
              <InncosLogo part="mark" />
            </Box>
            <Stack gap={0}>
              <Text fw={700} size="sm" lineClamp={1} data-testid="portal-firm">
                {me.data?.firm_name ?? ""}
              </Text>
              <Text size="xs" c="dimmed">
                {kind === "customer" ? pt.customerPortal : pt.supplierPortal}
              </Text>
            </Stack>
          </Group>
          <ThemeToggle />
        </Group>
      </AppShell.Header>
      <AppShell.Navbar p="xs">
        <ScrollArea style={{ flex: 1 }}>{items.map(link)}</ScrollArea>
        {link({
          path: PORTAL_SECURITY_PATH,
          label: pt.menu.security,
          icon: <IconShieldLock size={18} />,
        })}
        <NavLink label={pt.logout} leftSection={<IconLogout size={18} />} onClick={handleLogout} />
      </AppShell.Navbar>
      <AppShell.Main>
        <Outlet />
      </AppShell.Main>
    </AppShell>
  );
}

/** `/portal`: Siparişlerim'e yönlendirir. */
export function PortalHome() {
  return <Navigate to={PORTAL_PATHS.orders} replace />;
}
