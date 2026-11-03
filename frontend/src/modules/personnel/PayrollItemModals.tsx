// Ek ödeme ve kesinti pencereleri (Personel > Bordro): tek kalem, toplu ekleme, geçen aydan
// kopyalama. Kalem birlikte ödendiği ücretin bordro ayına girilir (docs/DECISIONS.md "Personel
// bordrosu"). Açıklama kişisel veri olabilir (icra dosyası); yalnızca yönetim görür.
import {
  Alert,
  Badge,
  Button,
  Checkbox,
  Group,
  Loader,
  Modal,
  MultiSelect,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconInfoCircle } from "@tabler/icons-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { personnelCostKeys } from "../../api/costing";
import {
  addPayrollItem,
  addPayrollItems,
  DESCRIBED_CATEGORIES,
  getBatchErrors,
  itemKind,
  listPayrollItems,
  payrollKeys,
  updatePayrollItem,
  type BatchErrorRow,
  type PayrollItemCategory,
  type PayrollItemInput,
  type PayrollItemRecord,
  type PayrollMonth,
  type PayrollRow,
} from "../../api/payroll";
import { formatMoney } from "../../i18n/format";
import { monthLabel, parseMoney, shiftMonth } from "../costing/personnelCostFormat";
import { ErrorAlert } from "../costing/ReportTable";
import { CATEGORY_LABELS, categoryOptions, isPastMonth, itemLabel } from "./payrollFormat";
import { pn, py } from "./strings";

function useRefresh() {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({ queryKey: payrollKeys.all });
    void queryClient.invalidateQueries({ queryKey: personnelCostKeys.all });
  };
}

/** Kalemin ipucu; nakit yemekte parametrelerdeki günlük SGK istisna sınırı (0 ise istisna yok). */
function CategoryHints({ category, mealLimit }: { category: string | null; mealLimit: string }) {
  if (category === "GARNISHMENT")
    return (
      <Text size="xs" c="dimmed">
        {pn.garnishmentHelp}
      </Text>
    );
  if (category === "MEAL")
    return Number(mealLimit) > 0 ? (
      <Text size="xs" c="dimmed">
        {pn.mealHelp(formatMoney(mealLimit))}
      </Text>
    ) : (
      <Text size="xs" c="orange">
        {pn.mealNoLimit}
      </Text>
    );
  return null;
}

/** Aynı kalem: kişi, kalem, tutar ve açıklama (geçen aydan kopyalamada bu ay zaten olanlar). */
function itemKey(item: PayrollItemRecord): string {
  return `${item.employee}|${item.category}|${Number(item.amount).toFixed(2)}|${item.description.trim()}`;
}

function BatchErrors({ rows, names }: { rows: BatchErrorRow[]; names: Map<number, string> }) {
  if (!rows.length) return null;
  return (
    <Alert color="red" variant="light">
      <Stack gap={2}>
        {rows.map((row) => (
          <Text key={row.index} size="sm">
            {pn.rowError(names.get(row.employee ?? 0) ?? `#${row.index + 1}`, row.detail)}
          </Text>
        ))}
      </Stack>
    </Alert>
  );
}

