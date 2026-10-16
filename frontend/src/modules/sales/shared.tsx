import { Badge } from "@mantine/core";
import type { SalesOrderStatus, ShipmentStatus } from "../../api/sales";
import { ORDER_STATUS_COLOR, SHIPMENT_STATUS_COLOR } from "./config";
import { st } from "./strings";

export function SalesOrderStatusBadge({ status }: { status: SalesOrderStatus }) {
  return (
    <Badge color={ORDER_STATUS_COLOR[status]} variant="light">
      {st.orderStatus[status]}
    </Badge>
  );
}

export function ShipmentStatusBadge({ status }: { status: ShipmentStatus }) {
  return (
    <Badge color={SHIPMENT_STATUS_COLOR[status]} variant="light">
      {st.shipmentStatus[status]}
    </Badge>
  );
}
