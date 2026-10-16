import {
  Alert,
  Anchor,
  Badge,
  Button,
  Checkbox,
  Group,
  Loader,
  Modal,
  Paper,
  SimpleGrid,
  Stack,
  Table,
  Text,
  Textarea,
  Title,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconArrowLeft, IconRefresh } from "@tabler/icons-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getErrorMessage } from "../../api/client";
import { getLotCostHistory, recalculateLotCost, type LotCostDetail } from "../../api/costing";
import { formatDate, formatDateTime, formatMoney, formatNumber } from "../../i18n/format";
import { lotPath } from "../inventory/config";
import { Info, Qty } from "../inventory/shared";
import { COSTING_BASE, lotCostPath } from "./config";
import { CostFlags } from "./CostFlags";
import { kt } from "./strings";

/** Lot maliyeti: güncel sürümün kalem kalem dökümü, eski sürümler ve yeniden hesaplama. */
export function LotCostPage() {
  const lotId = Number(useParams().lotId);
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: ["costing", "lot", lotId],
    queryFn: () => getLotCostHistory(lotId),
  });
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const [cascade, setCascade] = useState(false);
  const recalc = useMutation({
    mutationFn: () => recalculateLotCost(lotId, note.trim(), cascade),
    onSuccess: (data) => {
      queryClient.setQueryData(["costing", "lot", lotId], data);
      void queryClient.invalidateQueries({ queryKey: ["costing", "lot-costs"] });
      notifications.show({ color: "green", message: kt.recalculated });
      setOpen(false);
      setNote("");
      setCascade(false);
    },
  });

  if (query.isLoading) return <Loader />;
  if (query.isError || !query.data)
    return (
      <Alert color="red" variant="light">
        {getErrorMessage(query.error)}
      </Alert>
    );
  const history = query.data;
  const [current, ...older] = history.versions;

  return (
    <Stack>
      <Anchor component={Link} to={COSTING_BASE} size="sm">
        <Group gap={4}>
          <IconArrowLeft size={14} />
          {kt.title}
        </Group>
      </Anchor>
      <Group justify="space-between">
        <div>
          <Title order={2}>{kt.lotCostTitle(history.lot_no)}</Title>
          <Text c="dimmed">
            {history.material_code} — {history.material_name} ·{" "}
            <Anchor component={Link} to={lotPath(history.lot)}>
              {kt.lotDetail}
            </Anchor>
          </Text>
        </div>
        {history.is_costable && (
          <Button leftSection={<IconRefresh size={16} />} onClick={() => setOpen(true)}>
            {kt.recalculate}
          </Button>
        )}
      </Group>
      {!current && (
        <Alert color="gray" variant="light">
          {history.is_costable ? kt.noCost : kt.notCostable}
        </Alert>
      )}
      {current && <CostVersion cost={current} />}
      {older.length > 0 && (
        <Stack gap="xs">
          <Title order={4}>{kt.versions}</Title>
          {older.map((cost) => (
            <CostVersion key={cost.id} cost={cost} compact />
          ))}
        </Stack>
      )}
      <Modal opened={open} onClose={() => setOpen(false)} title={kt.recalcTitle}>
        <Stack>
          <Text size="sm">{kt.recalcHint}</Text>
          <Textarea
            label={kt.recalcNote}
            withAsterisk
            value={note}
            onChange={(event) => setNote(event.currentTarget.value)}
          />
          <Checkbox
            label={kt.cascade}
            checked={cascade}
            onChange={(event) => setCascade(event.currentTarget.checked)}
          />
          {recalc.isError && (
            <Alert color="red" variant="light">
              {getErrorMessage(recalc.error)}
            </Alert>
          )}
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setOpen(false)}>
              {kt.cancel}
            </Button>
            <Button
              onClick={() => recalc.mutate()}
              loading={recalc.isPending}
              disabled={!note.trim()}
            >
              {kt.recalculate}
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}

function CostVersion({ cost, compact = false }: { cost: LotCostDetail; compact?: boolean }) {
  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Group gap="xs">
          <Text fw={700}>{kt.version(cost.version)}</Text>
          {cost.is_current && (
            <Badge color="green" variant="light" size="sm">
              {kt.current}
            </Badge>
          )}
          <Badge variant="light" size="sm">
            {kt.method_[cost.method]}
          </Badge>
          <CostFlags estimated={cost.is_estimated} missing={cost.has_missing} />
        </Group>
        <SimpleGrid cols={{ base: 2, sm: 4 }}>
          <Info label={kt.unitCost}>{`${formatNumber(cost.unit_cost)} / ${cost.unit}`}</Info>
          <Info label={kt.totalCost}>{formatMoney(cost.total_cost)}</Info>
          <Info label={kt.quantity}>{<Qty value={cost.quantity} unit={cost.unit} />}</Info>
          <Info label={kt.date}>{formatDate(cost.cost_date)}</Info>
          {Number(cost.finished_scrap_cost) > 0 && (
            <Info label={kt.finishedScrap}>{formatMoney(cost.finished_scrap_cost)}</Info>
          )}
          <Info
            label={kt.calculatedBy}
          >{`${cost.calculated_by_name ?? ""} ${formatDateTime(cost.calculated_at)}`}</Info>
          {cost.note && <Info label={kt.note}>{cost.note}</Info>}
        </SimpleGrid>
        {!compact && (
          <Table.ScrollContainer minWidth={720}>
            <Table striped>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>{kt.category}</Table.Th>
                  <Table.Th>{kt.description}</Table.Th>
                  <Table.Th>{kt.sourceLot}</Table.Th>
                  <Table.Th ta="right">{kt.quantity}</Table.Th>
                  <Table.Th ta="right">{kt.unitCost}</Table.Th>
                  <Table.Th ta="right">{kt.amount}</Table.Th>
                  <Table.Th />
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {cost.lines.map((line) => (
                  <Table.Tr key={line.line_no}>
                    <Table.Td>{kt.category_[line.category]}</Table.Td>
                    <Table.Td>{line.description}</Table.Td>
                    <Table.Td>
                      {line.source_lot && line.source_lot_no ? (
                        <Anchor component={Link} to={lotCostPath(line.source_lot)} size="sm">
                          {line.source_lot_no}
                        </Anchor>
                      ) : null}
                    </Table.Td>
                    <Table.Td ta="right">
                      {line.quantity ? (
                        <Qty value={line.quantity} unit={line.unit ?? "kg"} />
                      ) : null}
                    </Table.Td>
                    <Table.Td ta="right">{formatNumber(line.unit_cost)}</Table.Td>
                    <Table.Td ta="right">{formatMoney(line.amount)}</Table.Td>
                    <Table.Td>
                      <CostFlags estimated={line.is_estimated} missing={line.is_missing} />
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
              <Table.Tfoot>
                <Table.Tr>
                  <Table.Th colSpan={5}>{kt.totalCost}</Table.Th>
                  <Table.Th ta="right">{formatMoney(cost.total_cost)}</Table.Th>
                  <Table.Th />
                </Table.Tr>
              </Table.Tfoot>
            </Table>
          </Table.ScrollContainer>
        )}
      </Stack>
    </Paper>
  );
}