/** Tek kalem: yeni (kişi seçilir) ya da düzeltme (kişi, ay ve tür değişmez). */
export function PayrollItemModal({
  payroll,
  people,
  item,
  employeeId,
  onClose,
}: {
  payroll: PayrollMonth;
  /** Bu ay bordrosu ERP'de hesaplanan kişiler. */
  people: PayrollRow[];
  item?: PayrollItemRecord;
  employeeId?: number;
  onClose: () => void;
}) {
  const refresh = useRefresh();
  const [employee, setEmployee] = useState<string | null>(
    item ? String(item.employee) : employeeId ? String(employeeId) : null,
  );
  const [category, setCategory] = useState<string | null>(item?.category ?? null);
  const [description, setDescription] = useState(item?.description ?? "");
  const [amount, setAmount] = useState(item ? formatMoney(item.amount) : "");
  const value = parseMoney(amount);
  const described =
    category !== null && DESCRIBED_CATEGORIES.includes(category as PayrollItemCategory);
  const save = useMutation({
    mutationFn: () => {
      const payload = {
        category: category as PayrollItemCategory,
        description: description.trim(),
        amount: value ?? "",
      };
      if (item) return updatePayrollItem(item.id, payload);
      return addPayrollItem(payroll.year, payroll.month, {
        ...payload,
        employee: Number(employee),
      });
    },
    onSuccess: () => {
      notifications.show({ color: "green", message: pn.itemSaved });
      refresh();
    },
  });
  const close = () => {
    if (!save.isPending) onClose();
  };
  const invalid = !employee || !category || value === null || (described && !description.trim());
  return (
    <Modal
      opened
      onClose={close}
      title={item ? pn.itemTitleEdit(item.employee_name) : pn.itemTitleNew}
      closeOnClickOutside={false}
      closeOnEscape={!save.isPending}
      withCloseButton={!save.isPending}
    >
      <Stack>
        <Text size="sm" c="dimmed">
          {payroll.period_label}
        </Text>
        {item ? (
          <TextInput label={pn.itemPerson} value={item.employee_name} readOnly disabled />
        ) : (
          <Select
            label={pn.itemPerson}
            withAsterisk
            searchable
            disabled={save.isPending}
            data={people.map((row) => ({
              value: String(row.employee.id),
              label: `${row.employee.full_name}${row.employee.employee_no ? ` (${row.employee.employee_no})` : ""}`,
            }))}
            value={employee}
            onChange={setEmployee}
          />
        )}
        <Select
          label={pn.itemCategory}
          withAsterisk
          disabled={save.isPending}
          data={categoryOptions(item ? itemKind(item.category) : undefined)}
          value={category}
          onChange={setCategory}
          description={item ? pn.itemKindLocked : undefined}
        />
        <CategoryHints
          category={category}
          mealLimit={payroll.parameters.values.meal_exemption_daily}
        />
        <TextInput
          label={pn.itemDescription}
          withAsterisk={described}
          maxLength={100}
          description={pn.descriptionHelp}
          value={description}
          disabled={save.isPending}
          error={described && !description.trim() ? pn.descriptionRequired : undefined}
          onChange={(event) => setDescription(event.currentTarget.value)}
        />
        <TextInput
          label={pn.itemAmount}
          withAsterisk
          inputMode="decimal"
          value={amount}
          disabled={save.isPending}
          error={amount.trim() && value === null ? py.invalidAmount : undefined}
          onChange={(event) => setAmount(event.currentTarget.value)}
        />
        {isPastMonth(payroll.year, payroll.month) && (
          <Alert color="blue" variant="light" icon={<IconInfoCircle size={18} />}>
            <Text size="sm">{pn.laterMonthsHint}</Text>
          </Alert>
        )}
        {save.isError && <ErrorAlert error={save.error} />}
        <Group justify="flex-end">
          <Button variant="default" onClick={close} disabled={save.isPending}>
            {pn.cancel}
          </Button>
          <Button
            onClick={() => save.mutate(undefined, { onSuccess: onClose })}
            loading={save.isPending}
            disabled={invalid}
          >
            {pn.save}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

/** Aynı kalemi seçili kişilere ekler (hepsi ya da hiçbiri). */
export function BulkItemsModal({
  payroll,
  people,
  onClose,
}: {
  payroll: PayrollMonth;
  people: PayrollRow[];
  onClose: () => void;
}) {
  const refresh = useRefresh();
  const [category, setCategory] = useState<string | null>(null);
  const [description, setDescription] = useState("");
  const [amount, setAmount] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const value = parseMoney(amount);
  const described =
    category !== null && DESCRIBED_CATEGORIES.includes(category as PayrollItemCategory);
  const names = new Map(people.map((row) => [row.employee.id, row.employee.full_name]));
  const save = useMutation({
    mutationFn: () =>
      addPayrollItems(
        payroll.year,
        payroll.month,
        selected.map((id): PayrollItemInput => ({
          employee: Number(id),
          category: category as PayrollItemCategory,
          description: description.trim(),
          amount: value ?? "",
        })),
      ),
    onSuccess: (items) => {
      notifications.show({ color: "green", message: pn.itemsSaved(items.length) });
      refresh();
    },
  });
  const close = () => {
    if (!save.isPending) onClose();
  };
  const errors = save.isError ? getBatchErrors(save.error) : [];
  const invalid =
    !category || value === null || !selected.length || (described && !description.trim());
  return (
    <Modal
      opened
      onClose={close}
      title={pn.bulkTitle}
      size="lg"
      closeOnClickOutside={false}
      closeOnEscape={!save.isPending}
      withCloseButton={!save.isPending}
    >
      <Stack>
        <Text size="sm" c="dimmed">
          {pn.bulkIntro} · {payroll.period_label}
        </Text>
        <Select
          label={pn.itemCategory}
          withAsterisk
          data={categoryOptions()}
          value={category}
          onChange={setCategory}
          disabled={save.isPending}
        />
        <CategoryHints
          category={category}
          mealLimit={payroll.parameters.values.meal_exemption_daily}
        />
        <TextInput
          label={pn.itemDescription}
          withAsterisk={described}
          maxLength={100}
          description={pn.descriptionHelp}
          value={description}
          disabled={save.isPending}
          error={described && !description.trim() ? pn.descriptionRequired : undefined}
          onChange={(event) => setDescription(event.currentTarget.value)}
        />
        <TextInput
          label={pn.itemAmount}
          withAsterisk
          inputMode="decimal"
          value={amount}
          disabled={save.isPending}
          error={amount.trim() && value === null ? py.invalidAmount : undefined}
          onChange={(event) => setAmount(event.currentTarget.value)}
        />
        <MultiSelect
          label={pn.bulkPeople}
          withAsterisk
          searchable
          data={people.map((row) => ({
            value: String(row.employee.id),
            label: `${row.employee.full_name} · ${row.employee.department}`,
          }))}
          value={selected}
          onChange={setSelected}
          disabled={save.isPending}
        />
        <Group>
          <Button
            variant="subtle"
            size="compact-sm"
            onClick={() => setSelected(people.map((row) => String(row.employee.id)))}
            disabled={save.isPending}
          >
            {pn.selectAll}
          </Button>
        </Group>
        {errors.length > 0 ? (
          <BatchErrors rows={errors} names={names} />
        ) : (
          save.isError && <ErrorAlert error={save.error} />
        )}
        <Group justify="flex-end">
          <Button variant="default" onClick={close} disabled={save.isPending}>
            {pn.cancel}
          </Button>
          <Button
            onClick={() => save.mutate(undefined, { onSuccess: onClose })}
            loading={save.isPending}
            disabled={invalid}
          >
            {pn.save}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

/** Geçen ayın kalemlerini işaretli listeyle bu aya ekler (her ay gözden geçirilerek). */
export function CopyItemsModal({
  payroll,
  people,
  onClose,
}: {
  payroll: PayrollMonth;
  people: PayrollRow[];
  onClose: () => void;
}) {
  const refresh = useRefresh();
  const [fromYear, fromMonth] = shiftMonth(payroll.year, payroll.month, -1).split("-").map(Number);
  // İki liste de her açılışta yeniden okunur (önbellekteki eski liste kopyalanmasın: geçen ay kalem
  // kaldırılmış ya da bu ay kalem eklenmiş olabilir).
  const previous = useQuery({
    queryKey: payrollKeys.items({ year: fromYear, month: fromMonth, copy: true }),
    queryFn: () =>
      listPayrollItems({ year: fromYear, month: fromMonth, is_active: true, page_size: 500 }),
    refetchOnMount: "always",
  });
  // Bu ayın kalemleri her açılışta yeniden okunur (başka sekmede ya da kişide eklenmiş olabilir).
  const current = useQuery({
    queryKey: payrollKeys.items({ year: payroll.year, month: payroll.month, copyTarget: true }),
    queryFn: () =>
      listPayrollItems({
        year: payroll.year,
        month: payroll.month,
        is_active: true,
        page_size: 500,
      }),
    refetchOnMount: "always",
  });
  const computed = new Set(people.map((row) => row.employee.id));
  const names = new Map(people.map((row) => [row.employee.id, row.employee.full_name]));
  const items = previous.data?.results ?? [];
  // Bu ay zaten olan kalemler: aynı kişi, kalem, tutar ve açıklama (her biri bir kez eşleşir; geçen
  // ay iki aynı avans, bu ay bir tane varsa ikincisi işaretli kalır).
  const present = new Set<number>();
  const counts = new Map<string, number>();
  for (const item of current.data?.results ?? [])
    counts.set(itemKey(item), (counts.get(itemKey(item)) ?? 0) + 1);
  for (const item of items) {
    const left = counts.get(itemKey(item)) ?? 0;
    if (left > 0) {
      present.add(item.id);
      counts.set(itemKey(item), left - 1);
    }
  }
  // Seçim, bu ayın listesi bu açılışta yeniden okunduktan sonra yapılır (önbellekteki eski listeyle
  // aynı kalem iki kez eklenmesin).
  const fresh = (query: {
    isSuccess: boolean;
    isFetchedAfterMount: boolean;
    isFetching: boolean;
  }) => query.isSuccess && query.isFetchedAfterMount && !query.isFetching;
  const ready = fresh(previous) && fresh(current);
  // İşaret: bu ay olmayanlar işaretli, olanlar işaretsiz gelir; kullanıcının seçimi saklanır (liste
  // yenilense de tıklanan kutu değişmez).
  const [choices, setChoices] = useState<Map<number, boolean>>(new Map());
  const isChecked = (item: PayrollItemRecord) =>
    computed.has(item.employee) && (choices.get(item.id) ?? !present.has(item.id));
  const chosen = items.filter(isChecked);
  const save = useMutation({
    mutationFn: () =>
      addPayrollItems(
        payroll.year,
        payroll.month,
        chosen.map((item) => ({
          employee: item.employee,
          category: item.category,
          description: item.description,
          amount: item.amount,
        })),
      ),
    onSuccess: (saved) => {
      notifications.show({ color: "green", message: pn.itemsSaved(saved.length) });
      refresh();
    },
  });
  const close = () => {
    if (!save.isPending) onClose();
  };
  const toggle = (item: PayrollItemRecord) =>
    setChoices((state) => new Map(state).set(item.id, !isChecked(item)));
  const errors = save.isError ? getBatchErrors(save.error) : [];
  return (
    <Modal
      opened
      onClose={close}
      title={pn.copyTitle(monthLabel(fromYear, fromMonth))}
      size="xl"
      closeOnClickOutside={false}
      closeOnEscape={!save.isPending}
      withCloseButton={!save.isPending}
    >
      <Stack>
        <Text size="sm" c="dimmed">
          {pn.copyIntro}
        </Text>
        {!ready && !previous.isError && !current.isError && <Loader size="sm" />}
        {previous.isError && <ErrorAlert error={previous.error} />}
        {current.isError && <ErrorAlert error={current.error} />}
        {present.size > 0 && (
          <Alert color="orange" variant="light">
            <Text size="sm">{pn.copyExisting(present.size)}</Text>
          </Alert>
        )}
        {previous.data && !items.length && <Text c="dimmed">{pn.copyEmpty}</Text>}
        {items.length > 0 && (
          <Table.ScrollContainer minWidth={560}>
            <Table striped withTableBorder>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th />
                  <Table.Th>{pn.itemPerson}</Table.Th>
                  <Table.Th>{pn.itemCategory}</Table.Th>
                  <Table.Th>{pn.itemDescription}</Table.Th>
                  <Table.Th ta="right">{pn.itemAmount}</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {items.map((item) => {
                  const available = computed.has(item.employee);
                  return (
                    <Table.Tr key={item.id}>
                      <Table.Td>
                        <Checkbox
                          aria-label={`${item.employee_name} ${itemLabel(item)} · ${formatMoney(item.amount)}`}
                          checked={isChecked(item)}
                          disabled={!available || save.isPending || !ready}
                          onChange={() => toggle(item)}
                        />
                      </Table.Td>
                      <Table.Td>
                        {item.employee_name}
                        {!available && (
                          <Text span size="xs" c="dimmed">
                            {` · ${pn.copyUnavailable}`}
                          </Text>
                        )}
                        {available && present.has(item.id) && (
                          <Badge color="orange" variant="light" size="xs" ml={6} tt="none">
                            {pn.copyPresent}
                          </Badge>
                        )}
                      </Table.Td>
                      <Table.Td>{CATEGORY_LABELS[item.category]}</Table.Td>
                      <Table.Td>{item.description}</Table.Td>
                      <Table.Td ta="right">{formatMoney(item.amount)}</Table.Td>
                    </Table.Tr>
                  );
                })}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        )}
        {errors.length > 0 ? (
          <BatchErrors rows={errors} names={names} />
        ) : (
          save.isError && <ErrorAlert error={save.error} />
        )}
        <Group justify="flex-end">
          <Button variant="default" onClick={close} disabled={save.isPending}>
            {pn.cancel}
          </Button>
          <Button
            onClick={() => save.mutate(undefined, { onSuccess: onClose })}
            loading={save.isPending}
            disabled={!chosen.length || !ready}
          >
            {pn.copyAdd(chosen.length)}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
