// Personel > Bordro > Parametreler: bir yılın yasal bordro değerleri (asgari ücret, SGK sınırları ve
// oranları, teşvik, gelir ve damga vergisi, BES). Yasal değerlerle dolu gelir; mali müşavirle
// kontrol edilip kaydedilir (docs/DECISIONS.md "Personel bordrosu").
import {
  Alert,
  Button,
  Group,
  Loader,
  Modal,
  Select,
  SimpleGrid,
  Stack,
  Text,
  Textarea,
  TextInput,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconAlertTriangle, IconInfoCircle } from "@tabler/icons-react";
import { useIsMutating, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import axios from "axios";
import { useState, type ReactNode } from "react";
import { personnelCostKeys } from "../../api/costing";
import {
  getParameterDefaults,
  listParameterSets,
  payrollKeys,
  removeParameterSet,
  saveParameterSet,
  type ParameterSet,
  type ParameterSetValues,
  type PayrollValues,
} from "../../api/payroll";
import { formatDateTime, formatMoney, formatNumber } from "../../i18n/format";
import { normalizeDecimal, trimDecimal } from "../common/forms";
import { parseMoney } from "../costing/personnelCostFormat";
import { ErrorAlert } from "../costing/ReportTable";
import { pe, py } from "./strings";

const NEW = "new";
const BRACKETS = [1, 2, 3, 4] as const;
const RATES = [1, 2, 3, 4, 5] as const;
const MONTH = /^\d{4}-(0[1-9]|1[0-2])$/;
// Kayıt ve kaldırma isteklerinin ortak anahtarı: istek sürerken pencere kapanmaz.
const PARAMETER_WRITE = [...payrollKeys.all, "parameter-write"] as const;
const VALUE_FIELDS: (keyof ParameterSetValues)[] = [
  "minimum_wage",
  "ceiling_multiplier",
  "employee_sgk_rate",
  "employee_unemployment_rate",
  "employer_sgk_rate",
  "employer_unemployment_rate",
  "incentive_points",
  "stamp_tax_per_mille",
  "tax_bracket_1",
  "tax_bracket_2",
  "tax_bracket_3",
  "tax_bracket_4",
  "tax_rate_1",
  "tax_rate_2",
  "tax_rate_3",
  "tax_rate_4",
  "tax_rate_5",
  "bes_rate",
];
// TL tutarları: binlik noktalı yazılabilir (33.030), en çok 2 ondalık, sıfırdan büyük.
const AMOUNT_FIELDS = new Set<keyof ParameterSetValues>([
  "minimum_wage",
  "tax_bracket_1",
  "tax_bracket_2",
  "tax_bracket_3",
  "tax_bracket_4",
]);
const FORM_FIELDS = new Set<string>([...VALUE_FIELDS, "valid_from", "source", "note"]);

type Draft = Record<keyof ParameterSetValues, string> & {
  valid_from: string;
  source: string;
  note: string;
};

/** "33030.00" → "33030", "21.75" → "21,75" (formda Türkçe ondalık). */
const show = (value: string) => trimDecimal(value).replace(".", ",");

function fromSet(set: ParameterSet): Draft {
  const draft = { valid_from: set.valid_from.slice(0, 7), source: set.source, note: set.note };
  return Object.fromEntries([
    ...Object.entries(draft),
    ...VALUE_FIELDS.map((name) => [name, show(set[name])]),
  ]) as Draft;
}

function fromValues(values: PayrollValues, year: number, source: string): Draft {
  const draft: Record<string, string> = {
    valid_from: `${year}-01`,
    source,
    note: "",
    minimum_wage: show(values.minimum_wage),
    ceiling_multiplier: show(values.ceiling_multiplier),
    employee_sgk_rate: show(values.employee_sgk_rate),
    employee_unemployment_rate: show(values.employee_unemployment_rate),
    employer_sgk_rate: show(values.employer_sgk_rate),
    employer_unemployment_rate: show(values.employer_unemployment_rate),
    incentive_points: show(values.incentive_points),
    stamp_tax_per_mille: show(values.stamp_tax_per_mille),
    bes_rate: show(values.bes_rate),
  };
  BRACKETS.forEach((n) => (draft[`tax_bracket_${n}`] = show(values.tax_brackets[n - 1])));
  RATES.forEach((n) => (draft[`tax_rate_${n}`] = show(values.tax_rates[n - 1])));
  return draft as Draft;
}

/**
 * Alanın sayısı, sunucunun sınırlarıyla (geçersizse null): TL tutarları binlik noktalı olabilir;
 * oranlar 0–100 ve en çok 2 ondalık; damga vergisi binde 0–100 ve en çok 3 ondalık; üst sınır
 * çarpanı en az 1. Oranlarda nokta ondalıktır ("7.59" = 7,59), binlik sayılmaz.
 */
function number(name: keyof ParameterSetValues, text: string): string | null {
  if (AMOUNT_FIELDS.has(name)) return parseMoney(text);
  const value = normalizeDecimal(text);
  const places = name === "stamp_tax_per_mille" ? 3 : 2;
  if (!new RegExp(`^\\d{1,3}(\\.\\d{1,${places}})?$`).test(value)) return null;
  const amount = Number(value);
  if (name === "ceiling_multiplier") return amount >= 1 ? value : null;
  return amount <= 100 ? value : null;
}

function invalidMessage(name: keyof ParameterSetValues): string {
  if (AMOUNT_FIELDS.has(name)) return py.invalidAmount;
  if (name === "stamp_tax_per_mille") return py.invalidStampTax;
  if (name === "ceiling_multiplier") return py.invalidMultiplier;
  return py.invalidRate;
}

/** Sunucunun alan hataları ({alan: mesaj}); doğrulama hatası değilse boş. */
function serverFieldErrors(error: unknown): Record<string, string> {
  if (!axios.isAxiosError(error)) return {};
  const data = error.response?.data as
    { code?: string; errors?: Record<string, unknown> } | undefined;
  if (data?.code !== "validation_error" || !data.errors) return {};
  return Object.fromEntries(
    Object.entries(data.errors).map(([name, messages]) => [
      name,
      Array.isArray(messages) ? messages.join(" ") : String(messages),
    ]),
  );
}

/** Günlük alt ve üst sınır ile etkin işveren oranı (kayıttan önce kontrol için). */
function derived(draft: Draft): { floor: string; ceiling: string; rate: string } | null {
  const values = {
    wage: number("minimum_wage", draft.minimum_wage),
    multiplier: number("ceiling_multiplier", draft.ceiling_multiplier),
    employer: number("employer_sgk_rate", draft.employer_sgk_rate),
    incentive: number("incentive_points", draft.incentive_points),
    unemployment: number("employer_unemployment_rate", draft.employer_unemployment_rate),
  };
  if (Object.values(values).some((value) => value === null)) return null;
  const floor = Math.round((Number(values.wage) / 30) * 100) / 100;
  const ceiling = Math.round(floor * Number(values.multiplier) * 100) / 100;
  const rate = Number(values.employer) - Number(values.incentive) + Number(values.unemployment);
  return { floor: formatMoney(floor), ceiling: formatMoney(ceiling), rate: formatNumber(rate) };
}

function Field({
  label,
  name,
  draft,
  serverError,
  onChange,
  description,
}: {
  label: string;
  name: keyof ParameterSetValues;
  draft: Draft;
  serverError?: string;
  onChange: (name: keyof ParameterSetValues, value: string) => void;
  description?: ReactNode;
}) {
  const value = draft[name];
  const local = value.trim() && number(name, value) === null ? invalidMessage(name) : undefined;
  return (
    <TextInput
      label={label}
      description={description}
      inputMode="decimal"
      value={value}
      error={serverError ?? local}
      onChange={(event) => onChange(name, event.currentTarget.value)}
      autoComplete="off"
    />
  );
}

function ParametersForm({
  initial,
  initialNotice,
  setId,
  set,
  year,
  onClose,
}: {
  initial: Draft;
  /** Pencere açılırken gösterilecek uyarı (ör. yılın yasal değerleri yok, başka yılınki dolu). */
  initialNotice: string | null;
  setId: number | null;
  set: ParameterSet | null;
  year: number;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<Draft>(initial);
  const [notice, setNotice] = useState<string | null>(initialNotice);
  const [serverErrors, setServerErrors] = useState<Record<string, string>>({});
  const [removing, setRemoving] = useState(false);
  const [reason, setReason] = useState("");
  const monthOk = MONTH.test(draft.valid_from);
  const draftYear = monthOk ? Number(draft.valid_from.slice(0, 4)) : year;
  const change = (name: keyof Draft, value: string) => {
    setDraft((d) => ({ ...d, [name]: value }));
    setServerErrors((errors) => {
      if (!(name in errors)) return errors;
      const next = { ...errors };
      delete next[name];
      return next;
    });
    if (name === "valid_from") setNotice(null);
  };
  // Seçilen ayın yılının yasal değerleri (düğme ve uyarı bunu söyler; bilinmiyorsa en yakın yıl).
  const draftDefaults = useQuery({
    queryKey: payrollKeys.defaults(draftYear),
    queryFn: () => getParameterDefaults(draftYear),
    enabled: monthOk,
  });
  const yearUnknown = monthOk && draftDefaults.data?.known === false;

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: payrollKeys.all });
    void queryClient.invalidateQueries({ queryKey: personnelCostKeys.all });
  };
  const fill = () => {
    const defaults = draftDefaults.data;
    if (!defaults) return;
    const filled = fromValues(defaults.values, draftYear, defaults.legal_source);
    setDraft((d) => ({ ...filled, valid_from: d.valid_from, note: d.note }));
    setServerErrors({});
    setNotice(defaults.known ? null : py.legalUnknown(defaults.year, defaults.values_year));
  };
  const save = useMutation({
    mutationKey: PARAMETER_WRITE,
    mutationFn: () => {
      const values = Object.fromEntries(
        VALUE_FIELDS.map((name) => [name, number(name, draft[name]) ?? ""]),
      ) as Record<keyof ParameterSetValues, string>;
      return saveParameterSet(setId, {
        ...values,
        valid_from: draft.valid_from,
        source: draft.source.trim(),
        note: draft.note.trim(),
      });
    },
    onSuccess: () => {
      notifications.show({ color: "green", message: py.parametersSaved_ });
      refresh();
    },
    onError: (error) => setServerErrors(serverFieldErrors(error)),
  });
  const remove = useMutation({
    mutationKey: PARAMETER_WRITE,
    mutationFn: () => removeParameterSet(setId ?? 0, reason.trim()),
    onSuccess: () => {
      notifications.show({ color: "green", message: py.setRemoved });
      refresh();
    },
  });
  const invalid = !monthOk || VALUE_FIELDS.some((name) => number(name, draft[name]) === null);
  const preview = derived(draft);
  const busy = save.isPending || remove.isPending;
  // Alanın altına yazılamayan sunucu hataları (ör. genel doğrulama) uyarı olarak görünür.
  const unplaced = Object.entries(serverErrors).filter(([name]) => !FORM_FIELDS.has(name));
  // Genel uyarı yalnız alan hatası taşımayan yanıtta (iş kuralı, yetki, ağ): alan düzeltilince ya
  // da "doldur"a basılınca "Gönderilen bilgiler geçersiz." yeniden çıkmasın.
  const fieldErrorResponse = Object.keys(serverFieldErrors(save.error)).length > 0;
  const field = (label: string, name: keyof ParameterSetValues, description?: ReactNode) => (
    <Field
      label={label}
      name={name}
      draft={draft}
      serverError={serverErrors[name]}
      onChange={change}
      description={description}
    />
  );

  if (removing)
    return (
      <Stack>
        <Text size="sm">{py.removeSetIntro}</Text>
        <Textarea
          label={py.removeReason}
          withAsterisk
          autosize
          minRows={2}
          maxLength={500}
          value={reason}
          disabled={busy}
          onChange={(event) => setReason(event.currentTarget.value)}
        />
        {remove.isError && <ErrorAlert error={remove.error} />}
        <Group justify="flex-end">
          <Button variant="default" onClick={() => setRemoving(false)} disabled={busy}>
            {py.cancel}
          </Button>
          <Button
            color="red"
            onClick={() => remove.mutate(undefined, { onSuccess: onClose })}
            loading={remove.isPending}
            disabled={!reason.trim()}
          >
            {py.removeSet}
          </Button>
        </Group>
      </Stack>
    );

  return (
    <Stack>
      <Group align="flex-end" wrap="wrap">
        <TextInput
          label={py.validFrom}
          type="month"
          placeholder={pe.periodPlaceholder}
          value={draft.valid_from}
          error={
            serverErrors.valid_from ?? (draft.valid_from && !monthOk ? pe.periodInvalid : undefined)
          }
          onChange={(event) => change("valid_from", event.currentTarget.value)}
          w={200}
        />
        <Button
          variant="light"
          onClick={fill}
          loading={monthOk && draftDefaults.isLoading}
          disabled={!monthOk || !draftDefaults.data || busy}
        >
          {yearUnknown && draftDefaults.data
            ? py.fillNearest(draftDefaults.data.values_year)
            : py.fillLegal(draftYear)}
        </Button>
      </Group>
      {notice ? (
        <Alert
          color={yearUnknown ? "red" : "yellow"}
          variant="light"
          icon={yearUnknown ? <IconAlertTriangle size={18} /> : undefined}
        >
          <Text size="sm">{notice}</Text>
        </Alert>
      ) : (
        yearUnknown && (
          <Alert color="red" variant="light" icon={<IconAlertTriangle size={18} />}>
            <Text size="sm">{py.yearUnknown(draftYear)}</Text>
          </Alert>
        )
      )}
      {draftDefaults.isError && <ErrorAlert error={draftDefaults.error} />}
      <Text fw={600}>{py.groupWage}</Text>
      <SimpleGrid cols={{ base: 1, sm: 2 }}>
        {field(py.minimumWage, "minimum_wage")}
        {field(py.ceilingMultiplier, "ceiling_multiplier")}
      </SimpleGrid>
      <Text fw={600}>{py.groupRates}</Text>
      <SimpleGrid cols={{ base: 1, sm: 2 }}>
        {field(py.employeeSgkRate, "employee_sgk_rate")}
        {field(py.employeeUnemploymentRate, "employee_unemployment_rate")}
        {field(py.employerSgkRate, "employer_sgk_rate")}
        {field(py.employerUnemploymentRate, "employer_unemployment_rate")}
        <Select
          label={py.incentivePoints}
          description={py.incentiveHelp}
          data={
            py.incentiveOptions.some((option) => option.value === draft.incentive_points)
              ? py.incentiveOptions
              : [
                  ...py.incentiveOptions,
                  { value: draft.incentive_points, label: draft.incentive_points },
                ]
          }
          value={draft.incentive_points}
          error={serverErrors.incentive_points}
          allowDeselect={false}
          onChange={(value) => value !== null && change("incentive_points", value)}
        />
        {field(py.besRate, "bes_rate")}
      </SimpleGrid>
      {preview && (
        <Text size="sm" c="dimmed">
          {py.derived(preview.floor, preview.ceiling, preview.rate)}
        </Text>
      )}
      <Text fw={600}>{py.groupTax}</Text>
      <SimpleGrid cols={{ base: 1, sm: 2 }}>
        {BRACKETS.map((n) => (
          <Field
            key={`bracket-${n}`}
            label={py.bracket(n)}
            name={`tax_bracket_${n}`}
            draft={draft}
            serverError={serverErrors[`tax_bracket_${n}`]}
            onChange={change}
          />
        ))}
        {RATES.map((n) => (
          <Field
            key={`rate-${n}`}
            label={py.rate(n)}
            name={`tax_rate_${n}`}
            draft={draft}
            serverError={serverErrors[`tax_rate_${n}`]}
            onChange={change}
          />
        ))}
        {field(py.stampTax, "stamp_tax_per_mille")}
      </SimpleGrid>
      <Textarea
        label={py.source}
        autosize
        minRows={2}
        maxLength={500}
        value={draft.source}
        error={serverErrors.source}
        onChange={(event) => change("source", event.currentTarget.value)}
      />
      <TextInput
        label={py.note}
        maxLength={200}
        value={draft.note}
        error={serverErrors.note}
        onChange={(event) => change("note", event.currentTarget.value)}
      />
      {set?.updated_by_name && (
        <Text size="xs" c="dimmed">
          {py.updatedBy(set.updated_by_name, formatDateTime(set.updated_at))}
        </Text>
      )}
      {save.isError && !fieldErrorResponse && <ErrorAlert error={save.error} />}
      {unplaced.length > 0 && (
        <Alert color="red" variant="light">
          {unplaced.map(([name, message]) => (
            <Text key={name} size="sm">
              {message}
            </Text>
          ))}
        </Alert>
      )}
      <Group justify="space-between">
        {setId !== null ? (
          <Button variant="subtle" color="red" onClick={() => setRemoving(true)} disabled={busy}>
            {py.removeSet}
          </Button>
        ) : (
          <span />
        )}
        <Group>
          <Button variant="default" onClick={onClose} disabled={busy}>
            {py.cancel}
          </Button>
          <Button
            onClick={() => save.mutate(undefined, { onSuccess: onClose })}
            loading={save.isPending}
            disabled={invalid}
          >
            {py.checkedAndSave}
          </Button>
        </Group>
      </Group>
    </Stack>
  );
}

