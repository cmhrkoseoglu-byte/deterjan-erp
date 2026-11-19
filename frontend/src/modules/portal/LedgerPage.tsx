import { Badge, Card, Group, SimpleGrid, Stack, Text, TextInput, Title } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import {
  downloadStatementPdf,
  fetchBalances,
  fetchStatement,
  type AgingBucket,
  type PortalBalance,
  type StatementRow,
} from "../../api/portal";
import { useAuth } from "../../auth/AuthContext";
import { formatDate, formatMoney } from "../../i18n/format";
import { portalKind } from "./config";
import { DataTable, DownloadButton, PageHeader, QueryState, type Column } from "./shared";
import { pt } from "./strings";

const BUCKETS: AgingBucket[] = ["not_due", "d1_30", "d31_60", "d61_90", "d90_plus"];

/** Bakiye: tutar, para birimi ve (B) borçlu / (A) alacaklı. */
function balanceText(value: string, currency: string): string {
  const amount = Number(value);
  if (!amount) return formatMoney(0, currency);
  return `${formatMoney(Math.abs(amount), currency)} (${amount > 0 ? "B" : "A"})`;
}

function BalanceCard({ balance }: { balance: PortalBalance }) {
  const overdue = Number(balance.overdue) > 0;
  return (
    <Card withBorder data-testid={`portal-balance-${balance.currency}`}>
      <Stack gap="xs">
        <Text size="xs" c="dimmed">
          {pt.balances} · {balance.currency}
        </Text>
        <Text fw={700} size="xl">
          {balanceText(balance.balance, balance.currency)}
        </Text>
        {overdue && (
          <Badge color="red" variant="light">
            {pt.overdue}: {formatMoney(balance.overdue, balance.currency)}
          </Badge>
        )}
        <Group gap="xs">
          {BUCKETS.filter((bucket) => Number(balance.aging[bucket]) > 0).map((bucket) => (
            <Badge key={bucket} variant="default">
              {pt.aging[bucket]}: {formatMoney(balance.aging[bucket], balance.currency)}
            </Badge>
          ))}
        </Group>
      </Stack>
    </Card>
  );
}

function statementColumns(currency: string): Column<StatementRow>[] {
  const money = (value: string) => (Number(value) ? formatMoney(value, currency) : "");
  return [
    { header: pt.date, render: (row) => formatDate(row.entry_date) },
    { header: pt.kind, render: (row) => row.kind_display },
    { header: pt.document, render: (row) => row.document },
    {
      header: pt.description,
      render: (row) => (row.is_reversed ? `${row.description} (${pt.reversed})` : row.description),
    },
    { header: pt.due, render: (row) => formatDate(row.due_date) },
    { header: pt.debit, render: (row) => money(row.debit), align: "right" },
    { header: pt.credit, render: (row) => money(row.credit), align: "right" },
    { header: pt.balance, render: (row) => balanceText(row.balance, currency), align: "right" },
  ];
}

/** Cari hesabım (müşteri ve tedarikçi): bakiye, yaşlandırma, ekstre ve PDF. */
export function LedgerPage() {
  const { user } = useAuth();
  const kind = portalKind(user) ?? "customer";
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const params = { date_from: dateFrom || undefined, date_to: dateTo || undefined };
  const balances = useQuery({
    queryKey: ["portal", kind, "balances"],
    queryFn: () => fetchBalances(kind),
  });
  const statement = useQuery({
    queryKey: ["portal", kind, "statement", params],
    queryFn: () => fetchStatement(kind, params),
  });

  return (
    <Stack>
      <PageHeader title={pt.menu.ledger} intro={pt.ledgerIntro} />
      <QueryState isLoading={balances.isLoading} error={balances.error} />
      {balances.data && balances.data.length === 0 && (
        <Text size="sm" c="dimmed">
          {pt.noBalance}
        </Text>
      )}
      <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }}>
        {balances.data?.map((balance) => (
          <BalanceCard key={balance.currency} balance={balance} />
        ))}
      </SimpleGrid>
      <Text size="xs" c="dimmed">
        {pt.debtorHint}
      </Text>
      <Group justify="space-between" align="flex-end">
        <Title order={4}>{pt.statement}</Title>
        <Group align="flex-end">
          <TextInput
            type="date"
            label={pt.dateFrom}
            value={dateFrom}
            onChange={(event) => setDateFrom(event.currentTarget.value)}
          />
          <TextInput
            type="date"
            label={pt.dateTo}
            value={dateTo}
            onChange={(event) => setDateTo(event.currentTarget.value)}
          />
          <DownloadButton
            label={pt.statementPdf}
            onDownload={() => downloadStatementPdf(kind, params)}
          />
        </Group>
      </Group>
      <QueryState isLoading={statement.isLoading} error={statement.error} />
      {statement.data?.currencies.map((currency) => (
        <Stack
          key={currency.currency}
          gap="xs"
          data-testid={`portal-statement-${currency.currency}`}
        >
          <Group justify="space-between">
            <Text fw={600}>{currency.currency}</Text>
            <Text size="sm">
              {pt.opening}: {balanceText(currency.opening, currency.currency)} · {pt.closing}:{" "}
              {balanceText(currency.closing, currency.currency)}
            </Text>
          </Group>
          <DataTable
            columns={statementColumns(currency.currency)}
            rows={currency.rows}
            rowKey={(row) => `${row.number}-${row.entry_date}`}
          />
        </Stack>
      ))}
    </Stack>
  );
}
