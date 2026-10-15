import { Badge } from "@mantine/core";
import { ct } from "./strings";

export function ActiveBadge({ active }: { active: boolean }) {
  return (
    <Badge color={active ? "green" : "gray"} variant="light">
      {active ? ct.active : ct.inactive}
    </Badge>
  );
}
