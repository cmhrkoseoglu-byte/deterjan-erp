import { Card, Stack, Text } from "@mantine/core";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import {
  downloadSupplierOrder,
  getReceipt,
  getSupplierOrder,
  listReceipts,
  listSupplierOrders,
  type Receipt,
  type ReceiptLine,
  type SupplierOrder,
  type SupplierOrderLine,
} from "../../api/portal";
import { formatDate, formatDateTime, formatMoney, formatNumber } from "../../i18n/format";
import { orderPath, PORTAL_PATHS, receiptPath } from "./config";
import { PAGE_SIZE, useListFilters } from "./filters";
import {
  DataTable,
  DownloadButton,
  Field,
  Fields,
  ListFilters,
  PageHeader,
  Pages,
  QueryState,
  StatusBadge,
  type Column,
} from "./shared";
import { pt } from "./strings";

const ORDER_STATUSES = [
  { value: "SENT", label: "Gönderildi" },
  { value: "PARTIALLY_RECEIVED", label: "Kısmen teslim alındı" },
  { value: "RECEIVED", label: "Teslim alındı" },
  { value: "CANCELLED", label: "İptal" },
];

const orderColumns: Column<SupplierOrder>[] = [
  { header: pt.number, render: (row) => row.number },
  { header: pt.orderDate, render: (row) => formatDate(row.order_date) },
  {
    header: pt.status,
    render: (row) => <StatusBadge status={row.status} label={row.status_display} />,
  },
  { header: pt.amount, render: (row) => formatMoney(row.total, row.currency), align: "right" },
  {
    header: pt.orderPdf,
    render: (row) => (
      <DownloadButton label={pt.orderPdf} onDownload={() => downloadSupplierOrder(row)} />
    ),
  },
];

/** Siparişlerim (tedarikçi): gönderilmiş satın alma siparişleri. */
export function SupplierOrdersPage() {
  const navigate = useNavigate();
  const filters = useListFilters();
  const params = {
    page: filters.page,
    page_size: PAGE_SIZE,
    search: filters.debounced || undefined,
    status: filters.status ?? undefined,
  };
  const query = useQuery({
    queryKey: ["portal", "supplier", "orders", params],
    queryFn: () => listSupplierOrders(params),
    placeholderData: keepPreviousData,
  });
  return (
    <Stack>
      <PageHeader title={pt.menu.orders} intro={pt.supplierOrdersIntro} />
      <ListFilters filters={filters} statuses={ORDER_STATUSES} />
      <QueryState isLoading={query.isLoading} error={query.error} />
      {query.data && (
        <DataTable
          testId="portal-supplier-orders"
          columns={orderColumns}
          rows={query.data.results}
          rowKey={(row) => row.id}
          onOpen={(row) => navigate(orderPath(row.id))}
        />
      )}
      <Pages count={query.data?.count ?? 0} filters={filters} />
    </Stack>
  );
}

function lineColumns(currency: string): Column<SupplierOrderLine>[] {
  return [
    { header: pt.material, render: (row) => `${row.material_code} · ${row.material_name}` },
    {
      header: pt.ordered,
      render: (row) => `${formatNumber(row.quantity)} ${row.unit_code}`,
      align: "right",
    },
    {
      header: pt.received,
      render: (row) => `${formatNumber(row.received_in_unit)} ${row.unit_code}`,
      align: "right",
    },
    {
      header: pt.remaining,
      render: (row) => `${formatNumber(row.remaining_in_unit)} ${row.unit_code}`,
      align: "right",
    },
    { header: pt.expectedDate, render: (row) => formatDate(row.expected_date) },
    {
      header: pt.unitPrice,
      render: (row) => formatMoney(row.unit_price, currency),
      align: "right",
    },
    { header: pt.amount, render: (row) => formatMoney(row.line_total, currency), align: "right" },
  ];
}

