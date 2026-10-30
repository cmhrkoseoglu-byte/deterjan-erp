// Maliyet > Personel maliyeti: brüt ücret ve puantajdan ayın personel maliyeti, aşama toplamları
// ve gerçekleşen işçilikten oran önerisi (docs/DECISIONS.md "Personel maliyeti").
import {
  ActionIcon,
  Alert,
  Anchor,
  Badge,
  Button,
  Group,
  List,
  Loader,
  Modal,
  Paper,
  SimpleGrid,
  Stack,
  Text,
  TextInput,
  Title,
  Tooltip,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import {
  IconAlertTriangle,
  IconChevronLeft,
  IconChevronRight,
  IconFileSpreadsheet,
  IconInfoCircle,
  IconLock,
} from "@tabler/icons-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  addLaborRateFromPersonnelCost,
  getPersonnelCost,
  personnelCostExcelUrl,
  personnelCostKeys,
  type CostStage,
  type PersonnelCostReport,
  type StageCost,
} from "../../api/costing";
import { formatDate, formatMoney, formatNumber } from "../../i18n/format";
import { COSTING_BASE } from "./config";
import {
  monthLabel,
  nextMonthStart,
  parseMonth,
  shiftMonth,
  stageLabel,
} from "./personnelCostFormat";
import { ErrorAlert, ReportTable } from "./ReportTable";
import { kt } from "./strings";

const money = (value: string) => formatMoney(value);

/** Üretim ya da dolum (genel giderin işçilik oranı olmaz). */
type RatedStage = StageCost & { stage: CostStage };
const isRated = (stage: StageCost): stage is RatedStage => stage.stage !== "";

/** Oran penceresi hangi ay ve aşama için açıldı (ay değişince pencere eski ayı göstermesin). */
interface Rating {
  year: number;
  month: number;
  stage: CostStage;
}

function Stat({
  label,
  value,
  strong = false,
}: {
  label: string;
  value: string;
  strong?: boolean;
}) {
  return (
    <Paper withBorder p="sm" radius="md">
      <Text size="xs" c="dimmed">
        {label}
      </Text>
      <Text fw={strong ? 700 : 600}>{value}</Text>
    </Paper>
  );
}

function AttendanceBadge({ report }: { report: PersonnelCostReport }) {
  if (report.attendance_approved)
    return (
      <Badge color="green" leftSection={<IconLock size={12} />}>
        {kt.attendanceApproved(report.attendance_number)}
      </Badge>
    );
  return (
    <Badge color="gray" variant="light">
      {kt.attendanceOpen}
    </Badge>
  );
}

/** Oran önerisi neden eklenemez; eklenebiliyorsa null. */
function rateBlocker(report: PersonnelCostReport, stage: StageCost): string | null {
  if (!report.attendance_approved) return kt.needsApproval;
  if (Number(stage.cost) <= 0) return kt.noStageCost;
  if (stage.suggested_rate !== null) return null;
  return stage.unconverted > 0 ? kt.noKg : kt.noProduction;
}

function KgCell({ stage }: { stage: StageCost }) {
  if (stage.kg === null) return null;
  return (
    <Group gap={4} justify="flex-end" wrap="nowrap">
      {stage.unconverted > 0 && (
        <Tooltip
          label={kt.unconverted(stage.unconverted)}
          multiline
          w={260}
          events={{ hover: true, focus: true, touch: true }}
        >
          <span tabIndex={0} role="img" aria-label={kt.unconverted(stage.unconverted)}>
            <IconAlertTriangle size={14} color="var(--mantine-color-orange-6)" />
          </span>
        </Tooltip>
      )}
      <span>{formatNumber(stage.kg)}</span>
    </Group>
  );
}

