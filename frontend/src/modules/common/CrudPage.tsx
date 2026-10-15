import {
  ActionIcon,
  Alert,
  Button,
  Group,
  Menu,
  Pagination,
  SegmentedControl,
  Stack,
  Table,
  Text,
  TextInput,
} from "@mantine/core";
import { useDebouncedValue } from "@mantine/hooks";
import { notifications } from "@mantine/notifications";
import { IconDots, IconFileSpreadsheet, IconPlus, IconSearch } from "@tabler/icons-react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { getErrorMessage } from "../../api/client";
import {
  listRecords,
  saveRecord,
  setRecordActive,
  type ImportKind,
  type MasterDataEndpoint,
} from "../../api/masterdata";
import type { Role } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { hasAnyRole } from "../../auth/roles";
import { ActiveBadge } from "./ActiveBadge";
import { ConfirmModal } from "./ConfirmModal";
import type { FieldDef, FormValues } from "./forms";
import { ImportModal } from "./ImportModal";
import { RecordFormModal } from "./RecordFormModal";
import { ct } from "./strings";

export interface Column<T> {
  key: string;
  label: string;
  render?: (row: T) => ReactNode;
}

export interface EntityConfig<T> {
  endpoint: MasterDataEndpoint;
  /** Çoğul başlık (ör. "Malzemeler"). */
  title: string;
  /** Tekil ad, form başlığında (ör. "Malzeme"). */
  singular: string;
  columns: Column<T>[];
  fields: FieldDef[];
  defaults?: FormValues;
  writeRoles: Role[];
  importKind?: ImportKind;
  /** Liste için ek filtre seçicileri. */
  filters?: (
    values: Record<string, string>,
    set: (name: string, value: string) => void,
  ) => ReactNode;
}

const PAGE_SIZE = 50;

interface Row {
  id: number;
  is_active: boolean;
  code?: string;
  name?: string;
}

function recordName(row: Row): string {
  return [row.code, row.name].filter(Boolean).join(" - ");
}

