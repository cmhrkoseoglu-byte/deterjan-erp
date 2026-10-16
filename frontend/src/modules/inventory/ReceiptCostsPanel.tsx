import {
  ActionIcon,
  Alert,
  Button,
  Group,
  Paper,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
  Textarea,
  Title,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconPlus, IconTrash } from "@tabler/icons-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { getErrorMessage } from "../../api/client";
import {
  setReceiptCosts,
  type Currency,
  type ExtraCostAllocation,
  type ExtraCostKind,
  type GoodsReceiptDetail,
} from "../../api/inventory";
import { normalizeDecimal, trimDecimal } from "../common/forms";
import { Qty } from "./shared";
import { it } from "./strings";

interface PriceDraft {
  id: number;
  unit_price: string;
  currency: Currency;
  exchange_rate: string;
}

interface ExtraDraft {
  key: string;
  id?: number;
  kind: ExtraCostKind;
  description: string;
  amount: string;
  allocation: ExtraCostAllocation;
}

const CURRENCIES = (["TRY", "EUR", "USD"] as const).map((value) => ({
  value,
  label: it.currency_[value],
}));
const KINDS = (["FREIGHT", "CUSTOMS", "OTHER"] as const).map((value) => ({
  value,
  label: it.extraKind_[value],
}));
const ALLOCATIONS = (["QUANTITY", "VALUE"] as const).map((value) => ({
  value,
  label: it.allocation_[value],
}));

let counter = 0;
const newKey = () => `e${++counter}`;
const decimalOrNull = (value: string) => (value.trim() ? normalizeDecimal(value) : null);

/** Mal kabulün alış fiyatları, para birimi, kuru ve ek masrafları (satin_alma, yonetim, admin).
 * Kaydedilmiş mal kabulde not zorunludur; backend oluşan lotların maliyetini yeniden hesaplar. */
