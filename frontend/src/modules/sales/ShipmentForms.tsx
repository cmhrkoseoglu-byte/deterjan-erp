import {
  Alert,
  Button,
  Group,
  Modal,
  SimpleGrid,
  Stack,
  Table,
  Text,
  TextInput,
  Textarea,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { getErrorMessage } from "../../api/client";
import {
  planShipment,
  updateShipment,
  type SalesOrderDetail,
  type ShipmentDetail,
  type ShipmentHeaderPayload,
} from "../../api/sales";
import { formatNumber } from "../../i18n/format";
import { normalizeDecimal, trimDecimal } from "../common/forms";
import { ct } from "../common/strings";
import { today } from "../inventory/config";
import { st } from "./strings";

interface HeaderDraft {
  planned_date: string;
  vehicle_plate: string;
  driver_name: string;
  driver_id_no: string;
  carrier: string;
  notes: string;
}

function toPayload(draft: HeaderDraft): ShipmentHeaderPayload {
  const id = draft.driver_id_no.replace(/\s/g, "");
  return {
    planned_date: draft.planned_date,
    vehicle_plate: draft.vehicle_plate.trim(),
    driver_name: draft.driver_name.trim(),
    // Boş bırakılan TC no gönderilmez: kayıtlı numara değişmez (okurken yalnızca maskeli gelir).
    ...(id ? { driver_id_no: id } : {}),
    carrier: draft.carrier.trim(),
    notes: draft.notes.trim(),
  };
}

/** Sevkiyat başlığı: tarih, araç, şoför (TC no maskeli saklanır), taşıyıcı, not. */
function HeaderFields({
  value,
  onChange,
  maskedId,
}: {
  value: HeaderDraft;
  onChange: (patch: Partial<HeaderDraft>) => void;
  maskedId?: string;
}) {
  return (
    <SimpleGrid cols={{ base: 1, sm: 2 }}>
      <TextInput
        label={st.plannedDate}
        type="date"
        withAsterisk
        value={value.planned_date}
        onChange={(event) => onChange({ planned_date: event.currentTarget.value })}
      />
      <TextInput
        label={st.vehiclePlate}
        maxLength={20}
        value={value.vehicle_plate}
        onChange={(event) => onChange({ vehicle_plate: event.currentTarget.value })}
      />
      <TextInput
        label={st.driverName}
        maxLength={100}
        value={value.driver_name}
        onChange={(event) => onChange({ driver_name: event.currentTarget.value })}
      />
      <TextInput
        label={st.driverId}
        description={st.driverIdHint}
        placeholder={maskedId || undefined}
        inputMode="numeric"
        maxLength={11}
        autoComplete="off"
        value={value.driver_id_no}
        onChange={(event) => onChange({ driver_id_no: event.currentTarget.value })}
      />
      <TextInput
        label={st.carrier}
        maxLength={100}
        value={value.carrier}
        onChange={(event) => onChange({ carrier: event.currentTarget.value })}
      />
      <Textarea
        label={st.notes}
        autosize
        minRows={1}
        value={value.notes}
        onChange={(event) => onChange({ notes: event.currentTarget.value })}
      />
    </SimpleGrid>
  );
}

/** Siparişten sevkiyat planlar: satır başına kalan miktar gelir, azaltılabilir (D-10). */
export function PlanShipmentModal({
  order,
  onClose,
  onDone,
}: {
  order: SalesOrderDetail;
  onClose: () => void;
  onDone: (shipment: ShipmentDetail) => void;
}) {
  const [header, setHeader] = useState<HeaderDraft>({
    planned_date: order.requested_delivery_date ?? today(),
    vehicle_plate: "",
    driver_name: "",
    driver_id_no: "",
    carrier: "",
    notes: "",
  });
  const lines = order.lines.filter((line) => Number(line.plannable_quantity) > 0);
  const [quantities, setQuantities] = useState<Record<number, string>>(() =>
    Object.fromEntries(lines.map((line) => [line.id!, trimDecimal(line.plannable_quantity ?? "")])),
  );
  const [error, setError] = useState("");
  const mutation = useMutation({
    mutationFn: () =>
      planShipment({
        sales_order: order.id,
        ...toPayload(header),
        lines: lines
          .filter((line) => (quantities[line.id!] ?? "").trim() !== "")
          .map((line) => ({
            order_line: line.id!,
            quantity: normalizeDecimal(quantities[line.id!]),
          }))
          .filter((line) => Number(line.quantity) > 0),
      }),
    onSuccess: (shipment) => {
      notifications.show({ color: "green", message: st.plannedOk });
      onDone(shipment);
    },
    onError: (err) => setError(getErrorMessage(err)),
  });

  return (
    <Modal opened onClose={onClose} title={st.planTitle(order.number)} size="xl">
      <Stack>
        <HeaderFields value={header} onChange={(patch) => setHeader({ ...header, ...patch })} />
        <Text size="sm" c="dimmed">
          {st.planIntro}
        </Text>
        {lines.length === 0 ? (
          <Text size="sm" c="dimmed">
            {st.nothingToPlan}
          </Text>
        ) : (
          <Table.ScrollContainer minWidth={560}>
            <Table fz="sm" data-testid="plan-lines">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>#</Table.Th>
                  <Table.Th>{st.product}</Table.Th>
                  <Table.Th ta="right">{st.plannable}</Table.Th>
                  <Table.Th>{st.shipQuantity}</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {lines.map((line) => (
                  <Table.Tr key={line.id}>
                    <Table.Td>{line.line_no}</Table.Td>
                    <Table.Td>{`${line.product_code} - ${line.product_name}`}</Table.Td>
                    <Table.Td ta="right">
                      {`${formatNumber(line.plannable_quantity)} ${line.base_unit_code ?? ""}`}
                    </Table.Td>
                    <Table.Td>
                      <TextInput
                        aria-label={`${st.shipQuantity} ${line.line_no}`}
                        size="xs"
                        w={120}
                        inputMode="decimal"
                        value={quantities[line.id!] ?? ""}
                        onChange={(event) => {
                          const next = event.currentTarget.value;
                          setQuantities((current) => ({ ...current, [line.id!]: next }));
                        }}
                      />
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        )}
        {error && (
          <Alert color="red" variant="light">
            {error}
          </Alert>
        )}
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            {ct.cancel}
          </Button>
          <Button
            disabled={lines.length === 0 || !header.planned_date}
            loading={mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            {st.plan}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

/** Sevk edilmemiş sevkiyatın araç, şoför, tarih ve notunu düzenler. */
export function EditShipmentModal({
  shipment,
  onClose,
  onDone,
}: {
  shipment: ShipmentDetail;
  onClose: () => void;
  onDone: (shipment: ShipmentDetail) => void;
}) {
  const [header, setHeader] = useState<HeaderDraft>({
    planned_date: shipment.planned_date,
    vehicle_plate: shipment.vehicle_plate,
    driver_name: shipment.driver_name,
    driver_id_no: "",
    carrier: shipment.carrier,
    notes: shipment.notes,
  });
  const [error, setError] = useState("");
  const mutation = useMutation({
    mutationFn: () => updateShipment(shipment.id, toPayload(header)),
    onSuccess: (saved) => {
      notifications.show({ color: "green", message: st.headerSaved });
      onDone(saved);
    },
    onError: (err) => setError(getErrorMessage(err)),
  });

  return (
    <Modal opened onClose={onClose} title={st.editHeader} size="lg">
      <Stack>
        <HeaderFields
          value={header}
          onChange={(patch) => setHeader({ ...header, ...patch })}
          maskedId={shipment.driver_id_no_masked || undefined}
        />
        {shipment.driver_id_no_masked && (
          <Text size="xs" c="dimmed">
            {`${shipment.driver_id_no_masked} · ${st.driverIdKeep}`}
          </Text>
        )}
        {error && (
          <Alert color="red" variant="light">
            {error}
          </Alert>
        )}
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            {ct.cancel}
          </Button>
          <Button
            disabled={!header.planned_date}
            loading={mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            {st.saveHeader}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
