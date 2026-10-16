import { Anchor, Box, Group, Stack, Text } from "@mantine/core";
import { IconCornerDownRight } from "@tabler/icons-react";
import { Link } from "react-router-dom";
import type { TraceNode } from "../../api/inventory";
import { formatNumber } from "../../i18n/format";
import { lotPath } from "./config";
import { LotStatusBadge } from "./shared";

/** Soy ağacı: her düğüm lot no (bağlantı), malzeme, kullanılan miktar ve durum. */
export function TraceTree({ root }: { root: TraceNode }) {
  return (
    <Stack gap={4}>
      {root.children.map((child) => (
        <TraceBranch key={`${child.id}`} node={child} depth={0} />
      ))}
    </Stack>
  );
}

function TraceBranch({ node, depth }: { node: TraceNode; depth: number }) {
  return (
    <>
      <Group gap="xs" wrap="nowrap" pl={depth * 24} data-testid="trace-node">
        <Box c="dimmed" style={{ flexShrink: 0 }}>
          <IconCornerDownRight size={16} />
        </Box>
        <Anchor component={Link} to={lotPath(node.id)} fw={600} size="sm">
          {node.lot_no}
        </Anchor>
        <Text size="sm" truncate>
          {`${node.material_code} - ${node.material_name}`}
        </Text>
        {node.quantity !== null && (
          <Text size="sm" c="dimmed" style={{ whiteSpace: "nowrap" }}>
            {`${formatNumber(node.quantity)} ${node.quantity_unit ?? node.unit}`}
          </Text>
        )}
        <LotStatusBadge status={node.status} />
      </Group>
      {node.children.map((child) => (
        <TraceBranch key={`${node.id}-${child.id}`} node={child} depth={depth + 1} />
      ))}
    </>
  );
}
