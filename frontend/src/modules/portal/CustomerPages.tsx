import { Card, Stack, Text, Title } from "@mantine/core";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import {
  downloadWaybill,
  getCustomerOrder,
  getCustomerShipment,
  listCustomerOrders,
  listCustomerShipments,
  type PortalOrder,
  type PortalOrderLine,
  type PortalShipment,
  type PortalShipmentLine,
} from "../../api/portal";
import { formatDate, formatDateTime, formatMoney, formatNumber } from "../../i18n/format";
import { orderPath, PORTAL_PATHS, shipmentPath } from "./config";
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
  { value: "CONFIRMED", label: "Onaylandı" },
  { value: "PARTIALLY_SHIPPED", label: "Kısmen sevk edildi" },
  { value: "SHIPPED", label: "Sevk edildi" },
  { value: "CLOSED", label: "Kapandı" },
  { value: "CANCELLED", label: "İptal" },
];

const SHIPMENT_STATUSES = [
  { value: "PLANNED", label: "Planlandı" },
  { value: "PICKING", label: "Toplanıyor" },
  { value: "LOADED", label: "Yüklendi" },
  { value: "DISPATCHED", label: "Sevk edildi" },
];

const totalsText = (order: PortalOrder) =>
  order.totals.map((total) => formatMoney(total.amount, total.currency)).join(" + ");

const progressText = (order: PortalOrder) =>
  order.lines
    .map(
      (line) =>
        `${formatNumber(line.shipped_in_unit)} / ${formatNumber(line.quantity)} ${line.unit_code}`,
    )
    .join(", ");

const orderColumns: Column<PortalOrder>[] = [
  { header: pt.number, render: (row) => row.number },
  { header: pt.customerPoNo, render: (row) => row.customer_po_no },
  { header: pt.orderDate, render: (row) => formatDate(row.order_date) },
  { header: pt.due, render: (row) => formatDate(row.due_date) },
  {
    header: pt.status,
    render: (row) => <StatusBadge status={row.status} label={row.status_display} />,
  },
  { header: `${pt.shipped} / ${pt.ordered}`, render: progressText },
  { header: pt.amount, render: totalsText, align: "right" },
];