function ReportView({
  report,
  onRate,
}: {
  report: PersonnelCostReport;
  onRate: (stage: CostStage) => void;
}) {
  // Ücreti eksik ayrılan personel varsa ücretler sekmesi ayrılanlarla açılır.
  const formerMissing = report.rows.some((row) => row.missing_wage && !row.employee.is_active);
  return (
    <Stack>
      {!report.attendance_approved && (
        <Alert color="yellow" variant="light" icon={<IconInfoCircle size={18} />}>
          <Text size="sm">{kt.attendanceOpenHint}</Text>
        </Alert>
      )}
      {report.missing_wage_count > 0 && (
        <Alert color="orange" variant="light" icon={<IconAlertTriangle size={18} />}>
          <Group gap="xs" justify="space-between">
            <Text size="sm">{kt.missingWages(report.missing_wage_count)}</Text>
            <Anchor
              component={Link}
              to={`${COSTING_BASE}/ucretler${formerMissing ? "?ayrilanlar=1" : ""}`}
              size="sm"
            >
              {kt.goToWages}
            </Anchor>
          </Group>
        </Alert>
      )}
      <SimpleGrid cols={{ base: 2, sm: 4 }}>
        <Stat label={kt.totalPersonnelCost} value={formatMoney(report.total_cost, "TL")} strong />
        <Stat label={kt.grossSalary} value={formatMoney(report.gross_salary, "TL")} />
        <Stat label={kt.overtimePay} value={formatMoney(report.overtime_pay, "TL")} />
        <Stat
          label={kt.employerShare(formatNumber(report.employer_rate, 2))}
          value={formatMoney(report.employer_share, "TL")}
        />
      </SimpleGrid>
      <Title order={4}>{kt.stageCosts}</Title>
      <ReportTable
        rows={report.stages}
        rowKey={(r) => r.stage || "GENERAL"}
        cells={[
          { label: kt.stage, render: (r) => stageLabel(r.stage) },
          { label: kt.employeeCount, right: true, render: (r) => r.employee_count },
          { label: kt.cost, right: true, render: (r) => money(r.cost) },
          { label: kt.producedKg, right: true, render: (r) => <KgCell stage={r} /> },
          {
            label: kt.actualLabor,
            right: true,
            render: (r) => (
              <Text span size="sm" fw={600}>
                {formatNumber(r.suggested_rate)}
              </Text>
            ),
          },
          { label: kt.currentLabor, right: true, render: (r) => formatNumber(r.current_rate) },
          {
            label: "",
            render: (r) => {
              if (!isRated(r)) return null;
              const blocker = rateBlocker(report, r);
              // Neden yazıyla da görünür (dokunmatik ekranda ve klavyede ipucu açılmaz); onay
              // eksikliği zaten üstteki uyarıda yazar.
              const reason = blocker && blocker !== kt.needsApproval ? blocker : null;
              return (
                <Stack gap={2} align="flex-end">
                  <Tooltip label={blocker ?? ""} disabled={!blocker}>
                    <span>
                      <Button
                        size="xs"
                        variant="light"
                        disabled={blocker !== null}
                        onClick={() => onRate(r.stage)}
                        aria-label={`${kt.useAsRate}: ${stageLabel(r.stage)}`}
                      >
                        {kt.useAsRate}
                      </Button>
                    </span>
                  </Tooltip>
                  {reason && (
                    <Text size="xs" c="dimmed" ta="right" maw={240}>
                      {reason}
                    </Text>
                  )}
                </Stack>
              );
            },
          },
        ]}
      />
      <Title order={4}>{kt.employeeCosts}</Title>
      <ReportTable
        rows={report.rows}
        rowKey={(r) => String(r.employee.id)}
        nowrap
        cells={[
          { label: kt.employeeNo, render: (r) => r.employee.employee_no },
          {
            label: kt.fullName,
            render: (r) => (
              <Group gap={6} wrap="nowrap">
                <span>{r.employee.full_name}</span>
                {r.missing_wage && (
                  <Badge color="orange" variant="light" size="sm" tt="none">
                    {kt.missingWage}
                  </Badge>
                )}
                {r.employee.termination_date && (
                  <Badge color="gray" variant="light" size="sm" tt="none">
                    {kt.leftOn(formatDate(r.employee.termination_date))}
                  </Badge>
                )}
              </Group>
            ),
          },
          { label: kt.department, render: (r) => r.employee.department },
          { label: kt.stage, render: (r) => stageLabel(r.stage) },
          {
            label: kt.grossMonthly,
            right: true,
            render: (r) => (r.gross_monthly === null ? "" : money(r.gross_monthly)),
          },
          { label: kt.paidDays, right: true, render: (r) => r.paid_days },
          { label: kt.unpaidDays, right: true, render: (r) => r.unpaid_days || "" },
          {
            label: kt.overtimeHours,
            right: true,
            render: (r) => (Number(r.overtime_hours) ? formatNumber(r.overtime_hours) : ""),
          },
          { label: kt.grossSalary, right: true, render: (r) => money(r.gross_salary) },
          { label: kt.overtimePay, right: true, render: (r) => money(r.overtime_pay) },
          { label: kt.employerShareShort, right: true, render: (r) => money(r.employer_share) },
          {
            label: kt.totalCost,
            right: true,
            render: (r) => (
              <Text span size="sm" fw={600}>
                {money(r.total_cost)}
              </Text>
            ),
          },
        ]}
      />
    </Stack>
  );
}

