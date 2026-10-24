import {
  ActionIcon,
  Menu,
  Tooltip,
  useComputedColorScheme,
  useMantineColorScheme,
} from "@mantine/core";
import { IconMoonStars, IconSun } from "@tabler/icons-react";
import { tr } from "../i18n/tr";

/** Gündüz / gece seçimi. Bu tarayıcıda saklanır (Mantine renk şeması yöneticisi). */
function useNightToggle() {
  const { setColorScheme } = useMantineColorScheme();
  const night = useComputedColorScheme("light") === "dark";
  return {
    night,
    label: night ? tr.layout.dayTheme : tr.layout.nightTheme,
    toggle: () => setColorScheme(night ? "light" : "dark"),
  };
}

/** Üst çubuktaki gündüz / gece düğmesi. */
export function ThemeToggle() {
  const { night, label, toggle } = useNightToggle();
  return (
    <Tooltip label={label}>
      <ActionIcon
        variant="subtle"
        color="gray"
        size="xl"
        radius="xl"
        aria-label={label}
        onClick={toggle}
      >
        {night ? <IconSun size={24} /> : <IconMoonStars size={24} />}
      </ActionIcon>
    </Tooltip>
  );
}

/** Telefonda aynı seçim kullanıcı menüsünde (çubukta yer yok). */
export function ThemeMenuItem() {
  const { night, label, toggle } = useNightToggle();
  return (
    <Menu.Item
      hiddenFrom="xs"
      leftSection={night ? <IconSun size={18} /> : <IconMoonStars size={18} />}
      onClick={toggle}
      py="sm"
    >
      {label}
    </Menu.Item>
  );
}
