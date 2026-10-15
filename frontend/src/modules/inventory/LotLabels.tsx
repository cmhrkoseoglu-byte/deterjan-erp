// Lot detayındaki etiket düğmesi ve mamul lotlarının palet (SSCC) etiketleri.
import { Button, Group, NumberInput, Paper, Stack, Table, Text, Title } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconPrinter } from "@tabler/icons-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { getErrorMessage } from "../../api/client";
import type { Lot } from "../../api/inventory";
import {
  createPallet,
  getLabelSettings,
  labelPaths,
  listPallets,
  printPaths,
  labelQueryKeys,
  type PalletLabel,
} from "../../api/labels";
import { useAuth } from "../../auth/AuthContext";
import { hasAnyRole } from "../../auth/roles";
import { LabelPrintModal, type LabelKindOption } from "../../components/labels/LabelPrintModal";
import { formatDateTime } from "../../i18n/format";
import { tr } from "../../i18n/tr";
import { PALLET_ROLES } from "./config";

const t = tr.labels;

/** Lot için etiket seçenekleri: lot etiketi; mamulde koli etiketi (D-6: GTIN'e göre). */
function lotLabelOptions(lot: Pick<Lot, "id" | "material_type" | "material_gtin">) {
  const options: LabelKindOption[] = [
    {
      value: "lot",
      label: t.kindLot,
      downloadPath: labelPaths.lot(lot.id),
      printPath: printPaths.lot(lot.id),
      printKind: "lot",
    },
  ];
  if (lot.material_type === "FINISHED") {
    options.push({
      value: "case",
      label: t.kindCase,
      hint: lot.material_gtin ? t.gs1Hint : t.internalHint,
      downloadPath: labelPaths.case(lot.id),
      printPath: printPaths.lot(lot.id),
      printKind: "case",
      withUnitsPerCase: true,
    });
  }
  return options;
}

export function LotLabelButton({ lot }: { lot: Lot }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button
        variant="default"
        leftSection={<IconPrinter size={16} />}
        onClick={() => setOpen(true)}
      >
        {t.print}
      </Button>
      <LabelPrintModal
        opened={open}
        onClose={() => setOpen(false)}
        options={lotLabelOptions(lot)}
      />
    </>
  );
}

function palletOption(pallet: PalletLabel): LabelKindOption {
  return {
    value: "pallet",
    label: t.kindPallet,
    downloadPath: labelPaths.pallet(pallet.id),
    printPath: printPaths.pallet(pallet.id),
  };
}

/** Mamul lotunun palet etiketleri: liste, yeni SSCC, yazdırma. GS1 öneki yoksa gizli. */
export function PalletSection({ lot }: { lot: Lot }) {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const canCreate = hasAnyRole(user, PALLET_ROLES);
  const [cases, setCases] = useState<number | "">("");
  const [units, setUnits] = useState<number | "">("");
  const [printing, setPrinting] = useState<PalletLabel | null>(null);
  const settings = useQuery({ queryKey: labelQueryKeys.settings, queryFn: getLabelSettings });
  const enabled = settings.data?.sscc_enabled ?? false;
  const pallets = useQuery({
    queryKey: ["inventory", "lot", lot.id, "pallets"],
    queryFn: () => listPallets(lot.id),
    enabled,
  });
  const create = useMutation({
    mutationFn: () =>
      createPallet({ lot: lot.id, case_count: Number(cases), units_per_case: units || null }),
    onSuccess: (pallet) => {
      notifications.show({ color: "green", message: t.palletCreated(pallet.sscc) });
      setCases("");
      void queryClient.invalidateQueries({ queryKey: ["inventory", "lot", lot.id, "pallets"] });
      setPrinting(pallet);
    },
    onError: (err) => notifications.show({ color: "red", message: getErrorMessage(err) }),
  });

  if (lot.material_type !== "FINISHED" || !enabled) return null;
  const rows = pallets.data ?? [];
  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Title order={4}>{t.pallets}</Title>
        {rows.length === 0 ? (
          <Text size="sm" c="dimmed">
            {t.noPallets}
          </Text>
        ) : (
          <Table.ScrollContainer minWidth={420}>
            <Table fz="sm">
              <Table.Tbody>
                {rows.map((pallet) => (
                  <Table.Tr key={pallet.id}>
                    <Table.Td ff="monospace">{pallet.sscc}</Table.Td>
                    <Table.Td>{`${pallet.case_count} koli`}</Table.Td>
                    <Table.Td>{formatDateTime(pallet.created_at)}</Table.Td>
                    <Table.Td ta="right">
                      <Button
                        size="compact-sm"
                        variant="subtle"
                        leftSection={<IconPrinter size={14} />}
                        onClick={() => setPrinting(pallet)}
                      >
                        {t.print}
                      </Button>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        )}
        {canCreate && (
          <Group align="flex-end" gap="xs">
            <NumberInput
              label={t.caseCount}
              min={1}
              value={cases}
              onChange={(value) => setCases(value === "" ? "" : Number(value))}
              w={140}
            />
            <NumberInput
              label={t.unitsPerCase}
              min={1}
              value={units}
              onChange={(value) => setUnits(value === "" ? "" : Number(value))}
              w={140}
            />
            <Button
              disabled={!cases || Number(cases) < 1}
              loading={create.isPending}
              onClick={() => create.mutate()}
            >
              {t.createPallet}
            </Button>
          </Group>
        )}
      </Stack>
      {printing && (
        <LabelPrintModal
          opened
          onClose={() => setPrinting(null)}
          options={[palletOption(printing)]}
          title={`${t.kindPallet}: ${printing.sscc}`}
        />
      )}
    </Paper>
  );
}