/** Parametre setleri: kayıtlı setlerden biri ya da yeni set (yılın yasal değerleriyle dolu). */
export function PayrollParametersModal({
  year,
  currentRecord,
  onClose,
}: {
  /** Bordrosu görüntülenen ayın yılı. */
  year: number;
  /** O ayın hesabında kullanılan kayıtlı set (yoksa boş). */
  currentRecord: number | null;
  onClose: () => void;
}) {
  const sets = useQuery({ queryKey: payrollKeys.parameters, queryFn: listParameterSets });
  const defaults = useQuery({
    queryKey: payrollKeys.defaults(year),
    queryFn: () => getParameterDefaults(year),
  });
  // Kayıt ya da kaldırma sürerken pencere kapanmaz (geç gelen yanıt başka pencereyi kapatmasın).
  const busy = useIsMutating({ mutationKey: PARAMETER_WRITE }) > 0;
  const close = () => {
    if (!busy) onClose();
  };
  const [selected, setSelected] = useState<string>(
    currentRecord !== null ? String(currentRecord) : NEW,
  );
  const list = sets.data ?? [];
  const set = list.find((item) => String(item.id) === selected) ?? null;
  const ready = sets.data && defaults.data && (selected === NEW || set);
  const options = [
    ...list.map((item) => ({
      value: String(item.id),
      label: py.setLabel(`${item.valid_from.slice(5, 7)}.${item.year}`),
    })),
    { value: NEW, label: py.newSet },
  ];
  // Yeni set yasal değeri bilinmeyen yıl için en yakın yılın değerleriyle dolu açılır: uyarılır.
  const initialNotice =
    !set && defaults.data && !defaults.data.known
      ? py.legalUnknown(defaults.data.year, defaults.data.values_year)
      : null;
  return (
    <Modal
      opened
      onClose={close}
      title={py.parametersTitle}
      size="xl"
      closeOnClickOutside={false}
      closeOnEscape={!busy}
      withCloseButton={!busy}
    >
      <Stack>
        <Alert color="blue" variant="light" icon={<IconInfoCircle size={18} />}>
          <Text size="sm">{py.parametersIntro}</Text>
        </Alert>
        {(sets.isError || defaults.isError) && <ErrorAlert error={sets.error ?? defaults.error} />}
        <Select
          label={py.editing}
          data={options}
          value={selected}
          allowDeselect={false}
          disabled={busy}
          onChange={(value) => value && setSelected(value)}
          w={260}
        />
        {!ready ? (
          <Loader size="sm" />
        ) : (
          <ParametersForm
            key={selected}
            initial={
              set
                ? fromSet(set)
                : fromValues(defaults.data!.values, year, defaults.data!.legal_source)
            }
            initialNotice={initialNotice}
            setId={set ? set.id : null}
            set={set}
            year={year}
            onClose={onClose}
          />
        )}
      </Stack>
    </Modal>
  );
}
