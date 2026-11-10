// Etiket yazdırma penceresi: etiket türü (lot / koli / palet / lokasyon), çıktı (ağ yazıcısı,
// PDF, A4 PDF, ZPL) ve kopya sayısı. Yazıcı listesi ve varsayılan yazıcı etiket ayarlarından gelir.
import {
  Alert,
  Button,
  Group,
  Modal,
  NumberInput,
  SegmentedControl,
  Select,
  Stack,
  Text,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconAlertTriangle, IconPrinter } from "@tabler/icons-react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { getErrorMessage } from "../../api/client";
import {
  getLabelSettings,
  labelQueryKeys,
  labelUrl,
  listPrinters,
  printLabel,
  type LabelOutput,
} from "../../api/labels";
import { formatNumber } from "../../i18n/format";
import { tr } from "../../i18n/tr";
import { optionLabel } from "../../modules/common/useOptions";

const t = tr.labels;

export interface LabelKindOption {
  value: string;
  label: string;
  /** Seçilince gösterilen açıklama (ör. GS1 / firma içi barkod). */
  hint?: string;
  /** Seçilince sarı uyarı olarak gösterilir (ör. koli GTIN'i tanımlı değil). */
  warning?: string;
  /** İndirme yolu, `/api/v1` olmadan (bkz. `labelPaths`). */
  downloadPath: string;
  /** Yazıcıya gönderme yolu (bkz. `printPaths`). */
  printPath: string;
  /** Lot yazdırma ucunda `kind` alanı ("lot" ya da "case"). */
  printKind?: "lot" | "case";
  withUnitsPerCase?: boolean;
  /** "Koli içi adet"in varsayılanı (ör. lotun koli içi adedi). Adet yazılmadıkça alanda durur;
   * pencere açıldıktan sonra gelse de (dolum ekranı lotu açılışta okur) alana gelir. */
  defaultUnitsPerCase?: number;
  /** Etikete basılan koli GTIN'inin koli içi adedi: yazılan adet farklıysa sarı uyarı çıkar. */
  gtinUnitsPerCase?: number;
}

/** Yazılan koli içi adet basılan koli GTIN'inin adedinden farklıysa sarı uyarı (GS1: koli GTIN'i
 * koli içeriğini belirler). Adet boşsa etikete adet yazılmaz, uyarı da çıkmaz. */
export function UnitsPerCaseWarning({
  units,
  gtinUnits,
}: {
  units: number | "";
  gtinUnits?: number;
}) {
  if (!units || gtinUnits === undefined || units === gtinUnits) return null;
  return (
    <Alert
      color="yellow"
      variant="light"
      icon={<IconAlertTriangle size={18} />}
      data-testid="units-warning"
    >
      {t.caseUnitsMismatch(formatNumber(gtinUnits))}
    </Alert>
  );
}

type Output = LabelOutput | "printer";

