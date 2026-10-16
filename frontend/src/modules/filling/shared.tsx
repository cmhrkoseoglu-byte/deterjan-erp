import { Badge } from "@mantine/core";
import type { FillingOrderStatus, FillingRunStatus, PackagingSpecStatus } from "../../api/filling";
import { ORDER_STATUS_COLOR, RUN_STATUS_COLOR, SPEC_STATUS_COLOR } from "./config";
import { ft } from "./strings";

export function FillingOrderStatusBadge({ status }: { status: FillingOrderStatus }) {
  return (
    <Badge color={ORDER_STATUS_COLOR[status]} variant="light">
      {ft.orderStatus[status]}
    </Badge>
  );
}

export function RunStatusBadge({ status }: { status: FillingRunStatus }) {
  return (
    <Badge color={RUN_STATUS_COLOR[status]} variant="light">
      {ft.runStatus[status]}
    </Badge>
  );
}

export function SpecStatusBadge({ status }: { status: PackagingSpecStatus }) {
  return (
    <Badge color={SPEC_STATUS_COLOR[status]} variant="light">
      {ft.specStatus[status]}
    </Badge>
  );
}
