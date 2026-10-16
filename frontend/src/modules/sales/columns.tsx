import { Badge, Group } from "@mantine/core";
import type { ReactNode } from "react";
import type { SalesOrder, Shipment } from "../../api/sales";
import { formatDate } from "../../i18n/format";
import { SalesOrderStatusBadge, ShipmentStatusBadge } from "./shared";
import { st } from "./strings";

/** Sipariş listesi sütunları (sipariş listesi ve müşteri kartındaki sipariş geçmişi). */
export const orderColumns: {
  header: string;
  render: (row: SalesOrder) => ReactNode;
  align?: "right";
}[] = [
  { header: st.number, render: (r) => r.number },
  { header: st.customer, render: (r) => r.customer_name },
  { header: st.orderDate, render: (r) => formatDate(r.order_date) },
  { header: st.requestedDelivery, render: (r) => formatDate(r.requested_delivery_date) },
  { header: st.customerPo, render: (r) => r.customer_po_no },
  {
    header: st.status,
    render: (r) => (
      <Group gap={4} wrap="nowrap">
        <SalesOrderStatusBadge status={r.status} />
        {r.has_shortage && (
          <Badge color="red" variant="light">
            {st.shortageBadge}
          </Badge>
        )}
      </Group>
    ),
  },
];

/** Sevkiyat listesi sütunları (sevkiyat listesi ve sipariş detayı). */
export const shipmentColumns: {
  header: string;
  render: (row: Shipment) => ReactNode;
  align?: "right";
}[] = [
  { header: st.shipmentNumber, render: (r) => r.number },
  { header: st.order, render: (r) => r.order_number },
  { header: st.customer, render: (r) => r.customer_name },
  { header: st.plannedDate, render: (r) => formatDate(r.planned_date) },
  { header: st.vehiclePlate, render: (r) => r.vehicle_plate },
  { header: st.driverName, render: (r) => r.driver_name },
  { header: st.status, render: (r) => <ShipmentStatusBadge status={r.status} /> },
];
