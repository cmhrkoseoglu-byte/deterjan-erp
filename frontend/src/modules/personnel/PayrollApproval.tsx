// Bordro onayı (Personel > Bordro, 4. adım): durum rozeti, onay penceresi (denetimler kişi adlarıyla,
// "okudum" işaretleri, ödeme tarihi), ödeme tarihi düzeltmesi, onay geçmişi ve yeniden açılan ayda
// kartı değişen kişiler (docs/DECISIONS.md "4. adım kararları").
import {
  Alert,
  Anchor,
  Badge,
  Button,
  Checkbox,
  Group,
  Modal,
  Paper,
  SimpleGrid,
  Stack,
  Text,
  TextInput,
  Textarea,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconAlertTriangle, IconInfoCircle, IconLock } from "@tabler/icons-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { attendanceKeys } from "../../api/attendance";
import { personnelCostKeys } from "../../api/costing";
import {
  approvePayroll,
  payrollExcelUrl,
  payrollKeys,
  payslipsPdfUrl,
  registerPdfUrl,
  setFollowCard,
  setPaymentDate,
  type CardChange,
  type PayrollApproval,
  type PayrollGate,
  type PayrollMonth,
} from "../../api/payroll";
import { formatDate, formatDateTime, formatMoney } from "../../i18n/format";
import { ErrorAlert } from "../costing/ReportTable";
import { gateLabel, paymentBounds } from "./payrollFormat";
import { pa, pn, py } from "./strings";

const NAMES_SHOWN = 5;
function gatePeople(gate: PayrollGate): string {
  const names = gate.employees.slice(0, NAMES_SHOWN).map((person) => person.full_name);
  return pa.people(names, gate.employees.length - names.length);
}

/** "Okudum" işaretinin anahtarı: denetim ve kişileri. Kişiler değişince (hesap yenilendi) işaret
 * kalkar; yeni kişi okunmadan onaylanmaz. */
function tickKey(gate: PayrollGate): string {
  return `${gate.code}:${gate.employees.map((person) => person.id).join(",")}`;
}

function GateLine({ gate }: { gate: PayrollGate }) {
  return (
    <Text size="sm">
      <Text span fw={600}>
        {gateLabel(gate.code)}
      </Text>
      {gate.employees.length > 0 && `: ${gatePeople(gate)}`}
    </Text>
  );
}

/** Ayın bordro durumu: onaylı (numara, ödeme tarihi) ya da taslak. */
export function PayrollStatusBadge({ payroll }: { payroll: PayrollMonth }) {
  const state = payroll.payroll;
  if (state.approved && state.approval)
    return (
      <Badge color="teal" leftSection={<IconLock size={12} />} tt="none">
        {pa.statusApproved(state.number, formatDate(state.approval.payment_date))}
      </Badge>
    );
  if (!payroll.net) return null;
  return (
    <Badge color="gray" variant="light" tt="none">
      {pa.statusDraft}
    </Badge>
  );
}

function refreshAll(queryClient: ReturnType<typeof useQueryClient>) {
  void queryClient.invalidateQueries({ queryKey: payrollKeys.all });
  void queryClient.invalidateQueries({ queryKey: personnelCostKeys.all });
  void queryClient.invalidateQueries({ queryKey: attendanceKeys.all });
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <Paper withBorder p="xs" radius="md">
      <Text size="xs" c="dimmed">
        {label}
      </Text>
      <Text fw={600} size="sm">
        {value}
      </Text>
    </Paper>
  );
}