/** Siparişlerim (müşteri): onaylanmış siparişler. */
export function CustomerOrdersPage() {
  const navigate = useNavigate();
  const filters = useListFilters();
  const params = {
    page: filters.page,
    page_size: PAGE_SIZE,
    search: filters.debounced || undefined,
    status: filters.status ?? undefined,
  };
  const query = useQuery({
    queryKey: ["portal", "customer", "orders", params],
    queryFn: () => listCustomerOrders(params),
    placeholderData: keepPreviousData,
  });
  return (
    <Stack>
      <PageHeader title={pt.menu.orders} intro={pt.customerOrdersIntro} />
      <ListFilters filters={filters} statuses={ORDER_STATUSES} />
      <QueryState isLoading={query.isLoading} error={query.error} />
      {query.data && (
        <DataTable
          testId="portal-orders"
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

const lineColumns: Column<PortalOrderLine>[] = [
  { header: pt.product, render: (row) => `${row.product_code} · ${row.product_name}` },
  {
    header: pt.ordered,
    render: (row) => `${formatNumber(row.quantity)} ${row.unit_code}`,
    align: "right",
  },
  {
    header: pt.shipped,
    render: (row) => `${formatNumber(row.shipped_in_unit)} ${row.unit_code}`,
    align: "right",
  },
  {
    header: pt.remaining,
    render: (row) => `${formatNumber(row.remaining_in_unit)} ${row.unit_code}`,
    align: "right",
  },
  {
    header: pt.unitPrice,
    render: (row) => (row.unit_price ? formatMoney(row.unit_price, row.currency) : ""),
    align: "right",
  },
  {
    header: pt.amount,
    render: (row) => (row.line_total ? formatMoney(row.line_total, row.currency) : ""),
    align: "right",
  },
];

const shipmentColumns: Column<PortalShipment>[] = [
  { header: pt.number, render: (row) => row.number },
  { header: pt.order, render: (row) => row.order_number },
  { header: pt.plannedDate, render: (row) => formatDate(row.planned_date) },
  { header: pt.dispatchedAt, render: (row) => formatDateTime(row.dispatched_at) },
  {
    header: pt.status,
    render: (row) => <StatusBadge status={row.status} label={row.status_display} />,
  },
  { header: pt.vehicle, render: (row) => row.vehicle_plate },
  {
    header: pt.waybill,
    render: (row) =>
      row.has_waybill ? (
        <DownloadButton label={pt.waybill} onDownload={() => downloadWaybill(row)} />
      ) : (
        ""
      ),
  },
];

/** Sipariş sayfası (müşteri): bilgiler, satırlar ve siparişin sevkiyatları. */
export function CustomerOrderPage() {
  const id = Number(useParams().orderId);
  const navigate = useNavigate();
  const order = useQuery({
    queryKey: ["portal", "customer", "order", id],
    queryFn: () => getCustomerOrder(id),
  });
  const shipments = useQuery({
    queryKey: ["portal", "customer", "shipments", { sales_order: id }],
    queryFn: () => listCustomerShipments({ sales_order: id, page_size: 100 }),
  });
  const row = order.data;
  return (
    <Stack>
      <PageHeader title={row ? `${pt.order} ${row.number}` : pt.order} back={PORTAL_PATHS.orders} />
      <QueryState isLoading={order.isLoading} error={order.error} />
      {row && (
        <>
          <Card withBorder>
            <Fields>
              <Field label={pt.status}>
                <StatusBadge status={row.status} label={row.status_display} />
              </Field>
              <Field label={pt.customerPoNo}>{row.customer_po_no}</Field>
              <Field label={pt.orderDate}>{formatDate(row.order_date)}</Field>
              <Field label={pt.requested}>{formatDate(row.requested_delivery_date)}</Field>
              <Field label={pt.promised}>{formatDate(row.promised_date)}</Field>
              <Field label={pt.total}>{totalsText(row)}</Field>
              <Field label={pt.deliveryAddress}>{row.delivery_address}</Field>
            </Fields>
          </Card>
          <DataTable
            testId="portal-order-lines"
            columns={lineColumns}
            rows={row.lines}
            rowKey={(line) => line.line_no}
          />
          <Title order={4}>{pt.orderShipments}</Title>
          <DataTable
            testId="portal-order-shipments"
            columns={shipmentColumns}
            rows={shipments.data?.results ?? []}
            rowKey={(shipment) => shipment.id}
            onOpen={(shipment) => navigate(shipmentPath(shipment.id))}
          />
        </>
      )}
    </Stack>
  );
}

/** Sevkiyatlar (müşteri): planlananlar ve yola çıkanlar. */
export function CustomerShipmentsPage() {
  const navigate = useNavigate();
  const filters = useListFilters();
  const params = {
    page: filters.page,
    page_size: PAGE_SIZE,
    search: filters.debounced || undefined,
    status: filters.status ?? undefined,
  };
  const query = useQuery({
    queryKey: ["portal", "customer", "shipments", params],
    queryFn: () => listCustomerShipments(params),
    placeholderData: keepPreviousData,
  });
  return (
    <Stack>
      <PageHeader title={pt.menu.shipments} intro={pt.shipmentsIntro} />
      <ListFilters filters={filters} statuses={SHIPMENT_STATUSES} />
      <QueryState isLoading={query.isLoading} error={query.error} />
      {query.data && (
        <DataTable
          testId="portal-shipments"
          columns={shipmentColumns}
          rows={query.data.results}
          rowKey={(row) => row.id}
          onOpen={(row) => navigate(shipmentPath(row.id))}
        />
      )}
      <Pages count={query.data?.count ?? 0} filters={filters} />
    </Stack>
  );
}

const shipmentLineColumns: Column<PortalShipmentLine>[] = [
  { header: pt.product, render: (row) => `${row.product_code} · ${row.product_name}` },
  {
    header: pt.quantity,
    render: (row) => `${formatNumber(row.quantity_in_unit)} ${row.unit_code}`,
    align: "right",
  },
  {
    header: "",
    render: (row) => `${formatNumber(row.quantity)} ${row.base_unit_code}`,
    align: "right",
  },
];

/** Sevkiyat sayfası (müşteri): durum, tarih, araç (sevkten sonra), satırlar ve irsaliye. */
export function CustomerShipmentPage() {
  const id = Number(useParams().shipmentId);
  const query = useQuery({
    queryKey: ["portal", "customer", "shipment", id],
    queryFn: () => getCustomerShipment(id),
  });
  const row = query.data;
  return (
    <Stack>
      <PageHeader
        title={row ? `${pt.shipment} ${row.number}` : pt.shipment}
        back={PORTAL_PATHS.shipments}
        actions={
          row?.has_waybill && (
            <DownloadButton label={pt.waybill} onDownload={() => downloadWaybill(row)} />
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
              <Field label={pt.order}>{row.order_number}</Field>
              <Field label={pt.customerPoNo}>{row.customer_po_no}</Field>
              <Field label={pt.plannedDate}>{formatDate(row.planned_date)}</Field>
              <Field label={pt.dispatchedAt}>{formatDateTime(row.dispatched_at)}</Field>
              <Field label={pt.vehicle}>{row.vehicle_plate}</Field>
              <Field label={pt.carrier}>{row.carrier}</Field>
            </Fields>
          </Card>
          {!row.has_waybill && (
            <Text size="sm" c="dimmed">
              {pt.waybillLater}
            </Text>
          )}
          <DataTable
            testId="portal-shipment-lines"
            columns={shipmentLineColumns}
            rows={row.lines ?? []}
            rowKey={(line) => line.line_no}
          />
        </>
      )}
    </Stack>
  );
}