/** Ana veri listesi: arama, aktif/pasif filtresi, sayfalama, form ve içe aktarma. */
export function CrudPage<T extends Row>({ config }: { config: EntityConfig<T> }) {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const canWrite = hasAnyRole(user, config.writeRoles);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [debouncedSearch] = useDebouncedValue(search, 300);
  const [activeFilter, setActiveFilter] = useState("true");
  const [extra, setExtra] = useState<Record<string, string>>({});
  const [editing, setEditing] = useState<T | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [confirming, setConfirming] = useState<T | null>(null);

  const params = {
    page,
    page_size: PAGE_SIZE,
    search: debouncedSearch,
    is_active: activeFilter,
    ...extra,
  };
  const list = useQuery({
    queryKey: ["masterdata", config.endpoint, params],
    queryFn: () => listRecords<T>(config.endpoint, params),
    placeholderData: keepPreviousData,
  });

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["masterdata", config.endpoint] });
    void queryClient.invalidateQueries({ queryKey: ["options", config.endpoint] });
  };

  const toggleActive = useMutation({
    mutationFn: (row: T) => setRecordActive<T>(config.endpoint, row.id, !row.is_active),
    onSuccess: refresh,
    onError: (error) => notifications.show({ color: "red", message: getErrorMessage(error) }),
    onSettled: () => setConfirming(null),
  });

  function confirmToggle(row: T) {
    if (row.is_active) setConfirming(row);
    else toggleActive.mutate(row);
  }

  function openForm(row: T | null) {
    setEditing(row);
    setFormOpen(true);
  }

  const rows = list.data?.results ?? [];
  const pages = Math.max(1, Math.ceil((list.data?.count ?? 0) / PAGE_SIZE));

  return (
    <Stack>
      <Group justify="space-between" wrap="wrap">
        <Group wrap="wrap">
          <TextInput
            aria-label={ct.search}
            placeholder={ct.search}
            leftSection={<IconSearch size={16} />}
            value={search}
            onChange={(event) => {
              setSearch(event.currentTarget.value);
              setPage(1);
            }}
          />
          <SegmentedControl
            aria-label={ct.statusFilter}
            value={activeFilter}
            onChange={(value) => {
              setActiveFilter(value);
              setPage(1);
            }}
            data={[
              { value: "true", label: ct.active },
              { value: "false", label: ct.inactive },
              { value: "", label: ct.all },
            ]}
          />
          {config.filters?.(extra, (name, value) => {
            setExtra((current) => ({ ...current, [name]: value }));
            setPage(1);
          })}
        </Group>
        {canWrite && (
          <Group>
            {config.importKind && (
              <Button
                variant="default"
                leftSection={<IconFileSpreadsheet size={16} />}
                onClick={() => setImportOpen(true)}
              >
                {ct.importButton}
              </Button>
            )}
            <Button leftSection={<IconPlus size={16} />} onClick={() => openForm(null)}>
              {ct.new}
            </Button>
          </Group>
        )}
      </Group>

      {list.isError && (
        <Alert color="red" variant="light">
          {getErrorMessage(list.error)}
        </Alert>
      )}

      <Table.ScrollContainer minWidth={640}>
        <Table striped highlightOnHover verticalSpacing="xs">
          <Table.Thead>
            <Table.Tr>
              {config.columns.map((column) => (
                <Table.Th key={column.key}>{column.label}</Table.Th>
              ))}
              <Table.Th>{ct.statusFilter}</Table.Th>
              <Table.Th w={60} aria-label={ct.actions} />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {rows.map((row) => (
              <Table.Tr key={row.id} style={{ cursor: "pointer" }} onClick={() => openForm(row)}>
                {config.columns.map((column) => (
                  <Table.Td key={column.key}>
                    {column.render
                      ? column.render(row)
                      : String((row as Record<string, unknown>)[column.key] ?? "")}
                  </Table.Td>
                ))}
                <Table.Td>
                  <ActiveBadge active={row.is_active} />
                </Table.Td>
                <Table.Td onClick={(event) => event.stopPropagation()}>
                  {canWrite && (
                    <Menu position="bottom-end" withinPortal>
                      <Menu.Target>
                        <ActionIcon
                          variant="subtle"
                          aria-label={`${ct.actions}: ${recordName(row)}`}
                        >
                          <IconDots size={16} />
                        </ActionIcon>
                      </Menu.Target>
                      <Menu.Dropdown>
                        <Menu.Item onClick={() => openForm(row)}>{ct.edit}</Menu.Item>
                        <Menu.Item
                          color={row.is_active ? "red" : undefined}
                          onClick={() => confirmToggle(row)}
                        >
                          {row.is_active ? ct.deactivate : ct.activate}
                        </Menu.Item>
                      </Menu.Dropdown>
                    </Menu>
                  )}
                </Table.Td>
              </Table.Tr>
            ))}
            {!list.isLoading && rows.length === 0 && (
              <Table.Tr>
                <Table.Td colSpan={config.columns.length + 2}>
                  <Text c="dimmed" ta="center" py="md">
                    {ct.empty}
                  </Text>
                </Table.Td>
              </Table.Tr>
            )}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>

      <Group justify="space-between">
        <Text size="sm" c="dimmed">
          {ct.totalCount(list.data?.count ?? 0)}
        </Text>
        {pages > 1 && <Pagination value={page} onChange={setPage} total={pages} />}
      </Group>

      <RecordFormModal<T>
        opened={formOpen}
        title={
          editing
            ? `${config.singular}: ${recordName(editing)}`
            : `${ct.new} ${config.singular.toLocaleLowerCase("tr")}`
        }
        fields={config.fields}
        record={editing}
        defaults={config.defaults}
        readOnly={!canWrite}
        onClose={() => setFormOpen(false)}
        onSubmit={(payload) => saveRecord<T>(config.endpoint, editing?.id ?? null, payload)}
        onSaved={() => {
          setFormOpen(false);
          refresh();
        }}
      />
      <ConfirmModal
        opened={confirming !== null}
        message={confirming ? ct.confirmDeactivate(recordName(confirming)) : ""}
        confirmLabel={ct.deactivate}
        danger
        loading={toggleActive.isPending}
        onConfirm={() => confirming && toggleActive.mutate(confirming)}
        onClose={() => setConfirming(null)}
      />
      {config.importKind && (
        <ImportModal
          kind={config.importKind}
          title={config.title}
          opened={importOpen}
          onClose={() => setImportOpen(false)}
          onImported={refresh}
        />
      )}
    </Stack>
  );
}
