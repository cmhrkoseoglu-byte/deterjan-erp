// Maliyet > Personel ücretleri: brüt aylık ücretler (geçerlilik tarihli), birimlerin maliyet
// aşaması ve işveren payı. Ücretler kişisel veridir (docs/KVKK.md); yalnızca yönetim görür.
import {
  Badge,
  Button,
  Group,
  Loader,
  Modal,
  Select,
  Stack,
  Switch,
  Text,
  Textarea,
  TextInput,
  Title,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconPlus } from "@tabler/icons-react";
import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  addWage,
  getPersonnelCostSettings,
  getWageSummary,
  listCostCenters,
  personnelCostKeys,
  removeWage,
  setCostCenter,
  updatePersonnelCostSettings,
  type CostCenter,
  type CostCenterStage,
  type EmployeeWage,
  type WageSummaryRow,
} from "../../api/costing";
import { formatDate, formatDateTime, formatMoney } from "../../i18n/format";
import { normalizeDecimal, trimDecimal } from "../common/forms";
import {
  currentMonthStart,
  parseMoney,
  previousMonthStart,
  stageLabel,
} from "./personnelCostFormat";
import { ErrorAlert, ReportTable } from "./ReportTable";
import { kt } from "./strings";

// Select boş değer taşımaz: genel gider arayüzde "GENERAL", API'de boş.
const GENERAL = "GENERAL";
const STAGE_OPTIONS = (["", "PRODUCTION", "FILLING"] as CostCenterStage[]).map((stage) => ({
  value: stage || GENERAL,
  label: stageLabel(stage),
}));
// Ücret 2000'den önce başlayamaz (backend sınırı).
const EARLIEST_WAGE_DATE = "2000-01-01";
const NO_WRAP = { whiteSpace: "nowrap" } as const;

/** Ücret ya da eşleştirme değişince rapor, ücret listeleri ve birimler yeniden okunur. */
function refresh(queryClient: QueryClient) {
  for (const queryKey of [
    personnelCostKeys.all,
    personnelCostKeys.wages,
    personnelCostKeys.costCenters,
  ])
    void queryClient.invalidateQueries({ queryKey });
}

/** İlk ücret işe girişten (bilinmiyorsa geçen ayın başından), zam bu ayın başından geçerli. */
function defaultValidFrom(row: WageSummaryRow): string {
  if (row.history.length) return currentMonthStart();
  const hired = row.employee.hire_date;
  if (!hired) return previousMonthStart();
  return hired < EARLIEST_WAGE_DATE ? EARLIEST_WAGE_DATE : hired;
}

function LeftBadge({ date }: { date: string | null }) {
  if (!date) return null;
  return (
    <Badge color="gray" variant="light" size="sm" tt="none">
      {kt.leftOn(formatDate(date))}
    </Badge>
  );
}

