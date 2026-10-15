import {
  Alert,
  Button,
  Checkbox,
  Group,
  Pagination,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
} from "@mantine/core";
import { useDebouncedValue } from "@mantine/hooks";
import { IconFileSpreadsheet, IconPlus, IconSearch } from "@tabler/icons-react";
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { getErrorMessage } from "../../api/client";
import {
  listAdjustments,
  listBalances,
  listGoodsReceipts,
  listLots,
  OPENING_TEMPLATE_URL,
  uploadOpening,
  type Lot,
} from "../../api/inventory";
import type { ListParams } from "../../api/masterdata";
import type { Paginated } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { hasAnyRole } from "../../auth/roles";
import { formatDate } from "../../i18n/format";
import { ImportModal } from "../common/ImportModal";
import { ct } from "../common/strings";
import { adjustmentPath, lotPath, receiptPath, STOCK_WRITE_ROLES } from "./config";
import { LotDecisionModal, type LotDecision } from "./LotDecisionModal";
import { DocStatusBadge, ExpiryText, LotStatusBadge, Qty } from "./shared";
import { it } from "./strings";

const PAGE_SIZE = 50;

const LOT_STATUS_OPTIONS = (["QUARANTINE", "RELEASED", "BLOCKED", "REJECTED"] as const).map(
  (value) => ({ value, label: it.lotStatus[value] }),
);
const DOC_STATUS_OPTIONS = (["DRAFT", "POSTED", "CANCELLED"] as const).map((value) => ({
  value,
  label: it.docStatus[value],
}));

interface Column<T> {
  header: string;
  render: (row: T) => ReactNode;
  align?: "right";
}

/** Sayfalı, aranabilir liste: filtreler + tablo + sayfalama. */
function usePagedList<T>(
  key: string,
  fetcher: (params: ListParams) => Promise<Paginated<T>>,
  filters: ListParams,
  search: string,
) {
  const [page, setPage] = useState(1);
  const [debounced] = useDebouncedValue(search, 300);
  const params = { page, page_size: PAGE_SIZE, search: debounced || undefined, ...filters };
  const query = useQuery({
    queryKey: ["inventory", key, params],
    queryFn: () => fetcher(params),
    placeholderData: keepPreviousData,
  });
  const pages = Math.max(1, Math.ceil((query.data?.count ?? 0) / PAGE_SIZE));
  return { query, page, setPage, pages };
}

function ListTable<T extends { id: number }>({
  columns,
  rows,
  loading,
  error,
  onOpen,
  minWidth = 720,
}: {
  columns: Column<T>[];
  rows: T[];
  loading: boolean;
  error: unknown;
  onOpen?: (row: T) => void;
  minWidth?: number;
}) {
  return (
    <>
      {Boolean(error) && (
        <Alert color="red" variant="light">
          {getErrorMessage(error)}
        </Alert>
      )}
      <Table.ScrollContainer minWidth={minWidth}>
        <Table striped highlightOnHover={Boolean(onOpen)}>
          <Table.Thead>
            <Table.Tr>
              {columns.map((column) => (
                <Table.Th key={column.header} ta={column.align}>
                  {column.header}
                </Table.Th>
              ))}
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {rows.map((row) => (
              <Table.Tr
                key={row.id}
                style={onOpen ? { cursor: "pointer" } : undefined}
                onClick={onOpen ? () => onOpen(row) : undefined}
              >
                {columns.map((column) => (
                  <Table.Td key={column.header} ta={column.align}>
                    {column.render(row)}
                  </Table.Td>
                ))}
              </Table.Tr>
            ))}
            {!loading && rows.length === 0 && (
              <Table.Tr>
                <Table.Td colSpan={columns.length}>
                  <Text c="dimmed" ta="center" py="md">
                    {ct.empty}
                  </Text>
                </Table.Td>
              </Table.Tr>
            )}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
    </>
  );
}

function SearchBox({
  value,
  placeholder,
  onChange,
}: {
  value: string;
  placeholder: string;
  onChange: (value: string) => void;
}) {
  return (
    <TextInput
      aria-label={placeholder}
      placeholder={placeholder}
      leftSection={<IconSearch size={16} />}
      value={value}
      w={320}
      onChange={(event) => onChange(event.currentTarget.value)}
    />
  );
}

// --- stok sorgu ----------------------------------------------------------------------------

