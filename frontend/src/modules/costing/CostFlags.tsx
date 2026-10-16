import { Badge, Group } from "@mantine/core";
import { kt } from "./strings";

/** Tahmini / eksik maliyet işareti. */
export function CostFlags({ estimated, missing }: { estimated: boolean; missing?: boolean }) {
  return (
    <Group gap={4} wrap="nowrap">
      {missing && (
        <Badge color="red" variant="light" size="sm">
          {kt.missing}
        </Badge>
      )}
      {estimated && !missing && (
        <Badge color="yellow" variant="light" size="sm">
          {kt.estimated}
        </Badge>
      )}
    </Group>
  );
}
