// Personel > Ücretler: brüt aylık ücretler (geçerlilik tarihli). Ücretler kişisel veridir
// (docs/KVKK.md); yalnızca yönetim ve admin görür. 2026-11-01'de Maliyet'ten taşındı; birimlerin
// maliyet aşaması ve işveren payı Maliyet > Personel maliyeti'nde kaldı.
import {
  Alert,
  Badge,
  Button,
  Group,
  Loader,
  Modal,
  Stack,
  Switch,
  Text,
  Textarea,
  TextInput,
  Title,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconInfoCircle, IconPlus } from "@tabler/icons-react";
import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { personnelCostKeys } from "../../api/costing";
import {
  addWage,
  getWageSummary,
  removeWage,
  wageKeys,
  type EmployeeWage,
  type WageSummaryRow,
} from "../../api/wages";
import { formatDate, formatDateTime, formatMoney } from "../../i18n/format";
import { currentMonthStart, parseMoney, previousMonthStart } from "../costing/personnelCostFormat";
import { ErrorAlert, ReportTable } from "../costing/ReportTable";
import { PersonnelTabs } from "./PersonnelTabs";
import { pe, WAGES_BASE, wt } from "./strings";

// Ücret 2000'den önce başlayamaz (backend sınırı).
const EARLIEST_WAGE_DATE = "2000-01-01";
const NO_WRAP = { whiteSpace: "nowrap" } as const;

