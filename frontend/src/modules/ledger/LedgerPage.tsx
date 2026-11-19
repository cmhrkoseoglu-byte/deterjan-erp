import {
  Alert,
  Badge,
  Button,
  Checkbox,
  Group,
  Pagination,
  Paper,
  Select,
  SimpleGrid,
  Stack,
  Table,
  Tabs,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useDebouncedValue } from "@mantine/hooks";
import { notifications } from "@mantine/notifications";
import { IconFileSpreadsheet, IconInfoCircle, IconSearch } from "@tabler/icons-react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Navigate, useNavigate, useParams } from "react-router-dom";
import { getErrorMessage } from "../../api/client";
import {
  downloadPartners,
  listPartners,
  type Currency,
  type LedgerTotal,
  type PartnerListParams,
} from "../../api/ledger";
import { useCan } from "../../auth/access";
import { formatDate, formatMoney } from "../../i18n/format";
import { ForbiddenPage } from "../../pages/ForbiddenPage";
import {
  LEDGER_BASE,
  PRICES,
  SIDES,
  balanceText,
  partnerLedgerPath,
  sideNotice,
  type SideConfig,
} from "./config";
import { lt } from "./strings";

const PAGE_SIZE = 50;
const CURRENCIES = (["TRY", "EUR", "USD"] as const).map((value) => ({ value, label: value }));

function Totals({ totals, side }: { totals: LedgerTotal[]; side: SideConfig }) {
  if (totals.length === 0) return null;
  const openLabel = side.side === "customers" ? lt.totalOpenCustomers : lt.totalOpenSuppliers;
  return (
    <SimpleGrid cols={{ base: 1, sm: 3 }}>
      {[
        { label: openLabel, key: "open" as const },
        { label: lt.totalOverdue, key: "overdue" as const },
        { label: lt.totalAdvance, key: "advance" as const },
      ].map((item) => (
        <Paper key={item.key} withBorder p="sm">
          <Text size="xs" c="dimmed">
            {item.label}
          </Text>
          {totals.map((total) => (
            <Text
              key={total.currency}
              fw={700}
              c={item.key === "overdue" && Number(total.overdue) > 0 ? "red" : undefined}
            >
              {formatMoney(total[item.key], total.currency)}
            </Text>
          ))}
        </Paper>
      ))}
    </SimpleGrid>
  );
}