/** Sipariş sayfası (tedarikçi): bilgiler, notlar, satırlar ve PDF. */
export function SupplierOrderPage() {
  const id = Number(useParams().orderId);
  const query = useQuery({
    queryKey: ["portal", "supplier", "order", id],
    queryFn: () => getSupplierOrder(id),
  });
  const row = query.data;
  return (
    <Stack>
      <PageHeader
        title={row ? `${pt.order} ${row.number}` : pt.order}
        back={PORTAL_PATHS.orders}
        actions={
          row && (
            <DownloadButton label={pt.orderPdf} onDownload={() => downloadSupplierOrder(row)} />
          )
        }
      />
      <QueryState isLoading={query.isLoading} error={query.error} />
      {row && (
        <>
          <Card withBorder>
            <Fields>
              <Field label={pt.status}>
                <StatusBadge status={row.status} label={row.status_display} />
              </Field>
              <Field label={pt.orderDate}>{formatDate(row.order_date)}</Field>
              <Field label={pt.sentAt}>{formatDateTime(row.sent_at)}</Field>
              <Field label={pt.total}>{formatMoney(row.total, row.currency)}</Field>
            </Fields>
            {row.notes && (
              <Stack gap={0} mt="sm">
                <Text size="xs" c="dimmed">
                  {pt.notes}
                </Text>
                <Text size="sm" style={{ whiteSpace: "pre-line" }}>
                  {row.notes}
                </Text>
              </Stack>
            )}
          </Card>
          <DataTable
            testId="portal-supplier-order-lines"
            columns={lineColumns(row.currency)}
            rows={row.lines}
            rowKey={(line) => line.line_no}
          />
        </>
      )}
    </Stack>
  );
}

const receiptColumns: Column<Receipt>[] = [
  { header: pt.number, render: (row) => row.number },
  { header: pt.date, render: (row) => formatDate(row.receipt_date) },
  { header: pt.deliveryNote, render: (row) => row.delivery_note_no },
  {
    header: pt.linkedOrder,
    render: (row) =>
      [...new Set(row.lines.map((line) => line.order_number).filter(Boolean))].join(", "),
  },
];

/** Teslimatlarım (tedarikçi): kaydedilmiş mal kabuller. */
export function ReceiptsPage() {
  const navigate = useNavigate();
  const filters = useListFilters();
  const params = {
    page: filters.page,
    page_size: PAGE_SIZE,
    search: filters.debounced || undefined,
  };
  const query = useQuery({
    queryKey: ["portal", "supplier", "receipts", params],
    queryFn: () => listReceipts(params),
    placeholderData: keepPreviousData,
  });
  return (
    <Stack>
      <PageHeader title={pt.menu.receipts} intro={pt.receiptsIntro} />
      <ListFilters filters={filters} />
      <QueryState isLoading={query.isLoading} error={query.error} />
      {query.data && (
        <DataTable
          testId="portal-receipts"
          columns={receiptColumns}
          rows={query.data.results}
          rowKey={(row) => row.id}
          onOpen={(row) => navigate(receiptPath(row.id))}
        />
      )}
      <Pages count={query.data?.count ?? 0} filters={filters} />
    </Stack>
  );
}

const receiptLineColumns: Column<ReceiptLine>[] = [
  { header: pt.material, render: (row) => `${row.material_code} · ${row.material_name}` },
  {
    header: pt.quantity,
    render: (row) => `${formatNumber(row.quantity)} ${row.unit_code}`,
    align: "right",
  },
  { header: pt.supplierLot, render: (row) => row.supplier_lot_no },
  { header: pt.linkedOrder, render: (row) => row.order_number ?? "" },
];

/** Teslimat sayfası (tedarikçi): mal kabulün satırları. */
export function ReceiptPage() {
  const id = Number(useParams().receiptId);
  const query = useQuery({
    queryKey: ["portal", "supplier", "receipt", id],
    queryFn: () => getReceipt(id),
  });
  const row = query.data;
  return (
    <Stack>
      <PageHeader
        title={row ? `${pt.menu.receipts}: ${row.number}` : pt.menu.receipts}
        back={PORTAL_PATHS.receipts}
      />
      <QueryState isLoading={query.isLoading} error={query.error} />
      {row && (
        <>
          <Card withBorder>
            <Fields>
              <Field label={pt.date}>{formatDate(row.receipt_date)}</Field>
              <Field label={pt.deliveryNote}>{row.delivery_note_no}</Field>
            </Fields>
          </Card>
          <DataTable
            testId="portal-receipt-lines"
            columns={receiptLineColumns}
            rows={row.lines}
            rowKey={(line) => line.line_no}
          />
        </>
      )}
    </Stack>
  );
}