export function StockTab() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  const list = usePagedList("balances", listBalances, { lot_status: status ?? undefined }, search);
  const rows = list.query.data?.results ?? [];

  return (
    <Stack>
      <Group justify="space-between">
        <Group>
          <SearchBox
            value={search}
            placeholder={it.searchStock}
            onChange={(value) => {
              setSearch(value);
              list.setPage(1);
            }}
          />
          <Select
            aria-label={it.status}
            placeholder={it.allStatuses}
            data={LOT_STATUS_OPTIONS}
            value={status}
            onChange={(value) => {
              setStatus(value);
              list.setPage(1);
            }}
            clearable
            w={180}
          />
        </Group>
        {hasAnyRole(user, STOCK_WRITE_ROLES) && (
          <Button
            variant="default"
            leftSection={<IconFileSpreadsheet size={16} />}
            onClick={() => setImportOpen(true)}
          >
            {it.openingImport}
          </Button>
        )}
      </Group>
      <ListTable
        rows={rows}
        loading={list.query.isLoading}
        error={list.query.error}
        onOpen={(row) => navigate(lotPath(row.lot))}
        columns={[
          { header: it.material, render: (r) => `${r.material_code} - ${r.material_name}` },
          { header: it.lotNo, render: (r) => r.lot_no },
          { header: it.status, render: (r) => <LotStatusBadge status={r.lot_status} /> },
          { header: it.expiry, render: (r) => <ExpiryText date={r.expiry_date} /> },
          { header: it.location, render: (r) => r.location_code },
          {
            header: it.quantity,
            align: "right",
            render: (r) => <Qty value={r.quantity} unit={r.unit} />,
          },
        ]}
      />
      {list.pages > 1 && (
        <Pagination value={list.page} onChange={list.setPage} total={list.pages} />
      )}
      <ImportModal
        title={it.openingTitle}
        opened={importOpen}
        intro={it.openingIntro}
        templateUrl={OPENING_TEMPLATE_URL}
        upload={uploadOpening}
        onClose={() => setImportOpen(false)}
        onImported={() => void queryClient.invalidateQueries({ queryKey: ["inventory"] })}
      />
    </Stack>
  );
}

// --- lotlar --------------------------------------------------------------------------------

function lotColumns(): Column<Lot>[] {
  return [
    { header: it.lotNo, render: (r) => r.lot_no },
    { header: it.material, render: (r) => `${r.material_code} - ${r.material_name}` },
    { header: it.status, render: (r) => <LotStatusBadge status={r.status} /> },
    { header: it.source, render: (r) => r.source_display },
    {
      header: it.expiry,
      render: (r) => <ExpiryText date={r.expiry_date} expired={r.is_expired} />,
    },
    {
      header: it.total,
      align: "right",
      render: (r) => <Qty value={r.total_quantity} unit={r.unit} />,
    },
  ];
}

export function LotsTab() {
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [withStock, setWithStock] = useState(true);
  const list = usePagedList(
    "lots",
    listLots,
    { status: status ?? undefined, has_stock: withStock ? true : undefined },
    search,
  );

  return (
    <Stack>
      <Group>
        <SearchBox
          value={search}
          placeholder={it.searchLots}
          onChange={(value) => {
            setSearch(value);
            list.setPage(1);
          }}
        />
        <Select
          aria-label={it.status}
          placeholder={it.allStatuses}
          data={LOT_STATUS_OPTIONS}
          value={status}
          onChange={(value) => {
            setStatus(value);
            list.setPage(1);
          }}
          clearable
          w={180}
        />
        <Checkbox
          label={it.onlyWithStock}
          checked={withStock}
          onChange={(event) => {
            setWithStock(event.currentTarget.checked);
            list.setPage(1);
          }}
        />
      </Group>
      <ListTable
        rows={list.query.data?.results ?? []}
        loading={list.query.isLoading}
        error={list.query.error}
        onOpen={(row) => navigate(lotPath(row.id))}
        columns={lotColumns()}
      />
      {list.pages > 1 && (
        <Pagination value={list.page} onChange={list.setPage} total={list.pages} />
      )}
    </Stack>
  );
}

// --- lot onay (laboratuvar) ----------------------------------------------------------------