function WageModal({ row, onClose }: { row: WageSummaryRow; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState(() => ({
    amount: "",
    valid_from: defaultValidFrom(row),
    note: "",
  }));
  const amount = parseMoney(draft.amount);
  // Yazarken sondaki nokta ya da virgül (ör. "45.") henüz hata sayılmaz.
  const typing = /[.,]$/.test(draft.amount.trim());
  const save = useMutation({
    mutationFn: () =>
      addWage({
        employee: row.employee.id,
        gross_monthly: amount ?? "",
        valid_from: draft.valid_from,
        note: draft.note.trim(),
      }),
    onSuccess: () => {
      notifications.show({ color: "green", message: kt.wageSaved });
      refresh(queryClient);
    },
  });
  // İstek sürerken pencere kapanmaz (geç gelen yanıt başka bir pencereyi kapatmasın).
  const close = () => {
    if (!save.isPending) onClose();
  };
  let amountHelp: string | undefined;
  if (amount) amountHelp = kt.amountPreview(formatMoney(amount, "TL"));
  return (
    <Modal
      opened
      onClose={close}
      title={kt.wageTitle(row.employee.full_name)}
      closeOnClickOutside={false}
      closeOnEscape={!save.isPending}
      withCloseButton={!save.isPending}
    >
      <Stack>
        {row.current_wage ? (
          <Text size="sm" c="dimmed">
            {kt.wageNow(formatMoney(row.current_wage, "TL"), formatDate(row.current_valid_from))}
          </Text>
        ) : (
          !row.history.length && (
            <Text size="sm" c="dimmed">
              {kt.firstWageHint(Boolean(row.employee.hire_date))}
            </Text>
          )
        )}
        <TextInput
          label={kt.grossMonthly}
          withAsterisk
          inputMode="decimal"
          value={draft.amount}
          description={amountHelp}
          inputWrapperOrder={["label", "input", "description", "error"]}
          error={draft.amount.trim() && amount === null && !typing ? kt.invalidAmount : undefined}
          onChange={(event) => {
            const value = event.currentTarget.value;
            setDraft((d) => ({ ...d, amount: value }));
          }}
        />
        <TextInput
          label={kt.validFrom}
          type="date"
          withAsterisk
          value={draft.valid_from}
          onChange={(event) => {
            const value = event.currentTarget.value;
            setDraft((d) => ({ ...d, valid_from: value }));
          }}
        />
        <TextInput
          label={kt.note}
          maxLength={200}
          value={draft.note}
          onChange={(event) => {
            const value = event.currentTarget.value;
            setDraft((d) => ({ ...d, note: value }));
          }}
        />
        {save.isError && <ErrorAlert error={save.error} />}
        <Group justify="flex-end">
          <Button variant="default" onClick={close} disabled={save.isPending}>
            {kt.cancel}
          </Button>
          <Button
            onClick={() => save.mutate(undefined, { onSuccess: onClose })}
            loading={save.isPending}
            disabled={amount === null || !draft.valid_from}
          >
            {kt.save}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

function WageHistoryModal({ row, onClose }: { row: WageSummaryRow; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [removing, setRemoving] = useState<EmployeeWage | null>(null);
  const [reason, setReason] = useState("");
  const remove = useMutation({
    mutationFn: (wage: EmployeeWage) => removeWage(wage.id, reason.trim()),
    onSuccess: () => {
      notifications.show({ color: "green", message: kt.wageRemoved });
      refresh(queryClient);
    },
  });
  const close = () => {
    if (!remove.isPending) onClose();
  };
  const label = (wage: EmployeeWage) =>
    `${formatDate(wage.valid_from)} · ${formatMoney(wage.gross_monthly, "TL")}`;
  return (
    <Modal
      opened
      onClose={close}
      title={kt.historyTitle(row.employee.full_name)}
      size="lg"
      closeOnClickOutside={false}
      closeOnEscape={!remove.isPending}
      withCloseButton={!remove.isPending}
    >
      {removing ? (
        <Stack>
          <Text size="sm">{kt.removeWageIntro}</Text>
          <Text size="sm" fw={600}>
            {label(removing)}
          </Text>
          <Textarea
            label={kt.removeReason}
            withAsterisk
            autosize
            minRows={2}
            maxLength={500}
            value={reason}
            onChange={(event) => setReason(event.currentTarget.value)}
          />
          {remove.isError && <ErrorAlert error={remove.error} />}
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setRemoving(null)} disabled={remove.isPending}>
              {kt.cancel}
            </Button>
            <Button
              color="red"
              onClick={() => remove.mutate(removing, { onSuccess: () => setRemoving(null) })}
              loading={remove.isPending}
              disabled={!reason.trim()}
            >
              {kt.removeWage}
            </Button>
          </Group>
        </Stack>
      ) : (
        <ReportTable
          rows={row.history}
          rowKey={(wage) => String(wage.id)}
          minWidth={560}
          cells={[
            { label: kt.validFrom, render: (wage) => formatDate(wage.valid_from) },
            {
              label: kt.grossMonthly,
              right: true,
              render: (wage) => formatMoney(wage.gross_monthly),
            },
            { label: kt.note, render: (wage) => wage.note },
            {
              label: kt.enteredBy,
              render: (wage) =>
                [wage.created_by_name, formatDateTime(wage.created_at)].filter(Boolean).join(" · "),
            },
            {
              label: "",
              render: (wage) => (
                <Group justify="flex-end">
                  <Button
                    size="xs"
                    variant="subtle"
                    color="red"
                    aria-label={kt.removeWageLabel(
                      formatDate(wage.valid_from),
                      formatMoney(wage.gross_monthly, "TL"),
                    )}
                    onClick={() => {
                      setRemoving(wage);
                      setReason("");
                      remove.reset();
                    }}
                  >
                    {kt.removeWage}
                  </Button>
                </Group>
              ),
            },
          ]}
        />
      )}
    </Modal>
  );
}

function CostCentersSection() {
  const queryClient = useQueryClient();
  const centers = useQuery({ queryKey: personnelCostKeys.costCenters, queryFn: listCostCenters });
  const save = useMutation({
    mutationFn: (center: CostCenter) => setCostCenter(center),
    onSuccess: () => {
      notifications.show({ color: "green", message: kt.costCenterSaved });
      refresh(queryClient);
    },
  });
  return (
    <Stack gap="xs">
      <Title order={4}>{kt.costCenters}</Title>
      <Text size="sm" c="dimmed" maw={860}>
        {kt.costCentersHint}
      </Text>
      {centers.isError && <ErrorAlert error={centers.error} />}
      {save.isError && <ErrorAlert error={save.error} />}
      {centers.isLoading ? (
        <Loader size="sm" />
      ) : (
        <ReportTable
          rows={centers.data ?? []}
          rowKey={(center) => center.department}
          minWidth={420}
          cells={[
            { label: kt.department, render: (center) => center.department },
            {
              label: kt.stage,
              render: (center) => (
                <Select
                  aria-label={`${kt.stage}: ${center.department}`}
                  data={STAGE_OPTIONS}
                  value={center.stage || GENERAL}
                  allowDeselect={false}
                  disabled={save.isPending}
                  w={220}
                  onChange={(value) => {
                    if (!value || value === (center.stage || GENERAL)) return;
                    const stage = (value === GENERAL ? "" : value) as CostCenterStage;
                    save.mutate({ department: center.department, stage });
                  }}
                />
              ),
            },
          ]}
        />
      )}
    </Stack>
  );
}

function EmployerRateSection() {
  const queryClient = useQueryClient();
  const settings = useQuery({
    queryKey: personnelCostKeys.settings,
    queryFn: getPersonnelCostSettings,
  });
  const [draft, setDraft] = useState<string | null>(null);
  const saved = settings.data ? trimDecimal(settings.data.employer_rate).replace(".", ",") : "";
  const value = draft ?? saved;
  const save = useMutation({
    mutationFn: () => updatePersonnelCostSettings(normalizeDecimal(value)),
    onSuccess: (data) => {
      notifications.show({ color: "green", message: kt.employerRateSaved });
      queryClient.setQueryData(personnelCostKeys.settings, data);
      setDraft(null);
      void queryClient.invalidateQueries({ queryKey: personnelCostKeys.all });
    },
  });
  return (
    <Stack gap="xs">
      <Title order={4}>{kt.employerRate}</Title>
      <Text size="sm" c="dimmed" maw={860}>
        {kt.employerRateHint}
      </Text>
      {settings.isError && <ErrorAlert error={settings.error} />}
      <Group align="flex-end">
        <TextInput
          label={kt.employerRateLabel}
          inputMode="decimal"
          w={160}
          value={value}
          disabled={!settings.data}
          onChange={(event) => setDraft(event.currentTarget.value)}
        />
        <Button
          onClick={() => save.mutate()}
          loading={save.isPending}
          disabled={draft === null || !draft.trim() || draft === saved}
        >
          {kt.save}
        </Button>
      </Group>
      {save.isError && <ErrorAlert error={save.error} />}
    </Stack>
  );
}

function WageCell({ row }: { row: WageSummaryRow }) {
  if (row.current_wage) return <>{formatMoney(row.current_wage)}</>;
  return (
    <Text span size="sm" c={row.history.length ? "dimmed" : "orange"}>
      {row.history.length ? kt.futureWage : kt.noWage}
    </Text>
  );
}

/** Personel ve güncel ücretleri (ayrılanlar isteğe bağlı); ücret ekleme, geçmiş ve kaldırma;
 * birim ve işveren payı ayarları. */
export function WagesPanel() {
  const [params, setParams] = useSearchParams();
  const includeFormer = params.get("ayrilanlar") === "1";
  const summary = useQuery({
    queryKey: personnelCostKeys.wageList(includeFormer),
    queryFn: () => getWageSummary(includeFormer),
  });
  const [adding, setAdding] = useState<number | null>(null);
  const [viewing, setViewing] = useState<number | null>(null);
  const [listFor, setListFor] = useState(includeFormer);
  // Liste değişince (anahtar ya da geri tuşu) açık pencere kapanır; sonra kendiliğinden açılmaz.
  if (listFor !== includeFormer) {
    setListFor(includeFormer);
    setAdding(null);
    setViewing(null);
  }
  const rows = summary.data ?? [];
  // Pencere güncel veriyi göstersin diye kişi kimliği tutulur.
  const find = (id: number | null) => rows.find((row) => row.employee.id === id);
  const added = find(adding);
  const viewed = find(viewing);
  // Kişi listeden çıktıysa (yenilemeden sonra) pencere durumu da temizlenir.
  if (summary.data && adding !== null && !added) setAdding(null);
  if (summary.data && viewing !== null && !viewed) setViewing(null);
  return (
    <Stack>
      <Group justify="space-between" align="flex-start" wrap="wrap">
        <Text size="sm" c="dimmed" maw={860}>
          {kt.wagesHint}
        </Text>
        <Switch
          label={kt.showFormer}
          checked={includeFormer}
          onChange={(event) => setParams(event.currentTarget.checked ? { ayrilanlar: "1" } : {})}
        />
      </Group>
      {summary.isError && <ErrorAlert error={summary.error} />}
      {summary.isLoading ? (
        <Loader />
      ) : (
        <ReportTable
          rows={rows}
          rowKey={(row) => String(row.employee.id)}
          minWidth={900}
          cells={[
            // Sicil no, tutar ve tarih bölünmez; ad ve birim gerekirse alt satıra geçer.
            {
              label: kt.employeeNo,
              render: (row) => <span style={NO_WRAP}>{row.employee.employee_no}</span>,
            },
            {
              label: kt.fullName,
              render: (row) => (
                <Group gap={6}>
                  <span>{row.employee.full_name}</span>
                  <LeftBadge date={row.employee.termination_date} />
                </Group>
              ),
            },
            { label: kt.department, render: (row) => row.employee.department },
            {
              label: kt.stage,
              render: (row) => <span style={NO_WRAP}>{stageLabel(row.stage)}</span>,
            },
            {
              label: kt.currentWage,
              right: true,
              render: (row) => (
                <span style={NO_WRAP}>
                  <WageCell row={row} />
                </span>
              ),
            },
            {
              label: kt.validFrom,
              render: (row) => <span style={NO_WRAP}>{formatDate(row.current_valid_from)}</span>,
            },
            {
              label: "",
              render: (row) => (
                <Group gap="xs" justify="flex-end" wrap="nowrap">
                  <Button
                    size="xs"
                    variant="light"
                    leftSection={<IconPlus size={14} />}
                    aria-label={`${kt.addWage}: ${row.employee.full_name}`}
                    onClick={() => setAdding(row.employee.id)}
                  >
                    {kt.addWage}
                  </Button>
                  <Button
                    size="xs"
                    variant="subtle"
                    disabled={row.history.length === 0}
                    aria-label={`${kt.history(row.history.length)}: ${row.employee.full_name}`}
                    onClick={() => setViewing(row.employee.id)}
                  >
                    {kt.history(row.history.length)}
                  </Button>
                </Group>
              ),
            },
          ]}
        />
      )}
      <CostCentersSection />
      <EmployerRateSection />
      {added && <WageModal row={added} onClose={() => setAdding(null)} />}
      {viewed && <WageHistoryModal row={viewed} onClose={() => setViewing(null)} />}
    </Stack>
  );
}
