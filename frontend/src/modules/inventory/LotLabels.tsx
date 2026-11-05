// Lot detayındaki etiket düğmesi ve mamul lotlarının palet (SSCC) etiketleri.
import { Button, Group, NumberInput, Paper, Stack, Table, Text, Title } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconPrinter } from "@tabler/icons-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { getErrorMessage } from "../../api/client";
import { getLot, type Lot } from "../../api/inventory";
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

/**
 * Lot için etiket seçenekleri: lot etiketi; mamulde koli etiketi (D-6: GTIN'e göre). Koli GTIN'i
 * (`material_case_gtin`) ve `gs1_label` verilmezse bilinmiyor sayılır (dolum ekranı; lot kaydından
 * okunur).
 */
type LabelLot = Pick<
  Lot,
  "id" | "material_type" | "material_gtin" | "material_case_gtin" | "gs1_label"
>;
type LabelHint = Pick<LabelKindOption, "hint" | "warning">;

/** GTIN'i (ürün ya da koli GTIN'i) olan lotun koli etiketine ve paletin GTIN ve lot barkodlarına
 * GS1 barkodu basılamıyor mu (sunucu `gs1_label: false`: lot numarası GS1'e uymuyor ya da GTIN
 * geçersiz)? Bilinmiyorsa bugünkü ipuçları kalır. */
function noGs1Label(lot: LabelLot): boolean {
  return lot.gs1_label === false && Boolean(lot.material_case_gtin || lot.material_gtin);
}

/** Koli etiketi: koli GTIN'i varsa o basılır; yoksa ürün GTIN'i (sarı uyarıyla) ya da firma içi
 * barkod. Koli GTIN'i henüz bilinmiyorsa ürün GTIN'ine göre söylenir. GS1 barkodu basılamıyorsa
 * sarı uyarı. */
function caseHint(lot: LabelLot): LabelHint {
  if (noGs1Label(lot)) return { warning: t.noGs1Label };
  if (lot.material_case_gtin) return { hint: t.caseGtinHint };
  if (!lot.material_gtin) return { hint: t.internalHint };
  if (lot.material_case_gtin === undefined) return { hint: t.gs1Hint };
  return { warning: t.noCaseGtin };
}

/** Palet etiketi: koli GTIN'i varsa (02) koli GTIN'i ve (37) koli sayısı; yoksa ürün GTIN'i. GTIN
 * ve lot barkodları GS1 basılamıyorsa sarı uyarı (SSCC her zaman basılır). */
function palletHint(lot: LabelLot): LabelHint {
  if (noGs1Label(lot)) return { warning: t.noGs1Pallet };
  if (lot.material_case_gtin) return { hint: t.palletCaseGtinHint };
  if (lot.material_gtin && lot.material_case_gtin !== undefined) {
    return { warning: t.noCaseGtinPallet };
  }
  return {};
}

function lotLabelOptions(lot: LabelLot, caseFirst = false) {
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
      ...caseHint(lot),
      downloadPath: labelPaths.case(lot.id),
      printPath: printPaths.lot(lot.id),
      printKind: "case",
      withUnitsPerCase: true,
    });
  }
  return caseFirst ? options.reverse() : options;
}

/** Lot etiketi düğmesi. `caseFirst`: mamulde koli etiketi önce seçili gelir (dolum hattı). */
export function LotLabelButton({
  lot,
  caseFirst = false,
  label = t.print,
}: {
  lot: LabelLot;
  caseFirst?: boolean;
  label?: string;
}) {
  const [open, setOpen] = useState(false);
  // Koli GTIN'i verilmediyse (dolum ekranı) pencere açılınca lot kaydından okunur; `gs1_label` de.
  const detail = useQuery({
    queryKey: ["inventory", "lot", lot.id],
    queryFn: () => getLot(lot.id),
    enabled: open && lot.material_type === "FINISHED" && lot.material_case_gtin === undefined,
  });
  const caseGtin = lot.material_case_gtin ?? detail.data?.material_case_gtin;
  const gs1Label = lot.gs1_label ?? detail.data?.gs1_label;
  return (
    <>
      <Button
        variant="default"
        leftSection={<IconPrinter size={16} />}
        onClick={() => setOpen(true)}
      >
        {label}
      </Button>
      <LabelPrintModal
        opened={open}
        onClose={() => setOpen(false)}
        options={lotLabelOptions(
          { ...lot, material_case_gtin: caseGtin, gs1_label: gs1Label },
          caseFirst,
        )}
      />
    </>
  );
}

function palletOption(pallet: PalletLabel, lot: LabelLot): LabelKindOption {
  return {
    value: "pallet",
    label: t.kindPallet,
    ...palletHint(lot),
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
          options={[palletOption(printing, lot)]}
          title={`${t.kindPallet}: ${printing.sscc}`}
        />
      )}
    </Paper>
  );
}