export function ApprovalTab() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [target, setTarget] = useState<{ lot: Lot; decision: LotDecision } | null>(null);
  const list = usePagedList("approval", listLots, { status: "QUARANTINE" }, search);
  const rows = list.query.data?.results ?? [];

  const columns: Column<Lot>[] = [
    ...lotColumns().filter((column) => column.header !== it.status),
    {
      header: ct.actions,
      render: (row) => (
        <Group gap={4} wrap="nowrap" onClick={(event) => event.stopPropagation()}>
          <Button
            size="compact-sm"
            color="green"
            onClick={() => setTarget({ lot: row, decision: "release" })}
          >
            {it.release}
          </Button>
          <Button
            size="compact-sm"
            color="red"
            variant="light"
            onClick={() => setTarget({ lot: row, decision: "reject" })}
          >
            {it.reject}
          </Button>
        </Group>
      ),
    },
  ];

  return (
    <Stack>
      <Text size="sm" c="dimmed">
        {it.approvalIntro}
      </Text>
      <SearchBox
        value={search}
        placeholder={it.searchLots}
        onChange={(value) => {
          setSearch(value);
          list.setPage(1);
        }}
      />
      <ListTable
        rows={rows}
        loading={list.query.isLoading}
        error={list.query.error}
        onOpen={(row) => navigate(lotPath(row.id))}
        columns={columns}
      />
      {list.pages > 1 && (
        <Pagination value={list.page} onChange={list.setPage} total={list.pages} />
      )}
      <LotDecisionModal
        lot={target?.lot ?? null}
        decision={target?.decision ?? null}
        onClose={() => setTarget(null)}
        onDone={() => {
          setTarget(null);
          void queryClient.invalidateQueries({ queryKey: ["inventory"] });
        }}
      />
    </Stack>
  );
}

// --- mal kabul ve sayım düzeltme listeleri -------------------------------------------------

export function ReceiptsTab() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const list = usePagedList("receipts", listGoodsReceipts, { status: status ?? undefined }, search);

  return (
    <Stack>
      <Group justify="space-between">
        <Group>
          <SearchBox
            value={search}
            placeholder={it.searchDocs}
            onChange={(value) => {
              setSearch(value);
              list.setPage(1);
            }}
          />
          <Select
            aria-label={it.status}
            placeholder={it.allStatuses}
            data={DOC_STATUS_OPTIONS}
            value={status}
            onChange={(value) => {
              setStatus(value);
              list.setPage(1);
            }}
            clearable
            w={180}
          />
        </Group>
        {hasAnyRole(user, STOCK_WRITE_ROLES) && (
          <Button
            leftSection={<IconPlus size={16} />}
            onClick={() => navigate(receiptPath("yeni"))}
          >
            {it.newReceipt}
          </Button>
        )}
      </Group>
      <ListTable
        rows={list.query.data?.results ?? []}
        loading={list.query.isLoading}
        error={list.query.error}
        onOpen={(row) => navigate(receiptPath(row.id))}
        columns={[
          { header: it.number, render: (r) => r.number },
          { header: it.date, render: (r) => formatDate(r.receipt_date) },
          { header: it.supplier, render: (r) => r.supplier_name },
          { header: it.deliveryNote, render: (r) => r.delivery_note_no },
          { header: it.lineCount, align: "right", render: (r) => r.line_count },
          { header: it.status, render: (r) => <DocStatusBadge status={r.status} /> },
        ]}
      />
      {list.pages > 1 && (
        <Pagination value={list.page} onChange={list.setPage} total={list.pages} />
      )}
    </Stack>
  );
}

export function AdjustmentsTab() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const list = usePagedList("adjustments", listAdjustments, {}, search);

  return (
    <Stack>
      <Group justify="space-between">
        <SearchBox
          value={search}
          placeholder={it.searchDocs}
          onChange={(value) => {
            setSearch(value);
            list.setPage(1);
          }}
        />
        {hasAnyRole(user, STOCK_WRITE_ROLES) && (
          <Button
            leftSection={<IconPlus size={16} />}
            onClick={() => navigate(adjustmentPath("yeni"))}
          >
            {it.newAdjustment}
          </Button>
        )}
      </Group>
      <ListTable
        rows={list.query.data?.results ?? []}
        loading={list.query.isLoading}
        error={list.query.error}
        onOpen={(row) => navigate(adjustmentPath(row.id))}
        minWidth={560}
        columns={[
          { header: it.number, render: (r) => r.number },
          { header: it.adjustmentDate, render: (r) => formatDate(r.adjustment_date) },
          { header: it.note, render: (r) => r.note },
          { header: it.lineCount, align: "right", render: (r) => r.line_count },
          { header: it.status, render: (r) => <DocStatusBadge status={r.status} /> },
        ]}
      />
      {list.pages > 1 && (
        <Pagination value={list.page} onChange={list.setPage} total={list.pages} />
      )}
    </Stack>
  );
}
