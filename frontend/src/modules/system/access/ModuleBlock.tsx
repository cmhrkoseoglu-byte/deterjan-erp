import {
  ActionIcon,
  Badge,
  Box,
  Button,
  Card,
  Checkbox,
  Group,
  Menu,
  Paper,
  Stack,
  Table,
  Text,
  Tooltip,
  UnstyledButton,
} from "@mantine/core";
import {
  IconChevronDown,
  IconChevronRight,
  IconDots,
  IconEyeCheck,
  IconInfoCircle,
  IconRestore,
  IconTrash,
} from "@tabler/icons-react";
import { memo, type ReactNode } from "react";
import type { SavedOverride } from "../../../api/access";
import { LEVEL_LABELS, type AccessLevel } from "../../../auth/access.gen";
import {
  cellId,
  cellInfo,
  columnState,
  GRANT_LEVELS,
  hasLetter,
  joinTr,
  moduleLabel,
  openRecordsKey,
  openRecordsReaders,
  readThroughNotes,
  section,
  type Draft,
  type GrantLevel,
  type Letters,
  type Note,
  type OverrideMap,
} from "./matrix";
import { MatrixCell } from "./MatrixCell";
import { RECORD_NOUNS, ua } from "./strings";

export interface RowsProps {
  keys: readonly string[];
  draft: Draft;
  saved: OverrideMap;
  savedRows: ReadonlyMap<string, SavedOverride>;
  defaults: Letters;
  preview: Letters;
  notes: readonly Note[];
  effects: readonly string[];
  mobile: boolean;
  readOnly: boolean;
  onToggle: (key: string, level: AccessLevel) => void;
}

function helpText(key: string): string {
  const meta = section(key);
  if (!meta) return "";
  return Object.entries(meta.help)
    .map(([level, text]) => `${LEVEL_LABELS[level as AccessLevel]}: ${text}`)
    .join(" ");
}

/** Satırın altındaki açıklamalar (ön koşul, okumaya devam eden kayıtlar, açık kayıtlar). */
function rowNotes(key: string, props: RowsProps): { text: string; error?: boolean }[] {
  const meta = section(key)!;
  const items: { text: string; error?: boolean }[] = props.notes
    .filter((note) => note.key === key)
    .map((note) => ({ text: note.text, error: note.error }));
  if (meta.kind === "open_records") {
    if (!hasLetter(props.preview, key, "read")) {
      const readers = openRecordsReaders(props.preview, meta.module);
      items.push({
        text: readers.length > 0 ? ua.stillReads(joinTr(readers)) : ua.noLongerReads,
      });
      if (props.effects.length > 0)
        items.push({ text: ua.affectedScreens(props.effects.join(" ")) });
    }
    return items;
  }
  for (const text of readThroughNotes(props.preview, key, RECORD_NOUNS)) items.push({ text });
  if (meta.read === "open" && !hasLetter(props.preview, key, "view")) {
    const records = openRecordsKey(meta.module);
    if (records && hasLetter(props.preview, records, "read")) items.push({ text: ua.openReadNote });
  }
  return items;
}

function SectionLabel({ sectionKey }: { sectionKey: string }) {
  const meta = section(sectionKey)!;
  const help = helpText(sectionKey);
  return (
    <Group gap={4} wrap="nowrap">
      <Text size="sm" fw={500}>
        {meta.label}
      </Text>
      {help && (
        <Tooltip label={help} multiline maw={360} withinPortal>
          <Box component="span" display="inline-flex" c="dimmed" aria-label={help}>
            <IconInfoCircle size={14} />
          </Box>
        </Tooltip>
      )}
    </Group>
  );
}

function OpenRecordsControl({ sectionKey, props }: { sectionKey: string; props: RowsProps }) {
  const meta = section(sectionKey)!;
  const id = cellId(sectionKey, "read");
  const closed = props.draft.overrides.get(id) === "revoke";
  const dirty = props.draft.overrides.get(id) !== props.saved.get(id);
  const text = closed ? ua.openRecordsClosed : ua.openRecordsOpen;
  return (
    <Button
      size="xs"
      variant={closed ? "light" : "default"}
      color={closed ? "red" : "blue"}
      aria-label={`${moduleLabel(meta.module)}: ${ua.openRecords} — ${text}${dirty ? ua.unsaved : ""}`}
      aria-pressed={!closed}
      disabled={props.readOnly}
      onClick={() => props.onToggle(sectionKey, "read")}
      rightSection={
        dirty ? (
          <Box w={8} h={8} bg="yellow" style={{ borderRadius: "50%" }} aria-hidden />
        ) : undefined
      }
    >
      {text}
    </Button>
  );
}

function cellProps(key: string, level: AccessLevel, props: RowsProps) {
  return {
    sectionLabel: section(key)!.label,
    level,
    info: cellInfo(props.draft, props.saved, key, level, props.defaults, props.preview),
    saved: props.savedRows.get(cellId(key, level)),
    mobile: props.mobile,
    readOnly: props.readOnly,
    onToggle: () => props.onToggle(key, level),
  };
}

function NoteLines({ items }: { items: { text: string; error?: boolean }[] }) {
  return (
    <Stack gap={2}>
      {items.map((item) => (
        <Text key={item.text} size="xs" c={item.error ? "red" : "dimmed"}>
          {item.text}
        </Text>
      ))}
    </Stack>
  );
}