export function LabelPrintModal({
  opened,
  onClose,
  options,
  title = t.title,
}: {
  opened: boolean;
  onClose: () => void;
  options: LabelKindOption[];
  title?: string;
}) {
  const printers = useQuery({
    queryKey: labelQueryKeys.printers,
    queryFn: listPrinters,
    enabled: opened,
  });
  const settings = useQuery({
    queryKey: labelQueryKeys.settings,
    queryFn: getLabelSettings,
    enabled: opened,
  });
  const [kind, setKind] = useState(options[0]?.value ?? "");
  const [output, setOutput] = useState<Output | null>(null);
  const [printer, setPrinter] = useState<string | null>(null);
  const [copies, setCopies] = useState<number>(1);
  // Koli içi adet; yazılmadıkça (null) seçeneğin varsayılanı gösterilir ve gönderilir.
  const [unitsPerCase, setUnitsPerCase] = useState<number | "" | null>(null);
  const option = options.find((o) => o.value === kind) ?? options[0];
  const shownUnits = unitsPerCase ?? option?.defaultUnitsPerCase ?? "";
  const units = option?.withUnitsPerCase && shownUnits ? shownUnits : null;
  const hasPrinters = (printers.data?.length ?? 0) > 0;
  const effectiveOutput: Output = output ?? (hasPrinters ? "printer" : "pdf");

  useEffect(() => {
    if (!opened) return;
    setKind(options[0]?.value ?? "");
    setCopies(1);
    setOutput(null);
    setUnitsPerCase(null);
    // Seçenekler her çizimde yeniden kurulur; yalnızca açılışta sıfırla.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opened]);

  useEffect(() => {
    if (printer !== null || !printers.data?.length) return;
    const preferred = settings.data?.default_printer;
    const match = printers.data.find((p) => p.id === preferred) ?? printers.data[0];
    setPrinter(String(match.id));
  }, [printers.data, settings.data, printer]);

  const send = useMutation({
    mutationFn: () =>
      printLabel(option.printPath, {
        printer: Number(printer),
        copies,
        ...(option.printKind ? { kind: option.printKind } : {}),
        ...(units ? { units_per_case: units } : {}),
      }),
    onSuccess: (result) => {
      notifications.show({ color: "green", message: t.sent(result.printed, result.printer) });
      onClose();
    },
    onError: (err) => notifications.show({ color: "red", message: getErrorMessage(err) }),
  });

  if (!option) return null;
  const downloadHref =
    effectiveOutput === "printer"
      ? undefined
      : labelUrl(option.downloadPath, {
          output: effectiveOutput,
          copies,
          units_per_case: units,
        });

  return (
    <Modal opened={opened} onClose={onClose} title={title}>
      <Stack>
        {options.length > 1 && (
          <Select
            label={t.kind}
            data={options.map((o) => ({ value: o.value, label: o.label }))}
            value={option.value}
            onChange={(value) => value && setKind(value)}
            allowDeselect={false}
          />
        )}
        {option.hint && (
          <Text size="sm" c="dimmed">
            {option.hint}
          </Text>
        )}
        {option.warning && (
          <Alert
            color="yellow"
            variant="light"
            icon={<IconAlertTriangle size={18} />}
            data-testid="label-warning"
          >
            {option.warning}
          </Alert>
        )}
        <Stack gap={4}>
          <Text size="sm" fw={500}>
            {t.output}
          </Text>
          <SegmentedControl
            fullWidth
            value={effectiveOutput}
            onChange={(value) => setOutput(value as Output)}
            data={[
              { value: "printer", label: t.outputPrinter, disabled: !hasPrinters },
              { value: "pdf", label: t.outputPdf },
              { value: "a4", label: t.outputA4 },
              { value: "zpl", label: t.outputZpl },
            ]}
          />
        </Stack>
        {printers.isSuccess && !hasPrinters && (
          <Text size="xs" c="dimmed">
            {t.noPrinter}
          </Text>
        )}
        {effectiveOutput === "printer" && (
          <Select
            label={t.printer}
            data={(printers.data ?? []).map((p) => ({
              value: String(p.id),
              label: optionLabel(p),
            }))}
            value={printer}
            onChange={setPrinter}
            allowDeselect={false}
          />
        )}
        <Group grow>
          <NumberInput
            label={t.copies}
            min={1}
            max={100}
            value={copies}
            onChange={(value) => setCopies(Math.max(1, Math.min(100, Number(value) || 1)))}
          />
          {option.withUnitsPerCase && (
            <NumberInput
              label={t.unitsPerCase}
              min={1}
              value={shownUnits}
              onChange={(value) => setUnitsPerCase(value === "" ? "" : Number(value))}
            />
          )}
        </Group>
        {option.withUnitsPerCase && (
          <UnitsPerCaseWarning units={units ?? ""} gtinUnits={option.gtinUnitsPerCase} />
        )}
        {send.isError && (
          <Alert color="red" variant="light">
            {getErrorMessage(send.error)}
          </Alert>
        )}
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            {tr.record.cancel}
          </Button>
          {effectiveOutput === "printer" ? (
            <Button
              leftSection={<IconPrinter size={16} />}
              disabled={!printer}
              loading={send.isPending}
              onClick={() => send.mutate()}
            >
              {t.send}
            </Button>
          ) : (
            <Button component="a" href={downloadHref} target="_blank" onClick={onClose}>
              {t.open}
            </Button>
          )}
        </Group>
      </Stack>
    </Modal>
  );
}
