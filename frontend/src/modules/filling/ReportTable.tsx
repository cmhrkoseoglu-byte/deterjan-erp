import { Alert, Badge, Group, Stack, Table, Text, Title } from "@mantine/core";
import type { ConsumptionReport, ConsumptionRow } from "../../api/filling";
import { formatNumber } from "../../i18n/format";
import { ft } from "./strings";

function Cells({ row, unit }: { row: ConsumptionRow; unit: string }) {
  return (
    <>
      <Table.Td ta="right">{`${formatNumber(row.theoretical)} ${unit}`}</Table.Td>
      <Table.Td ta="right">{`${formatNumber(row.consumed)} ${unit}`}</Table.Td>
      <Table.Td ta="right">{`${formatNumber(row.scrap)} ${unit}`}</Table.Td>
      <Table.Td ta="right">{`${formatNumber(row.actual)} ${unit}`}</Table.Td>
      <Table.Td ta="right">{`${formatNumber(row.variance)} ${unit}`}</Table.Td>
      <Table.Td ta="right">{`%${formatNumber(row.variance_pct)}`}</Table.Td>
    </>
  );
}

/** Dolum raporu: teorik (sağlam adet × reçete) ile gerçek (tüketim + fire) bulk ve ambalaj. */
export function ReportTable({ report }: { report: ConsumptionReport }) {
  if (report.runs.length === 0)
    return (
      <Text size="sm" c="dimmed">
        {ft.noReport}
      </Text>
    );
  return (
    <Stack gap="xs">
      <Group justify="space-between">
        <Title order={4}>{ft.report}</Title>
        <Text size="sm">
          {`${ft.goodUnits}: ${formatNumber(report.good_units)} · ${ft.scrappedUnits}: ${formatNumber(report.scrapped_units)}`}
        </Text>
      </Group>
      {report.bulk_over_threshold && (
        <Alert color="orange" variant="light">
          {ft.overThreshold(formatNumber(report.threshold_pct))}
        </Alert>
      )}
      <Table.ScrollContainer minWidth={720}>
        <Table striped fz="sm" data-testid="consumption-report">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{ft.material}</Table.Th>
              <Table.Th ta="right">{ft.theoretical}</Table.Th>
              <Table.Th ta="right">{ft.consumed}</Table.Th>
              <Table.Th ta="right">{ft.scrap}</Table.Th>
              <Table.Th ta="right">{ft.actual}</Table.Th>
              <Table.Th ta="right">{ft.variance}</Table.Th>
              <Table.Th ta="right">{ft.variancePct}</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            <Table.Tr>
              <Table.Td>
                <Group gap="xs">
                  <Text size="sm" fw={600}>{`${ft.bulk}: ${report.bulk_product_code}`}</Text>
                  {report.bulk_over_threshold && (
                    <Badge size="xs" color="orange">
                      {`>%${formatNumber(report.threshold_pct)}`}
                    </Badge>
                  )}
                </Group>
              </Table.Td>
              <Cells row={report.bulk} unit={report.bulk_unit} />
            </Table.Tr>
            {report.packaging.map((row) => (
              <Table.Tr key={row.material}>
                <Table.Td>
                  <Group gap="xs">
                    <Text size="sm">{`${row.material_code} - ${row.material_name}`}</Text>
                    {row.over_allowance && (
                      <Badge size="xs" color="red" variant="light">
                        {ft.overAllowance}
                      </Badge>
                    )}
                  </Group>
                </Table.Td>
                <Cells row={row} unit={row.unit} />
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
    </Stack>
  );
}