function LaborRateModal({
  report,
  stage,
  onClose,
}: {
  report: PersonnelCostReport;
  stage: RatedStage;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [validFrom, setValidFrom] = useState(nextMonthStart(report.year, report.month));
  const save = useMutation({
    mutationFn: () =>
      addLaborRateFromPersonnelCost(report.year, report.month, {
        stage: stage.stage,
        valid_from: validFrom,
      }),
    onSuccess: () => {
      notifications.show({ color: "green", message: kt.laborRateAdded });
      void queryClient.invalidateQueries({ queryKey: ["costing", "rates"] });
      void queryClient.invalidateQueries({ queryKey: personnelCostKeys.all });
    },
  });
  // İstek sürerken pencere kapanmaz (geç gelen yanıt başka bir pencereyi kapatmasın).
  const close = () => {
    if (!save.isPending) onClose();
  };
  return (
    <Modal
      opened
      onClose={close}
      title={kt.laborRateTitle(stageLabel(stage.stage))}
      closeOnClickOutside={false}
      closeOnEscape={!save.isPending}
      withCloseButton={!save.isPending}
    >
      <Stack>
        <Text size="sm">
          {kt.laborRateIntro(
            monthLabel(report.year, report.month),
            formatMoney(stage.cost, "TL"),
            formatNumber(stage.kg),
          )}
        </Text>
        <SimpleGrid cols={2}>
          <Stat label={kt.actualLabor} value={formatNumber(stage.suggested_rate)} strong />
          <Stat label={kt.currentLabor} value={formatNumber(stage.current_rate) || "—"} />
        </SimpleGrid>
        {stage.missing_wage_count > 0 && (
          <Alert color="orange" variant="light" icon={<IconAlertTriangle size={18} />}>
            <Text size="sm">{kt.rateMissingWages(stage.missing_wage_count)}</Text>
          </Alert>
        )}
        {stage.unconverted > 0 && (
          <Alert color="orange" variant="light" icon={<IconAlertTriangle size={18} />}>
            <Text size="sm">{kt.rateUnconverted(stage.unconverted)}</Text>
          </Alert>
        )}
        <TextInput
          label={kt.validFrom}
          type="date"
          withAsterisk
          value={validFrom}
          description={kt.laborRateEffect}
          onChange={(event) => setValidFrom(event.currentTarget.value)}
        />
        {save.isError && <ErrorAlert error={save.error} />}
        <Group justify="flex-end">
          <Button variant="default" onClick={close} disabled={save.isPending}>
            {kt.cancel}
          </Button>
          <Button
            onClick={() => save.mutate(undefined, { onSuccess: onClose })}
            loading={save.isPending}
            disabled={!validFrom}
          >
            {kt.useAsRate}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

/** Ay seçici, puantaj durumu, özet, aşama ve kişi tabloları, Excel ve işçilik oranı önerisi. */
export function PersonnelCostPanel() {
  const [params, setParams] = useSearchParams();
  const { year, month } = parseMonth(params.get("ay"));
  const [rating, setRating] = useState<Rating | null>(null);
  const [rules, setRules] = useState(false);
  const query = useQuery({
    queryKey: personnelCostKeys.report(year, month),
    queryFn: () => getPersonnelCost(year, month),
  });
  const report = query.data;
  // Ay değişince (geri tuşu dahil) açık oran penceresi kapanır.
  if (rating && (rating.year !== year || rating.month !== month)) setRating(null);
  const rated =
    rating && report && rating.year === year && rating.month === month
      ? report.stages.filter(isRated).find((stage) => stage.stage === rating.stage)
      : undefined;
  return (
    <Stack>
      <Stack gap={4} maw={860}>
        <Text size="sm" c="dimmed">
          {kt.personnelLead}
        </Text>
        <Anchor
          component="button"
          type="button"
          size="sm"
          ta="left"
          aria-expanded={rules}
          onClick={() => setRules((open) => !open)}
        >
          {rules ? kt.rulesHide : kt.rulesShow}
        </Anchor>
        {rules && (
          <List size="sm" c="dimmed" spacing={2}>
            {kt.rules.map((rule) => (
              <List.Item key={rule}>{rule}</List.Item>
            ))}
          </List>
        )}
      </Stack>
      <Group justify="space-between" align="center" wrap="wrap">
        <Group gap="xs" wrap="wrap">
          <ActionIcon
            variant="default"
            aria-label={kt.previousMonth}
            onClick={() => setParams({ ay: shiftMonth(year, month, -1) })}
          >
            <IconChevronLeft size={16} />
          </ActionIcon>
          <Text fw={600} miw={120} ta="center">
            {monthLabel(year, month)}
          </Text>
          <ActionIcon
            variant="default"
            aria-label={kt.nextMonth}
            onClick={() => setParams({ ay: shiftMonth(year, month, 1) })}
          >
            <IconChevronRight size={16} />
          </ActionIcon>
          {report && <AttendanceBadge report={report} />}
        </Group>
        <Button
          component="a"
          href={personnelCostExcelUrl(year, month)}
          variant="default"
          leftSection={<IconFileSpreadsheet size={16} />}
        >
          {kt.excel}
        </Button>
      </Group>
      {query.isError && <ErrorAlert error={query.error} />}
      {query.isLoading && <Loader />}
      {report && (
        <ReportView report={report} onRate={(stage) => setRating({ year, month, stage })} />
      )}
      {rated && report && (
        <LaborRateModal
          key={`${year}-${month}-${rated.stage}`}
          report={report}
          stage={rated}
          onClose={() => setRating(null)}
        />
      )}
    </Stack>
  );
}
