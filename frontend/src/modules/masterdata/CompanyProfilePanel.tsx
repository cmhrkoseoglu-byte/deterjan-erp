import {
  Alert,
  Button,
  Group,
  Loader,
  Paper,
  SimpleGrid,
  Stack,
  Text,
  Textarea,
  TextInput,
  Title,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconInfoCircle } from "@tabler/icons-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";
import { getErrorMessage } from "../../api/client";
import {
  getCompanyProfile,
  saveCompanyProfile,
  type CompanyProfileInput,
} from "../../api/masterdata";
import { useAuth } from "../../auth/AuthContext";
import { hasAnyRole } from "../../auth/roles";

const COMPANY_KEY = ["masterdata", "company"] as const;

const t = {
  title: "Firma bilgileri",
  intro:
    "Firmanın ticari bilgileri sevk irsaliyesinde satıcı, satın alma siparişinde alıcı olarak basılır.",
  readOnly: "Firma bilgilerini yönetim ve sistem yöneticisi değiştirir.",
  legalName: "Ticari unvan",
  address: "Adres",
  taxOffice: "Vergi dairesi",
  taxNumber: "Vergi no / TCKN",
  taxNumberHelp: "10 haneli VKN; şahıs firmasında 11 haneli TCKN",
  tradeRegistryNo: "Ticaret sicil no",
  mersisNo: "MERSİS no",
  mersisHelp: "16 haneli sayı",
  required: "Bu alan zorunlu.",
  taxNumberInvalid: "10 ya da 11 haneli bir sayı olmalı.",
  mersisInvalid: "16 haneli bir sayı olmalı.",
  save: "Kaydet",
  saved: "Firma bilgileri kaydedildi.",
};

const EMPTY: CompanyProfileInput = {
  legal_name: "",
  address: "",
  tax_office: "",
  tax_number: "",
  trade_registry_no: "",
  mersis_no: "",
};

type Errors = Partial<Record<"legal_name" | "tax_number" | "mersis_no", string>>;

const digits = (value: string) => value.replace(/\s+/g, "");

/** Ana veriler > Firma bilgileri: ticari unvan, adres ve vergi/sicil bilgileri (yönetim ve admin
 * düzenler; diğer roller okur). */
export function CompanyProfilePanel() {
  const { user } = useAuth();
  const canEdit = hasAnyRole(user, ["yonetim"]);
  const queryClient = useQueryClient();
  const profile = useQuery({ queryKey: COMPANY_KEY, queryFn: getCompanyProfile });
  const [form, setForm] = useState<CompanyProfileInput>(EMPTY);
  const [errors, setErrors] = useState<Errors>({});

  useEffect(() => {
    const data = profile.data;
    if (!data) return;
    setForm({
      legal_name: data.legal_name,
      address: data.address,
      tax_office: data.tax_office,
      tax_number: data.tax_number,
      trade_registry_no: data.trade_registry_no,
      mersis_no: data.mersis_no,
    });
  }, [profile.data]);

  const save = useMutation({
    mutationFn: () => saveCompanyProfile(form),
    onSuccess: (data) => {
      queryClient.setQueryData(COMPANY_KEY, data);
      notifications.show({ color: "green", message: t.saved });
    },
  });

  function set<K extends keyof CompanyProfileInput>(name: K, value: string) {
    setForm((current) => ({ ...current, [name]: value }));
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const tax = digits(form.tax_number);
    const mersis = digits(form.mersis_no);
    const next: Errors = {
      legal_name: form.legal_name.trim() ? undefined : t.required,
      tax_number: !tax || /^\d{10,11}$/.test(tax) ? undefined : t.taxNumberInvalid,
      mersis_no: !mersis || /^\d{16}$/.test(mersis) ? undefined : t.mersisInvalid,
    };
    setErrors(next);
    if (next.legal_name || next.tax_number || next.mersis_no) return;
    save.mutate();
  }

  if (profile.isLoading) return <Loader />;
  if (profile.isError)
    return (
      <Alert color="red" variant="light">
        {getErrorMessage(profile.error)}
      </Alert>
    );

  return (
    <Paper withBorder p="md" radius="md" maw={760}>
      <form onSubmit={handleSubmit} noValidate>
        <Stack>
          <Title order={4}>{t.title}</Title>
          <Alert color="blue" variant="light" icon={<IconInfoCircle size={18} />}>
            <Text size="sm">{t.intro}</Text>
          </Alert>
          {!canEdit && (
            <Text size="sm" c="dimmed">
              {t.readOnly}
            </Text>
          )}
          {save.isError && (
            <Alert color="red" variant="light" role="alert">
              {getErrorMessage(save.error)}
            </Alert>
          )}
          <TextInput
            label={t.legalName}
            value={form.legal_name}
            onChange={(e) => set("legal_name", e.currentTarget.value)}
            error={errors.legal_name}
            required
            disabled={!canEdit}
            autoComplete="off"
          />
          <Textarea
            label={t.address}
            value={form.address}
            onChange={(e) => set("address", e.currentTarget.value)}
            autosize
            minRows={2}
            disabled={!canEdit}
          />
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <TextInput
              label={t.taxOffice}
              value={form.tax_office}
              onChange={(e) => set("tax_office", e.currentTarget.value)}
              disabled={!canEdit}
              autoComplete="off"
            />
            <TextInput
              label={t.taxNumber}
              placeholder={t.taxNumberHelp}
              value={form.tax_number}
              onChange={(e) => set("tax_number", e.currentTarget.value)}
              error={errors.tax_number}
              inputMode="numeric"
              disabled={!canEdit}
              autoComplete="off"
            />
            <TextInput
              label={t.tradeRegistryNo}
              value={form.trade_registry_no}
              onChange={(e) => set("trade_registry_no", e.currentTarget.value)}
              disabled={!canEdit}
              autoComplete="off"
            />
            <TextInput
              label={t.mersisNo}
              placeholder={t.mersisHelp}
              value={form.mersis_no}
              onChange={(e) => set("mersis_no", e.currentTarget.value)}
              error={errors.mersis_no}
              inputMode="numeric"
              disabled={!canEdit}
              autoComplete="off"
            />
          </SimpleGrid>
          {canEdit && (
            <Group justify="flex-end">
              <Button type="submit" loading={save.isPending}>
                {t.save}
              </Button>
            </Group>
          )}
        </Stack>
      </form>
    </Paper>
  );
}