/** Onay penceresi: toplamlar, denetimler (engelleyen, "okudum" istenen, bilgi), ödeme tarihi. */
export function ApproveModal({ payroll, onClose }: { payroll: PayrollMonth; onClose: () => void }) {
  const queryClient = useQueryClient();
  const state = payroll.payroll;
  const gates = state.gates ?? [];
  const blocking = gates.filter((gate) => gate.level === "block");
  const acknowledge = gates.filter((gate) => gate.level === "acknowledge");
  const notices = gates.filter((gate) => gate.level === "notice");
  const [read, setRead] = useState<string[]>([]);
  const [paymentDate, setPaymentDateValue] = useState("");
  const bounds = paymentBounds(payroll.year, payroll.month);
  const outOfRange =
    paymentDate !== "" && (paymentDate < bounds.first || paymentDate > bounds.last);
  const late = paymentDate !== "" && !outOfRange && paymentDate > bounds.late;
  const unread = acknowledge.some((gate) => !read.includes(tickKey(gate)));
  const approve = useMutation({
    mutationFn: () =>
      approvePayroll(payroll.year, payroll.month, {
        payment_date: paymentDate,
        fingerprint: state.fingerprint ?? "",
        acknowledged: acknowledge
          .filter((gate) => read.includes(tickKey(gate)))
          .map((gate) => gate.code),
      }),
    onSuccess: (run) => {
      notifications.show({
        color: "green",
        message: pa.approved(payroll.period_label, run.number),
      });
      refreshAll(queryClient);
    },
    // Hesap değiştiyse ya da denetim kaldıysa yenilenen ay pencereye gelir.
    onError: () => refreshAll(queryClient),
  });
  const close = () => {
    if (!approve.isPending) onClose();
  };
  const { totals } = payroll;
  return (
    <Modal
      opened
      onClose={close}
      title={pa.approveTitle(payroll.period_label)}
      size="lg"
      closeOnClickOutside={false}
      closeOnEscape={!approve.isPending}
      withCloseButton={!approve.isPending}
    >
      <Stack>
        <Text size="sm">{pa.approveIntro}</Text>
        <Text size="sm" c="dimmed">
          {pa.totalsPeople(totals.employee_count - totals.external_count, totals.external_count)}
        </Text>
        <SimpleGrid cols={{ base: 2, sm: 4 }}>
          <Stat label={py.grossTotal} value={formatMoney(totals.gross_total, "TL")} />
          <Stat label={pn.statNet} value={formatMoney(totals.net_pay, "TL")} />
          <Stat label={pn.statPayable} value={formatMoney(totals.payable, "TL")} />
          <Stat label={py.totalCost} value={formatMoney(totals.employer_cost, "TL")} />
        </SimpleGrid>
        {blocking.length > 0 && (
          <Alert
            color="red"
            variant="light"
            icon={<IconAlertTriangle size={18} />}
            title={pa.blockingTitle}
          >
            <Stack gap={4}>
              {blocking.map((gate) => (
                <GateLine key={gate.code} gate={gate} />
              ))}
            </Stack>
          </Alert>
        )}
        {acknowledge.length > 0 && (
          <Alert color="yellow" variant="light" title={pa.acknowledgeTitle}>
            <Stack gap={6}>
              {acknowledge.map((gate) => {
                const key = tickKey(gate);
                return (
                  <Checkbox
                    key={gate.code}
                    checked={read.includes(key)}
                    disabled={approve.isPending}
                    onChange={(event) => {
                      const checked = event.currentTarget.checked;
                      setRead((current) =>
                        checked ? [...current, key] : current.filter((item) => item !== key),
                      );
                    }}
                    label={
                      <Text span size="sm" fw={600}>
                        {`${pa.acknowledge}: ${gateLabel(gate.code)}`}
                      </Text>
                    }
                    // Okunması istenen kişilerin hepsi yazılır (kısaltılmaz); ekran okuyucu kutuyla
                    // birlikte okur.
                    aria-describedby={`payroll-ack-${gate.code}`}
                    description={
                      <span id={`payroll-ack-${gate.code}`}>
                        {gate.employees.map((person) => person.full_name).join(", ")}
                      </span>
                    }
                  />
                );
              })}
            </Stack>
          </Alert>
        )}
        {notices.length > 0 && (
          <Alert
            color="blue"
            variant="light"
            icon={<IconInfoCircle size={18} />}
            title={pa.noticeTitle}
          >
            <Stack gap={4}>
              {notices.map((gate) => (
                <GateLine key={gate.code} gate={gate} />
              ))}
            </Stack>
          </Alert>
        )}
        {state.card_changes.length > 0 && (
          <Alert
            color="blue"
            variant="light"
            icon={<IconInfoCircle size={18} />}
            title={pa.cardChangesTitle}
          >
            <Stack gap={4}>
              <Text size="sm">{pa.cardChangesApproveHint}</Text>
              {state.card_changes.map((change) => (
                <div key={change.employee}>
                  <Text size="sm">
                    {pa.cardChange(
                      change.full_name,
                      pa.flags(change.approved_external, change.approved_bes),
                      pa.flags(change.card_external, change.card_bes),
                    )}
                    {change.following && (
                      <Badge component="span" ml={6} size="xs" variant="light" tt="none">
                        {pa.followingBadge}
                      </Badge>
                    )}
                  </Text>
                  {/* Onayda saklanacak hal (sunucudan): kartı izleyende kartınki, diğerinde
                      onaydaki; girilmiş mali müşavir rakamı kişiyi mali müşavirde tutar. */}
                  <Text size="xs" c="dimmed">
                    {pa.storedAs(pa.flags(change.stored_external, change.stored_bes))}
                  </Text>
                  {change.figure_keeps_external && (
                    <Text size="xs" c="orange">
                      {pa.figureKeepsExternal}
                    </Text>
                  )}
                </div>
              ))}
            </Stack>
          </Alert>
        )}
        <TextInput
          label={pa.paymentDate}
          description={pa.paymentDateHelp}
          type="date"
          withAsterisk
          min={bounds.first}
          max={bounds.last}
          value={paymentDate}
          disabled={approve.isPending}
          error={
            outOfRange
              ? pa.paymentDateRange(formatDate(bounds.first), formatDate(bounds.last))
              : undefined
          }
          onChange={(event) => setPaymentDateValue(event.currentTarget.value)}
        />
        {late && (
          <Text size="sm" c="orange">
            {pa.paymentDateLate}
          </Text>
        )}
        {/* Red durumunda ay yenilenir: denetimler yukarıda yeni haliyle görünür. */}
        {approve.isError && <ErrorAlert error={approve.error} />}
        <Group justify="flex-end">
          <Button variant="default" onClick={close} disabled={approve.isPending}>
            {pn.cancel}
          </Button>
          <Button
            leftSection={<IconLock size={16} />}
            loading={approve.isPending}
            disabled={
              blocking.length > 0 ||
              unread ||
              !paymentDate ||
              outOfRange ||
              state.fingerprint === null
            }
            onClick={() => approve.mutate(undefined, { onSuccess: onClose })}
          >
            {pa.approveConfirm}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

/** Onaylı bordronun ödeme tarihini gerekçeyle düzeltme (tutarlar değişmez). */
export function PaymentDateModal({
  payroll,
  onClose,
}: {
  payroll: PayrollMonth;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const current = payroll.payroll.approval?.payment_date ?? "";
  const [paymentDate, setPaymentDateValue] = useState(current);
  const [reason, setReason] = useState("");
  const bounds = paymentBounds(payroll.year, payroll.month);
  const outOfRange =
    paymentDate !== "" && (paymentDate < bounds.first || paymentDate > bounds.last);
  const save = useMutation({
    mutationFn: () =>
      setPaymentDate(payroll.year, payroll.month, {
        payment_date: paymentDate,
        reason: reason.trim(),
      }),
    onSuccess: () => {
      notifications.show({ color: "green", message: pa.paymentFixed });
      refreshAll(queryClient);
    },
    // Ay başka biri tarafından açıldıysa sayfa yeni durumu gösterir.
    onError: () => refreshAll(queryClient),
  });
  const late =
    paymentDate !== "" && paymentDate !== current && !outOfRange && paymentDate > bounds.late;
  const close = () => {
    if (!save.isPending) onClose();
  };
  return (
    <Modal
      opened
      onClose={close}
      title={pa.paymentFixTitle(payroll.period_label)}
      closeOnClickOutside={false}
      closeOnEscape={!save.isPending}
      withCloseButton={!save.isPending}
    >
      <Stack>
        <Text size="sm">{pa.paymentFixIntro}</Text>
        <TextInput
          label={pa.paymentDate}
          type="date"
          withAsterisk
          min={bounds.first}
          max={bounds.last}
          value={paymentDate}
          disabled={save.isPending}
          error={
            outOfRange
              ? pa.paymentDateRange(formatDate(bounds.first), formatDate(bounds.last))
              : undefined
          }
          onChange={(event) => setPaymentDateValue(event.currentTarget.value)}
        />
        {late && (
          <Text size="sm" c="orange">
            {pa.paymentDateLate}
          </Text>
        )}
        <Textarea
          label={pa.paymentFixReason}
          withAsterisk
          autosize
          minRows={2}
          maxLength={500}
          value={reason}
          disabled={save.isPending}
          onChange={(event) => setReason(event.currentTarget.value)}
        />
        {save.isError && <ErrorAlert error={save.error} />}
        <Group justify="flex-end">
          <Button variant="default" onClick={close} disabled={save.isPending}>
            {pn.cancel}
          </Button>
          <Button
            loading={save.isPending}
            disabled={!paymentDate || outOfRange || !reason.trim() || paymentDate === current}
            onClick={() => save.mutate(undefined, { onSuccess: onClose })}
          >
            {pn.save}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

function ApprovalOutputs({
  payroll,
  approval,
  superseded,
}: {
  payroll: PayrollMonth;
  approval: number;
  superseded: boolean;
}) {
  const { year, month } = payroll;
  const links = [
    { label: pn.registerPdf, href: registerPdfUrl(year, month, approval), tab: true },
    { label: pa.payslips, href: payslipsPdfUrl(year, month, { approval }), tab: true },
    { label: py.excel, href: payrollExcelUrl(year, month, approval), tab: false },
  ];
  return (
    <Group gap="sm">
      {links.map((link) => (
        <Anchor
          key={link.label}
          href={link.href}
          target={link.tab ? "_blank" : undefined}
          rel={link.tab ? "noopener" : undefined}
          size="sm"
          aria-label={pa.outputLink(link.label, approval, superseded)}
        >
          {link.label}
        </Anchor>
      ))}
    </Group>
  );
}

/** Ayın onayları (yeniden açılanlar dahil) ve her onayın çıktıları. */
export function HistoryModal({ payroll, onClose }: { payroll: PayrollMonth; onClose: () => void }) {
  const history: PayrollApproval[] = [...payroll.payroll.history].reverse();
  return (
    <Modal opened onClose={onClose} title={pa.historyTitle(payroll.period_label)} size="lg">
      <Stack>
        {history.map((approval) => {
          const superseded = approval.reopened_at !== null;
          return (
            <Paper key={approval.sequence} withBorder p="sm" radius="md">
              <Stack gap={4}>
                <Group gap="xs">
                  <Text size="sm" fw={600}>
                    {pa.historyLine(
                      approval.sequence,
                      approval.approved_by_name ?? "—",
                      formatDateTime(approval.approved_at),
                      formatDate(approval.payment_date),
                    )}
                  </Text>
                  <Badge color={superseded ? "gray" : "teal"} variant="light" size="sm" tt="none">
                    {superseded ? pa.historySuperseded : pa.historyCurrent}
                  </Badge>
                </Group>
                <Text size="sm" c="dimmed">
                  {pa.historyTotals(
                    formatMoney(approval.net_pay, "TL"),
                    formatMoney(approval.payable, "TL"),
                    formatMoney(approval.employer_cost, "TL"),
                  )}
                </Text>
                {superseded && (
                  <Text size="sm">
                    {pa.historyReopened(
                      approval.reopened_by_name ?? "—",
                      formatDateTime(approval.reopened_at),
                      approval.reopen_reason,
                    )}
                  </Text>
                )}
                <ApprovalOutputs
                  payroll={payroll}
                  approval={approval.sequence}
                  superseded={superseded}
                />
              </Stack>
            </Paper>
          );
        })}
      </Stack>
    </Modal>
  );
}

/** Yeniden açılan ayda kartı onaydan sonra değişen kişiler: onaydaki işaretlerle hesaplanır;
 * kartın bugünkü işaretlerine geçirmek ayrıca seçilir. */
export function CardChanges({ payroll }: { payroll: PayrollMonth }) {
  const queryClient = useQueryClient();
  const follow = useMutation({
    mutationFn: (change: CardChange) =>
      setFollowCard(payroll.year, payroll.month, {
        employee: change.employee,
        follow: !change.following,
      }),
    onSuccess: (_, change) => {
      notifications.show({
        color: "green",
        message: change.following ? pa.unfollowed(change.full_name) : pa.followed(change.full_name),
      });
      refreshAll(queryClient);
    },
    // Ay başka biri tarafından onaylandıysa sayfa yeni durumu gösterir.
    onError: () => refreshAll(queryClient),
  });
  const changes = payroll.payroll.card_changes;
  if (!changes.length) return null;
  return (
    <Alert color="yellow" variant="light" title={pa.cardChangesTitle}>
      <Stack gap={6}>
        <Text size="sm">{pa.cardChangesHint}</Text>
        {changes.map((change) => (
          <Group key={change.employee} justify="space-between" gap="xs" wrap="nowrap">
            {/* Metin sarılır, düğme küçülmez (dar ekranda etiketi kırpılmasın). */}
            <div style={{ flex: 1, minWidth: 0 }}>
              <Text size="sm">
                {pa.cardChange(
                  change.full_name,
                  pa.flags(change.approved_external, change.approved_bes),
                  pa.flags(change.card_external, change.card_bes),
                )}
                {change.following && (
                  <Badge component="span" ml={6} size="xs" variant="light" tt="none">
                    {pa.followingBadge}
                  </Badge>
                )}
              </Text>
              {change.figure_keeps_external && (
                <Text size="xs" c="orange">
                  {pa.figureKeepsExternal}
                </Text>
              )}
            </div>
            <div style={{ flexShrink: 0, whiteSpace: "nowrap" }}>
              <Button
                size="compact-xs"
                variant="light"
                loading={follow.isPending && follow.variables?.employee === change.employee}
                disabled={follow.isPending}
                aria-label={`${change.following ? pa.unfollow : pa.follow}: ${change.full_name}`}
                onClick={() => follow.mutate(change)}
              >
                {change.following ? pa.unfollow : pa.follow}
              </Button>
            </div>
          </Group>
        ))}
        {follow.isError && <ErrorAlert error={follow.error} />}
      </Stack>
    </Alert>
  );
}
