import { ActionIcon, Box, Button, Indicator, Text, Tooltip } from "@mantine/core";
import { IconAlertTriangle, IconCheck, IconLock, IconMinus, IconPlus } from "@tabler/icons-react";
import type { ReactNode } from "react";
import type { SavedOverride } from "../../../api/access";
import { LEVEL_LABELS, type AccessLevel } from "../../../auth/access.gen";
import { formatDateTime } from "../../../i18n/format";
import { isClickable, type CellInfo } from "./matrix";
import { ua } from "./strings";

const COLORS: Record<CellInfo["state"], string> = {
  role: "blue",
  granted: "green",
  revoked: "red",
  none: "gray",
  locked: "gray",
  absent: "gray",
};

function icon(info: CellInfo): ReactNode {
  switch (info.state) {
    case "role":
      return <IconCheck size={18} />;
    case "granted":
      return <IconPlus size={18} />;
    case "revoked":
      return <IconMinus size={18} />;
    case "locked":
      return <IconLock size={16} />;
    default:
      return null;
  }
}

/** Hücrenin durum metni: "Rolden (Depo)", "Eklendi", "Kilitli (Yalnız sistem yöneticisi)". */
function stateText(info: CellInfo): string {
  if (info.state === "role")
    return info.sources.length > 0
      ? `${ua.states.role} (${info.sources.join(", ")})`
      : ua.states.role;
  if (info.state === "locked" && info.lockReason)
    return `${ua.states.locked} (${ua.lockReasons[info.lockReason]})`;
  return ua.states[info.state];
}

function ineffectiveText(info: CellInfo): string | null {
  if (!info.ineffective) return null;
  if (info.ineffective === "redundant")
    return info.state === "revoked" ? ua.ineffective.redundantRevoke : ua.ineffective.redundant;
  return ua.ineffective[info.ineffective];
}

function tooltipText(info: CellInfo, saved: SavedOverride | undefined): string {
  const parts: string[] = [];
  if (info.state === "role" && info.sources.length > 0)
    parts.push(
      info.sources.length === 1 && info.sources[0] === "Herkes"
        ? ua.everyoneSource
        : ua.fromRole(info.sources.join(", ")),
    );
  else parts.push(stateText(info));
  const why = ineffectiveText(info);
  if (why) parts.push(why);
  if (saved && !info.dirty)
    parts.push(
      ua.savedBy(formatDateTime(saved.created_at), saved.created_by_name ?? ua.system, saved.note),
    );
  return parts.join(" · ");
}

interface Props {
  sectionLabel: string;
  level: AccessLevel;
  info: CellInfo;
  saved?: SavedOverride;
  mobile?: boolean;
  readOnly?: boolean;
  onToggle: () => void;
}

/** Yetkiler matrisinin bir hücresi (masaüstü simge düğmesi, telefonda yazılı düğme; plan §6.1). */
export function MatrixCell({
  sectionLabel,
  level,
  info,
  saved,
  mobile,
  readOnly,
  onToggle,
}: Props) {
  const levelLabel = LEVEL_LABELS[level];
  if (info.state === "absent") {
    if (mobile)
      return (
        <Button
          variant="default"
          disabled
          aria-label={`${sectionLabel}: ${levelLabel} — ${ua.states.absent}`}
        >
          —
        </Button>
      );
    return (
      <Text c="dimmed" ta="center" aria-label={ua.states.absent}>
        —
      </Text>
    );
  }
  const why = ineffectiveText(info);
  const label = `${sectionLabel}: ${levelLabel} — ${stateText(info)}${why ? ` · ${why}` : ""}${info.dirty ? ua.unsaved : ""}`;
  const disabled = readOnly || !isClickable(info);
  const color = COLORS[info.state];
  const warn = why;
  const variant = info.state === "none" || info.state === "locked" ? "default" : "light";
  const control = mobile ? (
    <Button
      variant={variant}
      color={color}
      aria-label={label}
      aria-pressed={info.effective}
      disabled={disabled}
      onClick={onToggle}
      leftSection={icon(info)}
      rightSection={
        warn ? <IconAlertTriangle size={14} color="var(--mantine-color-orange-6)" /> : null
      }
      px={6}
    >
      <Box component="span" style={{ display: "flex", flexDirection: "column", lineHeight: 1.1 }}>
        <span>{levelLabel}</span>
        <Text component="span" size="xs">
          {ua.states[info.state]}
        </Text>
      </Box>
    </Button>
  ) : (
    <ActionIcon
      size={36}
      variant={variant}
      color={color}
      aria-label={label}
      aria-pressed={info.effective}
      disabled={disabled}
      onClick={onToggle}
    >
      {icon(info)}
      {info.state === "none" && (
        <Box
          component="span"
          style={{
            position: "absolute",
            width: 1,
            height: 1,
            overflow: "hidden",
            clip: "rect(0 0 0 0)",
          }}
        >
          {ua.states.none}
        </Box>
      )}
    </ActionIcon>
  );
  const marked = (
    <Indicator color="yellow" size={9} disabled={!info.dirty} offset={4}>
      {warn && !mobile ? (
        <Indicator
          color="orange"
          size={14}
          position="bottom-end"
          label={<IconAlertTriangle size={10} />}
          offset={4}
        >
          {control}
        </Indicator>
      ) : (
        control
      )}
    </Indicator>
  );
  return (
    <Tooltip label={tooltipText(info, saved)} multiline maw={320} openDelay={300} withinPortal>
      <Box display="inline-block">{marked}</Box>
    </Tooltip>
  );
}
