import { Badge } from "@mantine/core";
import type { VersionStatus } from "../../api/recipes";
import { rt } from "./strings";

export function StatusBadge({ status }: { status: VersionStatus }) {
  return (
    <Badge color={rt.statusColor[status]} variant="light">
      {rt.status[status]}
    </Badge>
  );
}