/** Bölüm satırları: masaüstünde tablo, telefonda kartlar (plan §6.1). */
export function SectionRows(props: RowsProps) {
  if (props.mobile) {
    return (
      <Stack gap="xs">
        {props.keys.map((key) => {
          const meta = section(key)!;
          const notes = rowNotes(key, props);
          return (
            <Card key={key} withBorder padding="sm" data-testid={`section-${key}`}>
              <Stack gap={6}>
                <SectionLabel sectionKey={key} />
                {meta.kind === "open_records" ? (
                  <OpenRecordsControl sectionKey={key} props={props} />
                ) : (
                  <Group grow gap={6}>
                    {GRANT_LEVELS.map((level) => (
                      <MatrixCell key={level} {...cellProps(key, level, props)} />
                    ))}
                  </Group>
                )}
                {notes.length > 0 && <NoteLines items={notes} />}
              </Stack>
            </Card>
          );
        })}
      </Stack>
    );
  }
  return (
    <Table.ScrollContainer minWidth={560}>
      <Table verticalSpacing={4}>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>{ua.sectionColumn}</Table.Th>
            {GRANT_LEVELS.map((level) => (
              <Table.Th key={level} ta="center" w={110}>
                {LEVEL_LABELS[level]}
              </Table.Th>
            ))}
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {props.keys.flatMap((key) => {
            const meta = section(key)!;
            const notes = rowNotes(key, props);
            const rows: ReactNode[] = [
              <Table.Tr key={key} data-testid={`section-${key}`}>
                <Table.Td>
                  <SectionLabel sectionKey={key} />
                </Table.Td>
                {meta.kind === "open_records" ? (
                  <Table.Td colSpan={3} ta="center">
                    <OpenRecordsControl sectionKey={key} props={props} />
                  </Table.Td>
                ) : (
                  GRANT_LEVELS.map((level) => (
                    <Table.Td key={level} ta="center">
                      <MatrixCell {...cellProps(key, level, props)} />
                    </Table.Td>
                  ))
                )}
              </Table.Tr>,
            ];
            if (notes.length > 0)
              rows.push(
                <Table.Tr key={`${key}-notes`}>
                  <Table.Td colSpan={4} pt={0}>
                    <NoteLines items={notes} />
                  </Table.Td>
                </Table.Tr>,
              );
            return rows;
          })}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  );
}

interface BlockProps extends RowsProps {
  moduleKey: string;
  label: string;
  /** Menüde mi (`null`: menüde kendi modülü yok). */
  inMenu: boolean | null;
  overrideCount: number;
  expanded: boolean;
  onExpand: () => void;
  onColumn: (level: GrantLevel, on: boolean) => void;
  onBulk: (action: "reset" | "viewOnly" | "removeAll") => void;
}

/** Bir modülün açılır kapanır bloğu: başlıkta üç durumlu kutular ve toplu işlemler. */
export const ModuleBlock = memo(function ModuleBlock(props: BlockProps) {
  const { moduleKey, label, expanded, mobile, readOnly } = props;
  return (
    <Paper withBorder radius="md" p="sm" role="region" aria-label={label}>
      <Group justify="space-between" wrap="nowrap" gap="xs">
        <UnstyledButton onClick={props.onExpand} aria-expanded={expanded} style={{ flex: 1 }}>
          <Group gap="xs" wrap="wrap">
            {expanded ? <IconChevronDown size={18} /> : <IconChevronRight size={18} />}
            <Text fw={600}>{label}</Text>
            {props.inMenu !== null && (
              <Badge size="sm" variant="outline" color={props.inMenu ? "teal" : "gray"}>
                {props.inMenu ? ua.inMenu : ua.notInMenu}
              </Badge>
            )}
            {props.overrideCount > 0 && (
              <Badge size="sm" color="teal" variant="light">
                {ua.overrideCount(props.overrideCount)}
              </Badge>
            )}
          </Group>
        </UnstyledButton>
        {!mobile && (
          <Group gap="md" wrap="nowrap">
            {GRANT_LEVELS.map((level) => {
              const state = columnState(props.draft, moduleKey, level, props.preview);
              return (
                <Checkbox
                  key={level}
                  aria-label={ua.columnToggle(label, LEVEL_LABELS[level])}
                  checked={state === "all"}
                  indeterminate={state === "some"}
                  disabled={readOnly || state === "empty"}
                  onChange={() => props.onColumn(level, state !== "all")}
                  w={110}
                  styles={{ body: { justifyContent: "center" } }}
                />
              );
            })}
          </Group>
        )}
        {!readOnly && (
          <Menu position="bottom-end" withinPortal>
            <Menu.Target>
              <ActionIcon variant="subtle" color="gray" aria-label={ua.moduleActions(label)}>
                <IconDots size={18} />
              </ActionIcon>
            </Menu.Target>
            <Menu.Dropdown>
              <Menu.Item
                leftSection={<IconRestore size={16} />}
                onClick={() => props.onBulk("reset")}
              >
                {ua.resetModule}
              </Menu.Item>
              <Menu.Item
                leftSection={<IconEyeCheck size={16} />}
                onClick={() => props.onBulk("viewOnly")}
              >
                {ua.viewOnly}
              </Menu.Item>
              <Menu.Item
                color="red"
                leftSection={<IconTrash size={16} />}
                onClick={() => props.onBulk("removeAll")}
              >
                {ua.removeAll}
              </Menu.Item>
            </Menu.Dropdown>
          </Menu>
        )}
      </Group>
      {expanded && (
        <Box mt="xs">
          <SectionRows {...props} />
        </Box>
      )}
    </Paper>
  );
});
