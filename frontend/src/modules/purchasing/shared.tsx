import { Badge } from "@mantine/core";
import type { PurchaseOrderStatus, PurchaseRequestStatus } from "../../api/purchasing";
import { ORDER_STATUS_COLOR, REQUEST_STATUS_COLOR } from "./config";
import { pt } from "./strings";

export function PurchaseOrderStatusBadge({ status }: { status: PurchaseOrderStatus }) {
  return (
    <Badge color={ORDER_STATUS_COLOR[status]} variant="light">
      {pt.orderStatus[status]}
    </Badge>
  );
}

export function RequestStatusBadge({ status }: { status: PurchaseRequestStatus }) {
  return (
    <Badge color={REQUEST_STATUS_COLOR[status]} variant="light">
      {pt.requestStatus[status]}
    </Badge>
  );
}
