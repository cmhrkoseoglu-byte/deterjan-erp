// Ana verilerde etiketle ilgili ekranlar: lokasyon etiketi yazdırma, yazıcı deneme etiketi ve
// etiket ayarları (GS1 firma öneki, SSCC, varsayılan yazıcı; yalnızca admin değiştirir).
import {
  ActionIcon,
  Alert,
  Button,
  Group,
  NumberInput,
  Paper,
  Select,
  Stack,
  Text,
  TextInput,
  Title,
  Tooltip,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconPrinter, IconTestPipe } from "@tabler/icons-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { getErrorMessage } from "../../api/client";
import {
  getLabelSettings,
  labelPaths,
  labelQueryKeys,
  listPrinters,
  printPaths,
  saveLabelSettings,
  testPrinter,
  type Printer,
} from "../../api/labels";
import type { Location } from "../../api/masterdata";
import { useAuth } from "../../auth/AuthContext";
import { hasAnyRole } from "../../auth/roles";
import { LabelPrintModal } from "../../components/labels/LabelPrintModal";
import { tr } from "../../i18n/tr";

const t = tr.labels;

export function LocationLabelAction({ row }: { row: Location }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Tooltip label={t.kindLocation}>
        <ActionIcon
          variant="subtle"
          aria-label={`${t.kindLocation}: ${row.code}`}
          onClick={() => setOpen(true)}
        >
          <IconPrinter size={16} />
        </ActionIcon>
      </Tooltip>
      {open && (
        <LabelPrintModal
          opened
          onClose={() => setOpen(false)}
          title={`${t.kindLocation}: ${row.code}`}
          options={[
            {
              value: "location",
              label: t.kindLocation,
              downloadPath: labelPaths.location(row.id),
              printPath: printPaths.location(row.id),
            },
          ]}
        />
      )}
    </>
  );
}

export function PrinterTestAction({ row }: { row: Printer }) {
  const test = useMutation({
    mutationFn: () => testPrinter(row.id),
    onSuccess: (result) =>
      notifications.show({ color: "green", message: t.testSent(result.printer) }),
    onError: (err) => notifications.show({ color: "red", message: getErrorMessage(err) }),
  });
  if (!row.is_active) return null;
  return (
    <Tooltip label={t.testLabel}>
      <ActionIcon
        variant="subtle"
        aria-label={`${t.testLabel}: ${row.code}`}
        loading={test.isPending}
        onClick={() => test.mutate()}
      >
        <IconTestPipe size={16} />
      </ActionIcon>
    </Tooltip>
  );
}

const s = {
  title: "Etiket ayarları",
  companyName: "Etikette firma adı",
  prefix: "GS1 firma öneki",
  prefixHelp: "6-12 hane. Girilince palet etiketi (SSCC) açılır (Karar D-6).",
  extension: "SSCC uzantı hanesi",
  nextSerial: "Sıradaki SSCC seri no",
  defaultPrinter: "Varsayılan yazıcı",
  save: "Kaydet",
  saved: "Etiket ayarları kaydedildi.",
  readOnly: "Etiket ayarlarını yalnızca sistem yöneticisi değiştirir.",
  ssccOn: "SSCC palet etiketi açık.",
  ssccOff: "SSCC palet etiketi kapalı (GS1 firma öneki yok).",
};

export function LabelSettingsPanel() {
  const { user } = useAuth();
  const canEdit = hasAnyRole(user, ["admin"]);
  const queryClient = useQueryClient();
  const settings = useQuery({ queryKey: labelQueryKeys.settings, queryFn: getLabelSettings });
  const printers = useQuery({ queryKey: labelQueryKeys.printers, queryFn: listPrinters });
  const [company, setCompany] = useState("");
  const [prefix, setPrefix] = useState("");
  const [extension, setExtension] = useState<number>(0);
  const [printer, setPrinter] = useState<string | null>(null);

  useEffect(() => {
    if (!settings.data) return;
    setCompany(settings.data.company_name);
    setPrefix(settings.data.gs1_company_prefix);
    setExtension(settings.data.sscc_extension_digit);
    setPrinter(settings.data.default_printer ? String(settings.data.default_printer) : null);
  }, [settings.data]);

  const save = useMutation({
    mutationFn: () =>
      saveLabelSettings({
        company_name: company,
        gs1_company_prefix: prefix.trim(),
        sscc_extension_digit: extension,
        default_printer: printer ? Number(printer) : null,
      }),
    onSuccess: (data) => {
      queryClient.setQueryData(labelQueryKeys.settings, data);
      notifications.show({ color: "green", message: s.saved });
    },
  });

  if (!settings.data) return null;
  return (
    <Paper withBorder p="md" radius="md" maw={560}>
      <Stack>
        <Title order={4}>{s.title}</Title>
        {!canEdit && (
          <Text size="sm" c="dimmed">
            {s.readOnly}
          </Text>
        )}
        <TextInput
          label={s.companyName}
          value={company}
          disabled={!canEdit}
          onChange={(event) => setCompany(event.currentTarget.value)}
        />
        <TextInput
          label={s.prefix}
          description={s.prefixHelp}
          value={prefix}
          inputMode="numeric"
          disabled={!canEdit}
          onChange={(event) => setPrefix(event.currentTarget.value)}
        />
        <Group grow>
          <NumberInput
            label={s.extension}
            min={0}
            max={9}
            value={extension}
            disabled={!canEdit}
            onChange={(value) => setExtension(Number(value) || 0)}
          />
          <TextInput label={s.nextSerial} value={String(settings.data.next_sscc_serial)} disabled />
        </Group>
        <Select
          label={s.defaultPrinter}
          data={(printers.data ?? []).map((p) => ({
            value: String(p.id),
            label: `${p.code} - ${p.name}`,
          }))}
          value={printer}
          onChange={setPrinter}
          clearable
          disabled={!canEdit}
        />
        <Text size="sm" c={settings.data.sscc_enabled ? "green.8" : "dimmed"}>
          {settings.data.sscc_enabled ? s.ssccOn : s.ssccOff}
        </Text>
        {save.isError && (
          <Alert color="red" variant="light">
            {getErrorMessage(save.error)}
          </Alert>
        )}
        {canEdit && (
          <Group justify="flex-end">
            <Button loading={save.isPending} onClick={() => save.mutate()}>
              {s.save}
            </Button>
          </Group>
        )}
      </Stack>
    </Paper>
  );
}
