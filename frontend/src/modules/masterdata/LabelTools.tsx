// Ana verilerde etiketle ilgili ekranlar: lokasyon etiketi yazdırma, yazıcı deneme etiketi ve
// etiket ayarları (firma adı ve varsayılan yazıcı; yalnızca admin değiştirir). GS1 alanları
// burada salt okunurdur; Sistem > Kodlama sistematiği > GS1'de değiştirilir.
import {
  ActionIcon,
  Alert,
  Anchor,
  Button,
  Group,
  Paper,
  Select,
  SimpleGrid,
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
import { Link } from "react-router-dom";
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
import { optionLabel } from "../common/useOptions";
import { SYSTEM_BASE, TABS } from "../system/config";

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
  extension: "SSCC uzantı hanesi",
  nextSerial: "Sıradaki SSCC seri no",
  gs1Before: "GS1 ayarları ",
  gs1Place: "Sistem > Kodlama sistematiği > GS1",
  gs1After: "'de değiştirilir.",
  defaultPrinter: "Varsayılan yazıcı",
  save: "Kaydet",
  saved: "Etiket ayarları kaydedildi.",
  readOnly: "Etiket ayarlarını yalnızca sistem yöneticisi değiştirir.",
  ssccOn: "SSCC palet etiketi açık.",
  ssccOff: "SSCC palet etiketi kapalı (GS1 firma öneki yok).",
};

/** GS1 ayarlarının tek yeri: Sistem > Kodlama sistematiği > GS1 (yalnız admin). */
const GS1_PATH = `${SYSTEM_BASE}/${TABS.coding}?bolum=gs1`;

export function LabelSettingsPanel() {
  const { user } = useAuth();
  const canEdit = hasAnyRole(user, ["admin"]);
  const queryClient = useQueryClient();
  const settings = useQuery({ queryKey: labelQueryKeys.settings, queryFn: getLabelSettings });
  const printers = useQuery({ queryKey: labelQueryKeys.printers, queryFn: listPrinters });
  const [company, setCompany] = useState("");
  const [printer, setPrinter] = useState<string | null>(null);

  useEffect(() => {
    if (!settings.data) return;
    setCompany(settings.data.company_name);
    setPrinter(settings.data.default_printer ? String(settings.data.default_printer) : null);
  }, [settings.data]);

  // GS1 alanları burada gönderilmez; Kodlama > GS1'de notla değiştirilir.
  const save = useMutation({
    mutationFn: () =>
      saveLabelSettings({
        company_name: company,
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
        <Stack gap={4}>
          <SimpleGrid cols={{ base: 1, xs: 3 }}>
            <TextInput label={s.prefix} value={settings.data.gs1_company_prefix} disabled />
            <TextInput
              label={s.extension}
              value={String(settings.data.sscc_extension_digit)}
              disabled
            />
            <TextInput
              label={s.nextSerial}
              value={String(settings.data.next_sscc_serial)}
              disabled
            />
          </SimpleGrid>
          <Text size="sm" c={settings.data.sscc_enabled ? "green.8" : "dimmed"}>
            {settings.data.sscc_enabled ? s.ssccOn : s.ssccOff}
          </Text>
          <Text size="xs" c="dimmed" data-testid="gs1-managed">
            {s.gs1Before}
            {canEdit ? (
              <Anchor component={Link} to={GS1_PATH} size="xs">
                {s.gs1Place}
              </Anchor>
            ) : (
              s.gs1Place
            )}
            {s.gs1After}
          </Text>
        </Stack>
        <Select
          label={s.defaultPrinter}
          data={(printers.data ?? []).map((p) => ({
            value: String(p.id),
            label: optionLabel(p),
          }))}
          value={printer}
          onChange={setPrinter}
          clearable
          disabled={!canEdit}
        />
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