export function ReceiptCostsPanel({ doc }: { doc: GoodsReceiptDetail }) {
  const queryClient = useQueryClient();
  const posted = doc.status === "POSTED";
  const [prices, setPrices] = useState<PriceDraft[]>(() =>
    doc.lines.map((line) => ({
      id: line.id!,
      unit_price: line.unit_price ? trimDecimal(line.unit_price) : "",
      currency: line.currency ?? "TRY",
      exchange_rate: line.exchange_rate ? trimDecimal(line.exchange_rate) : "",
    })),
  );
  const [extras, setExtras] = useState<ExtraDraft[]>(() =>
    (doc.extra_costs ?? []).map((row) => ({
      key: `x${row.id}`,
      id: row.id,
      kind: row.kind,
      description: row.description,
      amount: trimDecimal(row.amount),
      allocation: row.allocation,
    })),
  );
  const [note, setNote] = useState("");
  const setPrice = (id: number, patch: Partial<PriceDraft>) =>
    setPrices((rows) => rows.map((row) => (row.id === id ? { ...row, ...patch } : row)));
  const setExtra = (key: string, patch: Partial<ExtraDraft>) =>
    setExtras((rows) => rows.map((row) => (row.key === key ? { ...row, ...patch } : row)));

  const save = useMutation({
    mutationFn: () =>
      setReceiptCosts(doc.id, {
        lines: prices.map((row) => ({
          id: row.id,
          unit_price: decimalOrNull(row.unit_price),
          currency: row.currency,
          exchange_rate: row.currency === "TRY" ? null : decimalOrNull(row.exchange_rate),
        })),
        extra_costs: extras.map((row) => ({
          ...(row.id ? { id: row.id } : {}),
          kind: row.kind,
          description: row.description.trim(),
          amount: normalizeDecimal(row.amount),
          allocation: row.allocation,
        })),
        note: note.trim(),
      }),
    onSuccess: (data) => {
      queryClient.setQueryData(["inventory", "receipt", doc.id], data);
      notifications.show({ color: "green", message: it.costsSaved });
      setNote("");
    },
  });

  return (
    <Paper withBorder p="md" radius="md">
      <Stack>
        <div>
          <Title order={4}>{it.costsTitle}</Title>
          <Text size="sm" c="dimmed">
            {posted ? it.costsPostedHint : it.costsHint}
          </Text>
        </div>
        <Table.ScrollContainer minWidth={640}>
          <Table>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{it.material}</Table.Th>
                <Table.Th ta="right">{it.quantity}</Table.Th>
                <Table.Th>{it.unitPrice}</Table.Th>
                <Table.Th>{it.currency}</Table.Th>
                <Table.Th>{it.exchangeRate}</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {doc.lines.map((line) => {
                const row = prices.find((p) => p.id === line.id)!;
                return (
                  <Table.Tr key={line.id}>
                    <Table.Td>
                      {line.material_code} — {line.material_name}
                    </Table.Td>
                    <Table.Td ta="right">
                      <Qty value={line.quantity} unit={line.unit_code} />
                    </Table.Td>
                    <Table.Td>
                      <TextInput
                        aria-label={`${it.unitPrice} ${line.material_code}`}
                        inputMode="decimal"
                        value={row.unit_price}
                        onChange={(event) =>
                          setPrice(row.id, { unit_price: event.currentTarget.value })
                        }
                      />
                    </Table.Td>
                    <Table.Td>
                      <Select
                        aria-label={`${it.currency} ${line.material_code}`}
                        data={CURRENCIES}
                        value={row.currency}
                        allowDeselect={false}
                        onChange={(value) => setPrice(row.id, { currency: value as Currency })}
                      />
                    </Table.Td>
                    <Table.Td>
                      <TextInput
                        aria-label={`${it.exchangeRate} ${line.material_code}`}
                        inputMode="decimal"
                        disabled={row.currency === "TRY"}
                        value={row.currency === "TRY" ? "" : row.exchange_rate}
                        onChange={(event) =>
                          setPrice(row.id, { exchange_rate: event.currentTarget.value })
                        }
                      />
                    </Table.Td>
                  </Table.Tr>
                );
              })}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
        <Group justify="space-between">
          <Text fw={600}>{it.extraCosts}</Text>
          <Button
            variant="light"
            size="xs"
            leftSection={<IconPlus size={14} />}
            onClick={() =>
              setExtras((rows) => [
                ...rows,
                {
                  key: newKey(),
                  kind: "FREIGHT",
                  description: "",
                  amount: "",
                  allocation: "QUANTITY",
                },
              ])
            }
          >
            {it.addExtraCost}
          </Button>
        </Group>
        {extras.map((row) => (
          <Group key={row.key} align="flex-end" wrap="wrap" data-testid="extra-cost">
            <Select
              label={it.extraKind}
              data={KINDS}
              value={row.kind}
              allowDeselect={false}
              onChange={(value) => setExtra(row.key, { kind: value as ExtraCostKind })}
              w={130}
            />
            <TextInput
              label={it.extraDescription}
              value={row.description}
              onChange={(event) => setExtra(row.key, { description: event.currentTarget.value })}
            />
            <TextInput
              label={it.extraAmount}
              inputMode="decimal"
              value={row.amount}
              onChange={(event) => setExtra(row.key, { amount: event.currentTarget.value })}
              w={130}
            />
            <Select
              label={it.extraAllocation}
              data={ALLOCATIONS}
              value={row.allocation}
              allowDeselect={false}
              onChange={(value) => setExtra(row.key, { allocation: value as ExtraCostAllocation })}
              w={170}
            />
            <ActionIcon
              variant="subtle"
              color="red"
              aria-label={it.removeLine}
              onClick={() => setExtras((rows) => rows.filter((r) => r.key !== row.key))}
            >
              <IconTrash size={16} />
            </ActionIcon>
          </Group>
        ))}
        {posted && (
          <Textarea
            label={it.costsNote}
            withAsterisk
            value={note}
            onChange={(event) => setNote(event.currentTarget.value)}
          />
        )}
        {save.isError && (
          <Alert color="red" variant="light">
            {getErrorMessage(save.error)}
          </Alert>
        )}
        <Group justify="flex-end">
          <Button
            onClick={() => save.mutate()}
            loading={save.isPending}
            disabled={posted && !note.trim()}
          >
            {it.saveCosts}
          </Button>
        </Group>
      </Stack>
    </Paper>
  );
}