/** Bir tarafın cari listesi: bakiye, vadesi geçen ve tutarı eksik belgeler. */
function PartnerList({ side }: { side: SideConfig }) {
  const { can } = useCan();
  const navigate = useNavigate();
  const amounts = can(PRICES);
  const [search, setSearch] = useState("");
  const [withBalance, setWithBalance] = useState(false);
  const [overdue, setOverdue] = useState(false);
  const [inactive, setInactive] = useState(false);
  const [currency, setCurrency] = useState<Currency | null>(null);
  const [page, setPage] = useState(1);
  const [exporting, setExporting] = useState(false);
  const [debounced] = useDebouncedValue(search, 300);
  const filters: PartnerListParams = {
    search: debounced || undefined,
    with_balance: withBalance,
    overdue,
    include_inactive: inactive,
    currency: currency ?? undefined,
  };
  const params = { ...filters, page, page_size: PAGE_SIZE };
  const query = useQuery({
    queryKey: ["ledger", side.side, "list", params],
    queryFn: () => listPartners(side.side, params),
    placeholderData: keepPreviousData,
  });
  const rows = query.data?.results ?? [];
  const pages = Math.max(1, Math.ceil((query.data?.count ?? 0) / PAGE_SIZE));
  const reset = () => setPage(1);

  async function exportExcel() {
    setExporting(true);
    try {
      await downloadPartners(side.side, filters);
    } catch (error) {
      notifications.show({ color: "red", message: getErrorMessage(error) });
    } finally {
      setExporting(false);
    }
  }

  return (
    <Stack>
      <Group justify="space-between" align="flex-end">
        <Group align="flex-end">
          <TextInput
            placeholder={lt.search}
            aria-label={lt.search}
            leftSection={<IconSearch size={16} />}
            value={search}
            onChange={(event) => {
              setSearch(event.currentTarget.value);
              reset();
            }}
          />
          <Select
            placeholder={lt.allCurrencies}
            aria-label={lt.currency}
            clearable
            data={CURRENCIES}
            value={currency}
            onChange={(value) => {
              setCurrency(value as Currency | null);
              reset();
            }}
            w={170}
          />
          <Checkbox
            label={lt.withBalance}
            checked={withBalance}
            onChange={(event) => {
              setWithBalance(event.currentTarget.checked);
              reset();
            }}
          />
          <Checkbox
            label={lt.overdue}
            checked={overdue}
            onChange={(event) => {
              setOverdue(event.currentTarget.checked);
              reset();
            }}
          />
          <Checkbox
            label={lt.includeInactive}
            checked={inactive}
            onChange={(event) => {
              setInactive(event.currentTarget.checked);
              reset();
            }}
          />
        </Group>
        <Button
          variant="default"
          leftSection={<IconFileSpreadsheet size={16} />}
          loading={exporting}
          onClick={() => void exportExcel()}
        >
          {lt.excel}
        </Button>
      </Group>
      {sideNotice(side.side) && (
        <Alert color="blue" variant="light" icon={<IconInfoCircle size={18} />}>
          {sideNotice(side.side)}
        </Alert>
      )}
      {!amounts && (
        <Alert color="gray" variant="light">
          {lt.noAmounts}
        </Alert>
      )}
      {query.data?.totals && <Totals totals={query.data.totals} side={side} />}
      {query.isError && (
        <Alert color="red" variant="light">
          {getErrorMessage(query.error)}
        </Alert>
      )}
      <Table.ScrollContainer minWidth={760}>
        <Table striped highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{lt.code}</Table.Th>
              <Table.Th>{lt.name}</Table.Th>
              <Table.Th>{lt.term}</Table.Th>
              {amounts && <Table.Th ta="right">{lt.balance}</Table.Th>}
              {amounts && <Table.Th ta="right">{lt.overdueAmount}</Table.Th>}
              <Table.Th>{lt.lastEntry}</Table.Th>
              <Table.Th>{lt.missing}</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {rows.map((row) => (
              <Table.Tr
                key={row.partner.id}
                style={{ cursor: "pointer" }}
                onClick={() => navigate(partnerLedgerPath(side.slug, row.partner.id))}
              >
                <Table.Td fw={600}>{row.partner.code}</Table.Td>
                <Table.Td>
                  <Group gap={6}>
                    <Text size="sm">{row.partner.name}</Text>
                    {!row.partner.is_active && (
                      <Badge size="xs" color="gray" variant="light">
                        {lt.inactive}
                      </Badge>
                    )}
                  </Group>
                </Table.Td>
                <Table.Td>{lt.termDays(row.partner.payment_term_days)}</Table.Td>
                {amounts && (
                  <Table.Td ta="right">
                    {row.balances.length === 0 ? (
                      <Text size="sm" c="dimmed">
                        {lt.noEntries}
                      </Text>
                    ) : (
                      row.balances.map((balance) => (
                        <Text key={balance.currency} size="sm">
                          {balanceText(balance.balance, balance.currency)}
                        </Text>
                      ))
                    )}
                  </Table.Td>
                )}
                {amounts && (
                  <Table.Td ta="right">
                    {row.balances
                      .filter((balance) => Number(balance.overdue) > 0)
                      .map((balance) => (
                        <Text key={balance.currency} size="sm" c="red">
                          {formatMoney(balance.overdue, balance.currency)}
                        </Text>
                      ))}
                  </Table.Td>
                )}
                <Table.Td>
                  {formatDate(
                    row.balances.reduce<string | null>(
                      (latest, balance) =>
                        balance.last_date && (!latest || balance.last_date > latest)
                          ? balance.last_date
                          : latest,
                      null,
                    ),
                  )}
                </Table.Td>
                <Table.Td>
                  {row.missing > 0 && (
                    <Badge color="orange" variant="light">
                      {lt.missingCount(row.missing)}
                    </Badge>
                  )}
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
      {!query.isLoading && rows.length === 0 && (
        <Text size="sm" c="dimmed">
          {lt.empty}
        </Text>
      )}
      {pages > 1 && <Pagination value={page} onChange={setPage} total={pages} />}
    </Stack>
  );
}

/** Cari hesaplar: müşteri ve tedarikçi sekmeleri (her biri kendi bölümünün Görür'üyle). */
export function LedgerPage() {
  const { tab } = useParams();
  const { can } = useCan();
  const navigate = useNavigate();
  const visible = SIDES.filter((item) => can(item.section));
  const fallback = visible[0];
  if (!fallback) return <ForbiddenPage />;
  const current = tab ? visible.find((item) => item.slug === tab) : fallback;
  if (!current) return <Navigate to={LEDGER_BASE} replace />;

  return (
    <Stack>
      <Title order={2}>{lt.title}</Title>
      <Tabs value={current.slug} onChange={(value) => value && navigate(`${LEDGER_BASE}/${value}`)}>
        <Tabs.List>
          {visible.map((item) => (
            <Tabs.Tab key={item.slug} value={item.slug}>
              {item.label}
            </Tabs.Tab>
          ))}
        </Tabs.List>
      </Tabs>
      <PartnerList key={current.slug} side={current} />
    </Stack>
  );
}