/** Ücret değişince ücret listeleri ve personel maliyeti raporu yeniden okunur. */
function refresh(queryClient: QueryClient) {
  for (const queryKey of [wageKeys.all, personnelCostKeys.all])
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
      {wt.leftOn(formatDate(date))}
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
      notifications.show({ color: "green", message: wt.wageSaved });
      refresh(queryClient);
    },
  });
  // İstek sürerken pencere kapanmaz (geç gelen yanıt başka bir pencereyi kapatmasın).
  const close = () => {
    if (!save.isPending) onClose();
  };
  let amountHelp: string | undefined;
  if (amount) amountHelp = wt.amountPreview(formatMoney(amount, "TL"));
  return (
    <Modal
      opened
      onClose={close}
      title={wt.wageTitle(row.employee.full_name)}
      closeOnClickOutside={false}
      closeOnEscape={!save.isPending}
      withCloseButton={!save.isPending}
    >
      <Stack>
        {row.current_wage ? (
          <Text size="sm" c="dimmed">
            {wt.wageNow(formatMoney(row.current_wage, "TL"), formatDate(row.current_valid_from))}
          </Text>
        ) : (
          !row.history.length && (
            <Text size="sm" c="dimmed">
              {wt.firstWageHint(Boolean(row.employee.hire_date))}
            </Text>
          )
        )}
        <TextInput
          label={wt.grossMonthly}
          withAsterisk
          inputMode="decimal"
          value={draft.amount}
          description={amountHelp}
          inputWrapperOrder={["label", "input", "description", "error"]}
          error={draft.amount.trim() && amount === null && !typing ? wt.invalidAmount : undefined}
          onChange={(event) => {
            const value = event.currentTarget.value;
            setDraft((d) => ({ ...d, amount: value }));
          }}
        />
        <TextInput
          label={wt.validFrom}
          type="date"
          withAsterisk
          value={draft.valid_from}
          onChange={(event) => {
            const value = event.currentTarget.value;
            setDraft((d) => ({ ...d, valid_from: value }));
          }}
        />
        <TextInput
          label={wt.note}
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
            {wt.cancel}
          </Button>
          <Button
            onClick={() => save.mutate(undefined, { onSuccess: onClose })}
            loading={save.isPending}
            disabled={amount === null || !draft.valid_from}
          >
            {wt.save}
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
      notifications.show({ color: "green", message: wt.wageRemoved });
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
      title={wt.historyTitle(row.employee.full_name)}
      size="lg"
      closeOnClickOutside={false}
      closeOnEscape={!remove.isPending}
      withCloseButton={!remove.isPending}
    >
      {removing ? (
        <Stack>
          <Text size="sm">{wt.removeWageIntro}</Text>
          <Text size="sm" fw={600}>
            {label(removing)}
          </Text>
          <Textarea
            label={wt.removeReason}
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
              {wt.cancel}
            </Button>
            <Button
              color="red"
              onClick={() => remove.mutate(removing, { onSuccess: () => setRemoving(null) })}
              loading={remove.isPending}
              disabled={!reason.trim()}
            >
              {wt.removeWage}
            </Button>
          </Group>
        </Stack>
      ) : (
        <ReportTable
          rows={row.history}
          rowKey={(wage) => String(wage.id)}
          minWidth={560}
          cells={[
            { label: wt.validFrom, render: (wage) => formatDate(wage.valid_from) },
            {
              label: wt.grossMonthly,
              right: true,
              render: (wage) => formatMoney(wage.gross_monthly),
            },
            { label: wt.note, render: (wage) => wage.note },
            {
              label: wt.enteredBy,
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
                    aria-label={wt.removeWageLabel(
                      formatDate(wage.valid_from),
                      formatMoney(wage.gross_monthly, "TL"),
                    )}
                    onClick={() => {
                      setRemoving(wage);
                      setReason("");
                      remove.reset();
                    }}
                  >
                    {wt.removeWage}
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

function WageCell({ row }: { row: WageSummaryRow }) {
  if (row.current_wage) return <>{formatMoney(row.current_wage)}</>;
  return (
    <Text span size="sm" c={row.history.length ? "dimmed" : "orange"}>
      {row.history.length ? wt.futureWage : wt.noWage}
    </Text>
  );
}

/** Personel ve güncel ücretleri (ayrılanlar isteğe bağlı); ücret ekleme, geçmiş ve kaldırma. */
export function WagesPage() {
  const [params, setParams] = useSearchParams();
  const includeFormer = params.get("ayrilanlar") === "1";
  const summary = useQuery({
    queryKey: wageKeys.list(includeFormer),
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
      <Title order={2}>{pe.title}</Title>
      <PersonnelTabs active={WAGES_BASE} />
      <Group justify="space-between" align="flex-start" wrap="wrap">
        <Alert
          color="blue"
          variant="light"
          icon={<IconInfoCircle size={18} />}
          maw={860}
          style={{ flex: 1 }}
        >
          <Text size="sm">{wt.intro}</Text>
        </Alert>
        <Switch
          label={wt.showFormer}
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
          minWidth={820}
          cells={[
            // Sicil no, tutar ve tarih bölünmez; ad ve birim gerekirse alt satıra geçer.
            {
              label: wt.employeeNo,
              render: (row) => <span style={NO_WRAP}>{row.employee.employee_no}</span>,
            },
            {
              label: wt.fullName,
              render: (row) => (
                <Group gap={6}>
                  <span>{row.employee.full_name}</span>
                  <LeftBadge date={row.employee.termination_date} />
                </Group>
              ),
            },
            { label: wt.department, render: (row) => row.employee.department },
            {
              label: wt.currentWage,
              right: true,
              render: (row) => (
                <span style={NO_WRAP}>
                  <WageCell row={row} />
                </span>
              ),
            },
            {
              label: wt.validFrom,
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
                    aria-label={`${wt.addWage}: ${row.employee.full_name}`}
                    onClick={() => setAdding(row.employee.id)}
                  >
                    {wt.addWage}
                  </Button>
                  <Button
                    size="xs"
                    variant="subtle"
                    disabled={row.history.length === 0}
                    aria-label={`${wt.history(row.history.length)}: ${row.employee.full_name}`}
                    onClick={() => setViewing(row.employee.id)}
                  >
                    {wt.history(row.history.length)}
                  </Button>
                </Group>
              ),
            },
          ]}
        />
      )}
      {added && <WageModal row={added} onClose={() => setAdding(null)} />}
      {viewed && <WageHistoryModal row={viewed} onClose={() => setViewing(null)} />}
    </Stack>
  );
}
