import {
  Alert,
  Anchor,
  Badge,
  Button,
  Group,
  Modal,
  Paper,
  Select,
  SimpleGrid,
  Stack,
  Table,
  Text,
  TextInput,
  Textarea,
  Title,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconArrowLeft, IconFileSpreadsheet, IconFileTypePdf, IconPlus } from "@tabler/icons-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, Navigate, useParams } from "react-router-dom";
import { getErrorMessage } from "../../api/client";
import {
  downloadStatement,
  getPartnerSummary,
  getReturnSuggestion,
  getStatement,
  listMissingPrices,
  postEntry,
  reverseEntry,
  setShipmentLinePrice,
  type Currency,
  type EntryKind,
  type LedgerBalance,
  type LedgerEntry,
  type MissingPrice,
  type PaymentMethod,
  type ReturnInfo,
} from "../../api/ledger";
import { useCan } from "../../auth/access";
import { formatDate, formatMoney, formatNumber } from "../../i18n/format";
import { normalizeDecimal } from "../common/forms";
import { today } from "../inventory/config";
import { receiptPath } from "../inventory/config";
import { returnPath } from "../returns/config";
import { shipmentPath } from "../sales/config";
import { LEDGER_BASE, PRICES, balanceText, sideBySlug, type SideConfig } from "./config";
import { lt } from "./strings";

const CURRENCIES = (["TRY", "EUR", "USD"] as const).map((value) => ({ value, label: value }));
const METHODS = (Object.keys(lt.method_) as PaymentMethod[]).map((value) => ({
  value,
  label: lt.method_[value],
}));
const KINDS: Record<SideConfig["side"], EntryKind[]> = {
  customers: ["COLLECTION", "RETURN_CREDIT", "DEBIT_NOTE", "CREDIT_NOTE", "OPENING"],
  suppliers: ["PAYMENT", "DEBIT_NOTE", "CREDIT_NOTE", "OPENING"],
};
const AUTO_KINDS: EntryKind[] = ["SALE", "PURCHASE", "REVERSAL"];
const BUCKETS = Object.keys(lt.aging_) as (keyof typeof lt.aging_)[];

// --- kayıt girişi ---

interface EntryDraft {
  kind: EntryKind;
  entry_date: string;
  currency: Currency;
  amount: string;
  direction: "debit" | "credit" | null;
  method: PaymentMethod | null;
  reference: string;
  description: string;
  exchange_rate: string;
  customer_return: string | null;
}

