// Maliyet sekmelerinin ortak tablosu ve hata kutusu.
import { Alert, Table, Text } from "@mantine/core";
import type { ReactNode } from "react";
import { getErrorMessage } from "../../api/client";
import { ct } from "../common/strings";

export interface Cell<T> {
  label: string;
  render: (row: T) => ReactNode;
  right?: boolean;
}

export function ErrorAlert({ error }: { error: unknown }) {
  return (
    <Alert color="red" variant="light">
      {getErrorMessage(error)}
    </Alert>
  );
}

export function ReportTable<T>({
  rows,
  cells,
  rowKey,
  minWidth = 760,
  nowrap = false,
}: {
  rows: T[];
  cells: Cell<T>[];
  rowKey: (row: T) => string;
  minWidth?: number;
  /** Hücreler satır kırmaz; dar ekranda tablo yatay kayar. */
  nowrap?: boolean;
}) {
  if (rows.length === 0)
    return (
      <Text size="sm" c="dimmed">
        {ct.empty}
      </Text>
    );
  return (
    <Table.ScrollContainer minWidth={minWidth}>
      <Table striped style={nowrap ? { whiteSpace: "nowrap" } : undefined}>
        <Table.Thead>
          <Table.Tr>
            {cells.map((cell) => (
              <Table.Th key={cell.label} ta={cell.right ? "right" : undefined}>
                {cell.label}
              </Table.Th>
            ))}
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {rows.map((row) => (
            <Table.Tr key={rowKey(row)}>
              {cells.map((cell) => (
                <Table.Td key={cell.label} ta={cell.right ? "right" : undefined}>
                  {cell.render(row)}
                </Table.Td>
              ))}
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  );
}
