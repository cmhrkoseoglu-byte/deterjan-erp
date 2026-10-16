import { Group, Tooltip } from "@mantine/core";
import { IconAlertTriangleFilled } from "@tabler/icons-react";
import type { ReactNode } from "react";

const LABEL = "Tehlikeli madde: güvenlik bilgi formuna (GBF) bakın";

/** Tehlikeli madde uyarı simgesi (Faz 4, İSG). Malzeme kartında GHS piktogramı olan malzemenin
 * lotlarında gösterilir. */
export function HazardIcon({ size = 16 }: { size?: number }) {
  return (
    <Tooltip label={LABEL} withArrow>
      <span role="img" aria-label={LABEL} style={{ display: "inline-flex", color: "#e8590c" }}>
        <IconAlertTriangleFilled size={size} />
      </span>
    </Tooltip>
  );
}

/** Metnin önüne, tehlikeliyse uyarı simgesi koyar. */
export function WithHazard({ hazardous, children }: { hazardous?: boolean; children: ReactNode }) {
  if (!hazardous) return <>{children}</>;
  return (
    <Group gap={4} wrap="nowrap">
      <HazardIcon />
      <span>{children}</span>
    </Group>
  );
}