function EntryModal({
  side,
  partnerId,
  initialKind,
  returns,
  onClose,
}: {
  side: SideConfig;
  partnerId: number;
  initialKind: EntryKind;
  returns: ReturnInfo[];
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<EntryDraft>({
    kind: initialKind,
    entry_date: today(),
    currency: "TRY",
    amount: "",
    direction: null,
    method: initialKind === "COLLECTION" || initialKind === "PAYMENT" ? "TRANSFER" : null,
    reference: "",
    description: "",
    exchange_rate: "",
    customer_return: null,
  });
  const [suggestion, setSuggestion] = useState("");
  const [error, setError] = useState("");
  const set = (patch: Partial<EntryDraft>) => setDraft((current) => ({ ...current, ...patch }));
  const isPayment = draft.kind === "COLLECTION" || draft.kind === "PAYMENT";
  const mutation = useMutation({
    mutationFn: () =>
      postEntry(side.side, partnerId, {
        kind: draft.kind,
        entry_date: draft.entry_date,
        currency: draft.currency,
        amount: normalizeDecimal(draft.amount),
        direction: draft.kind === "OPENING" ? draft.direction : null,
        method: isPayment ? (draft.method ?? "") : "",
        reference: draft.reference,
        description: draft.description,
        exchange_rate:
          draft.currency !== "TRY" && draft.exchange_rate
            ? normalizeDecimal(draft.exchange_rate)
            : null,
        customer_return:
          draft.kind === "RETURN_CREDIT" && draft.customer_return
            ? Number(draft.customer_return)
            : null,
      }),
    onSuccess: (entry) => {
      notifications.show({ color: "green", message: `${lt.saved}: ${entry.number}` });
      void queryClient.invalidateQueries({ queryKey: ["ledger"] });
      onClose();
    },
    onError: (err) => setError(getErrorMessage(err)),
  });

  async function chooseReturn(value: string | null) {
    set({ customer_return: value });
    setSuggestion("");
    if (!value) return;
    try {
      const amounts = await getReturnSuggestion(partnerId, Number(value));
      const first = amounts[0];
      if (first) {
        set({ customer_return: value, amount: first.amount, currency: first.currency });
        setSuggestion(amounts.map((item) => formatMoney(item.amount, item.currency)).join(", "));
      }
    } catch {
      // Öneri yoksa tutar elle girilir.
    }
  }

  return (
    <Modal opened onClose={onClose} title={lt.entryTitle}>
      <Stack>
        <Select
          label={lt.kind}
          data={KINDS[side.side].map((value) => ({ value, label: lt.kind_[value] }))}
          value={draft.kind}
          allowDeselect={false}
          onChange={(value) =>
            value &&
            set({
              kind: value as EntryKind,
              method: value === "COLLECTION" || value === "PAYMENT" ? "TRANSFER" : null,
            })
          }
        />
        {draft.kind === "RETURN_CREDIT" && (
          <Select
            label={lt.customerReturn}
            required
            data={returns
              .filter((item) => !item.has_credit)
              .map((item) => ({
                value: String(item.id),
                label: `${item.number} · ${formatDate(item.return_date)}`,
              }))}
            value={draft.customer_return}
            onChange={(value) => void chooseReturn(value)}
          />
        )}
        {suggestion && (
          <Text size="sm" c="dimmed">
            {lt.suggestion(suggestion)}
          </Text>
        )}
        <Group grow>
          <TextInput
            label={lt.date}
            type="date"
            required
            value={draft.entry_date}
            max={today()}
            onChange={(event) => set({ entry_date: event.currentTarget.value })}
          />
          <Select
            label={lt.currency}
            data={CURRENCIES}
            value={draft.currency}
            allowDeselect={false}
            onChange={(value) => value && set({ currency: value as Currency })}
          />
        </Group>
        <TextInput
          label={lt.amount}
          required
          inputMode="decimal"
          value={draft.amount}
          onChange={(event) => set({ amount: event.currentTarget.value })}
        />
        {draft.kind === "OPENING" && (
          <Select
            label={lt.direction}
            required
            data={[
              { value: "debit", label: lt.debitSide },
              { value: "credit", label: lt.creditSide },
            ]}
            value={draft.direction}
            onChange={(value) => set({ direction: value as EntryDraft["direction"] })}
          />
        )}
        {isPayment && (
          <Select
            label={lt.method}
            required
            data={METHODS}
            value={draft.method}
            allowDeselect={false}
            onChange={(value) => set({ method: value as PaymentMethod | null })}
          />
        )}
        {draft.currency !== "TRY" && (
          <TextInput
            label={lt.exchangeRate}
            inputMode="decimal"
            value={draft.exchange_rate}
            onChange={(event) => set({ exchange_rate: event.currentTarget.value })}
          />
        )}
        <TextInput
          label={lt.reference}
          value={draft.reference}
          maxLength={64}
          onChange={(event) => set({ reference: event.currentTarget.value })}
        />
        <Textarea
          label={lt.description}
          required={draft.kind === "DEBIT_NOTE" || draft.kind === "CREDIT_NOTE"}
          value={draft.description}
          maxLength={255}
          onChange={(event) => set({ description: event.currentTarget.value })}
        />
        {error && (
          <Alert color="red" variant="light">
            {error}
          </Alert>
        )}
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            {lt.close}
          </Button>
          <Button loading={mutation.isPending} onClick={() => mutation.mutate()}>
            {lt.save}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

function ReverseModal({
  side,
  partnerId,
  entry,
  onClose,
}: {
  side: SideConfig;
  partnerId: number;
  entry: LedgerEntry;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const mutation = useMutation({
    mutationFn: () => reverseEntry(side.side, partnerId, entry.id, reason),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["ledger"] });
      onClose();
    },
    onError: (err) => setError(getErrorMessage(err)),
  });
  return (
    <Modal opened onClose={onClose} title={lt.cancelTitle(entry.number)}>
      <Stack>
        <Text size="sm">{lt.cancelHelp}</Text>
        <Textarea
          label={lt.reason}
          required
          value={reason}
          onChange={(event) => setReason(event.currentTarget.value)}
        />
        {error && (
          <Alert color="red" variant="light">
            {error}
          </Alert>
        )}
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            {lt.close}
          </Button>
          <Button
            color="red"
            loading={mutation.isPending}
            disabled={!reason.trim()}
            onClick={() => mutation.mutate()}
          >
            {lt.confirm}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

function PriceModal({ line, onClose }: { line: MissingPrice; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [price, setPrice] = useState("");
  const [currency, setCurrency] = useState<Currency>("TRY");
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const mutation = useMutation({
    mutationFn: () =>
      setShipmentLinePrice({
        line: line.line_id,
        unit_price: normalizeDecimal(price),
        currency,
        note,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["ledger"] });
      onClose();
    },
    onError: (err) => setError(getErrorMessage(err)),
  });
  return (
    <Modal opened onClose={onClose} title={lt.priceTitle(line.document_number)}>
      <Stack>
        <Text size="sm">
          {line.material_code} — {line.material_name}: {formatNumber(line.quantity)}{" "}
          {line.unit_code}
        </Text>
        <Group grow>
          <TextInput
            label={lt.unitPrice}
            required
            inputMode="decimal"
            value={price}
            onChange={(event) => setPrice(event.currentTarget.value)}
          />
          <Select
            label={lt.currency}
            data={CURRENCIES}
            value={currency}
            allowDeselect={false}
            onChange={(value) => value && setCurrency(value as Currency)}
          />
        </Group>
        <TextInput
          label={lt.note}
          value={note}
          maxLength={200}
          onChange={(event) => setNote(event.currentTarget.value)}
        />
        {error && (
          <Alert color="red" variant="light">
            {error}
          </Alert>
        )}
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            {lt.close}
          </Button>
          <Button loading={mutation.isPending} onClick={() => mutation.mutate()}>
            {lt.save}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

// --- sayfa ---

function BalanceCard({ balance }: { balance: LedgerBalance }) {
  return (
    <Paper withBorder p="sm">
      <Text size="xs" c="dimmed">
        {lt.balance} ({balance.currency})
      </Text>
      <Text fw={700} size="lg">
        {balanceText(balance.balance, balance.currency)}
      </Text>
      {balance.aging && (
        <Table mt="xs" withRowBorders={false} verticalSpacing={2} fz="xs">
          <Table.Tbody>
            {BUCKETS.map((bucket) => (
              <Table.Tr key={bucket}>
                <Table.Td>{lt.aging_[bucket]}</Table.Td>
                <Table.Td
                  ta="right"
                  c={
                    bucket !== "not_due" && Number(balance.aging?.[bucket]) > 0 ? "red" : undefined
                  }
                >
                  {formatMoney(balance.aging?.[bucket])}
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}
    </Paper>
  );
}

function documentLink(entry: LedgerEntry) {
  if (entry.shipment && entry.shipment_number) {
    return (
      <Anchor component={Link} to={shipmentPath(entry.shipment)} size="sm">
        {entry.shipment_number}
      </Anchor>
    );
  }
  if (entry.goods_receipt && entry.goods_receipt_number) {
    return (
      <Anchor component={Link} to={receiptPath(entry.goods_receipt)} size="sm">
        {entry.goods_receipt_number}
      </Anchor>
    );
  }
  if (entry.customer_return && entry.customer_return_number) {
    return (
      <Anchor component={Link} to={returnPath(entry.customer_return)} size="sm">
        {entry.customer_return_number}
      </Anchor>
    );
  }
  return entry.reversal_of_number ?? entry.reference;
}

/** Bir carinin özeti, yaşlandırması, ekstresi ve elle kayıtları. */
export function PartnerLedgerPage() {
  const { tab, partnerId } = useParams();
  const side = sideBySlug(tab);
  const id = Number(partnerId);
  const { can } = useCan();
  const amounts = can(PRICES);
  const writable = side !== undefined && can(side.section, "change") && amounts;
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [entryKind, setEntryKind] = useState<EntryKind | null>(null);
  const [reversing, setReversing] = useState<LedgerEntry | null>(null);
  const [pricing, setPricing] = useState<MissingPrice | null>(null);
  const [downloading, setDownloading] = useState<"xlsx" | "pdf" | null>(null);
  const valid = side !== undefined && Number.isInteger(id) && id > 0;
  const dates = { date_from: dateFrom || undefined, date_to: dateTo || undefined };
  const summary = useQuery({
    queryKey: ["ledger", side?.side, "summary", id],
    queryFn: () => getPartnerSummary(side!.side, id),
    enabled: valid,
  });
  const statement = useQuery({
    queryKey: ["ledger", side?.side, "statement", id, dates],
    queryFn: () => getStatement(side!.side, id, dates),
    enabled: valid,
  });
  const missing = useQuery({
    queryKey: ["ledger", side?.side, "missing", id],
    queryFn: () => listMissingPrices(side!.side, id),
    enabled: valid,
  });
  if (!side) return <Navigate to={LEDGER_BASE} replace />;
  if (!valid) return <Navigate to={`${LEDGER_BASE}/${side.slug}`} replace />;
  const partner = summary.data?.partner;
  const returns = statement.data?.returns ?? [];

  async function download(format: "xlsx" | "pdf") {
    setDownloading(format);
    try {
      await downloadStatement(side!.side, id, format, dates);
    } catch (error) {
      notifications.show({ color: "red", message: getErrorMessage(error) });
    } finally {
      setDownloading(null);
    }
  }

  return (
    <Stack>
      <Anchor component={Link} to={`${LEDGER_BASE}/${side.slug}`} size="sm">
        <Group gap={4}>
          <IconArrowLeft size={14} />
          {lt.back}
        </Group>
      </Anchor>
      {(summary.isError || statement.isError) && (
        <Alert color="red" variant="light">
          {getErrorMessage(summary.error ?? statement.error)}
        </Alert>
      )}
      {partner && (
        <Group justify="space-between" align="flex-start">
          <Stack gap={2}>
            <Title order={2}>
              {partner.code} — {partner.name}
            </Title>
            <Group gap="xs">
              <Text size="sm" c="dimmed">
                {lt.term}: {lt.termDays(partner.payment_term_days)}
              </Text>
              {partner.vat_exempt && (
                <Badge variant="light" color="grape">
                  {lt.vatExempt}
                </Badge>
              )}
              {!partner.is_active && (
                <Badge variant="light" color="gray">
                  {lt.inactive}
                </Badge>
              )}
            </Group>
          </Stack>
          {writable && (
            <Group>
              <Button
                leftSection={<IconPlus size={16} />}
                onClick={() => setEntryKind(side.side === "customers" ? "COLLECTION" : "PAYMENT")}
              >
                {side.side === "customers" ? lt.newCollection : lt.newPayment}
              </Button>
              <Button variant="default" onClick={() => setEntryKind("DEBIT_NOTE")}>
                {lt.newEntry}
              </Button>
            </Group>
          )}
        </Group>
      )}
      {!amounts && (
        <Alert color="gray" variant="light">
          {lt.noAmounts}
        </Alert>
      )}
      {amounts && summary.data && summary.data.balances.length > 0 && (
        <SimpleGrid cols={{ base: 1, sm: 2, md: 3 }}>
          {summary.data.balances.map((balance) => (
            <BalanceCard key={balance.currency} balance={balance} />
          ))}
        </SimpleGrid>
      )}
      {(missing.data ?? []).length > 0 && (
        <Paper withBorder p="sm">
          <Stack gap="xs">
            <Text fw={600}>{lt.missingTitle}</Text>
            <Text size="sm" c="dimmed">
              {side.side === "customers" ? lt.missingHelpCustomer : lt.missingHelpSupplier}
            </Text>
            <Table>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>{lt.document}</Table.Th>
                  <Table.Th>{lt.date}</Table.Th>
                  <Table.Th>{lt.material}</Table.Th>
                  <Table.Th ta="right">{lt.quantity}</Table.Th>
                  <Table.Th />
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {(missing.data ?? []).map((line) => (
                  <Table.Tr key={`${line.kind}-${line.line_id}`}>
                    <Table.Td>
                      <Anchor
                        component={Link}
                        to={
                          line.kind === "shipment"
                            ? shipmentPath(line.document_id)
                            : receiptPath(line.document_id)
                        }
                        size="sm"
                      >
                        {line.document_number}
                      </Anchor>
                    </Table.Td>
                    <Table.Td>{formatDate(line.document_date)}</Table.Td>
                    <Table.Td>
                      {line.material_code} — {line.material_name}
                    </Table.Td>
                    <Table.Td ta="right">
                      {formatNumber(line.quantity)} {line.unit_code}
                    </Table.Td>
                    <Table.Td ta="right">
                      {writable && line.kind === "shipment" && (
                        <Button size="xs" variant="light" onClick={() => setPricing(line)}>
                          {lt.setPrice}
                        </Button>
                      )}
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Stack>
        </Paper>
      )}
      <Group justify="space-between" align="flex-end">
        <Group align="flex-end">
          <Title order={4}>{lt.statement}</Title>
          <TextInput
            label={lt.dateFrom}
            type="date"
            value={dateFrom}
            onChange={(event) => setDateFrom(event.currentTarget.value)}
          />
          <TextInput
            label={lt.dateTo}
            type="date"
            value={dateTo}
            onChange={(event) => setDateTo(event.currentTarget.value)}
          />
        </Group>
        <Group>
          <Button
            variant="default"
            leftSection={<IconFileSpreadsheet size={16} />}
            loading={downloading === "xlsx"}
            onClick={() => void download("xlsx")}
          >
            {lt.excel}
          </Button>
          {amounts && (
            <Button
              variant="default"
              leftSection={<IconFileTypePdf size={16} />}
              loading={downloading === "pdf"}
              onClick={() => void download("pdf")}
            >
              {lt.pdf}
            </Button>
          )}
        </Group>
      </Group>
      {statement.data && statement.data.currencies.length === 0 && (
        <Text size="sm" c="dimmed">
          {lt.noEntries}
        </Text>
      )}
      {(statement.data?.currencies ?? []).map((block) => (
        <Stack key={block.currency} gap="xs">
          <Text fw={600}>
            {lt.currency}: {block.currency}
          </Text>
          <Table.ScrollContainer minWidth={900}>
            <Table striped>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>{lt.date}</Table.Th>
                  <Table.Th>{lt.number}</Table.Th>
                  <Table.Th>{lt.kind}</Table.Th>
                  <Table.Th>{lt.document}</Table.Th>
                  <Table.Th>{lt.description}</Table.Th>
                  <Table.Th>{lt.due}</Table.Th>
                  {amounts && <Table.Th ta="right">{lt.debit}</Table.Th>}
                  {amounts && <Table.Th ta="right">{lt.credit}</Table.Th>}
                  {amounts && <Table.Th ta="right">{lt.balance}</Table.Th>}
                  {writable && <Table.Th />}
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {amounts && dateFrom && (
                  <Table.Tr>
                    <Table.Td>{formatDate(dateFrom)}</Table.Td>
                    <Table.Td colSpan={5}>{lt.opening}</Table.Td>
                    <Table.Td />
                    <Table.Td />
                    <Table.Td ta="right">{balanceText(block.opening, block.currency)}</Table.Td>
                    {writable && <Table.Td />}
                  </Table.Tr>
                )}
                {block.rows.map((row) => (
                  <Table.Tr key={row.entry.id} c={row.is_reversed ? "dimmed" : undefined}>
                    <Table.Td>{formatDate(row.entry.entry_date)}</Table.Td>
                    <Table.Td>{row.entry.number}</Table.Td>
                    <Table.Td>
                      <Group gap={6} wrap="nowrap">
                        <Text size="sm">{row.entry.kind_display}</Text>
                        {row.is_reversed && (
                          <Badge size="xs" color="gray" variant="light">
                            {lt.reversed}
                          </Badge>
                        )}
                      </Group>
                      {row.entry.method_display && (
                        <Text size="xs" c="dimmed">
                          {row.entry.method_display}
                        </Text>
                      )}
                    </Table.Td>
                    <Table.Td>{documentLink(row.entry)}</Table.Td>
                    <Table.Td>
                      <Text size="sm" lineClamp={2}>
                        {row.entry.description}
                      </Text>
                    </Table.Td>
                    <Table.Td>{formatDate(row.due_date)}</Table.Td>
                    {amounts && (
                      <Table.Td ta="right">
                        {Number(row.entry.debit) ? formatMoney(row.entry.debit) : ""}
                      </Table.Td>
                    )}
                    {amounts && (
                      <Table.Td ta="right">
                        {Number(row.entry.credit) ? formatMoney(row.entry.credit) : ""}
                      </Table.Td>
                    )}
                    {amounts && (
                      <Table.Td ta="right">{balanceText(row.balance, block.currency)}</Table.Td>
                    )}
                    {writable && (
                      <Table.Td ta="right">
                        {!row.is_reversed && !AUTO_KINDS.includes(row.entry.kind) && (
                          <Button
                            size="xs"
                            variant="subtle"
                            color="red"
                            onClick={() => setReversing(row.entry)}
                          >
                            {lt.cancel}
                          </Button>
                        )}
                      </Table.Td>
                    )}
                  </Table.Tr>
                ))}
                {amounts && (
                  <Table.Tr fw={700}>
                    <Table.Td colSpan={6}>{lt.total}</Table.Td>
                    <Table.Td ta="right">{formatMoney(block.total_debit)}</Table.Td>
                    <Table.Td ta="right">{formatMoney(block.total_credit)}</Table.Td>
                    <Table.Td ta="right">{balanceText(block.closing, block.currency)}</Table.Td>
                    {writable && <Table.Td />}
                  </Table.Tr>
                )}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        </Stack>
      ))}
      {returns.length > 0 && (
        <Stack gap="xs">
          <Title order={5}>{lt.returnsTitle}</Title>
          {returns.map((item) => (
            <Group key={item.id} gap="xs">
              <Anchor component={Link} to={returnPath(item.id)} size="sm">
                {item.number}
              </Anchor>
              <Text size="sm">{formatDate(item.return_date)}</Text>
              <Badge variant="light" color={item.has_credit ? "green" : "orange"}>
                {item.has_credit ? lt.returnCredited : lt.returnNotCredited}
              </Badge>
            </Group>
          ))}
        </Stack>
      )}
      {entryKind && (
        <EntryModal
          side={side}
          partnerId={id}
          initialKind={entryKind}
          returns={returns}
          onClose={() => setEntryKind(null)}
        />
      )}
      {reversing && (
        <ReverseModal
          side={side}
          partnerId={id}
          entry={reversing}
          onClose={() => setReversing(null)}
        />
      )}
      {pricing && <PriceModal line={pricing} onClose={() => setPricing(null)} />}
    </Stack>
  );
}
