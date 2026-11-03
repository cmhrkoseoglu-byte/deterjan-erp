// Devirler penceresi (Personel > Bordro): kişinin bu işverende bir ayın öncesindeki kümülatif gelir
// vergisi matrahı ve asgari ücret istisnası ay sayısı, mali müşavirin bir önceki ay bordrosundan.
// ERP bordrosunun ilk ayında (Ekim 2026) herkes için, mali müşavirden ERP'ye geçişte ve mali
// müşavirle eşitlemede girilir (docs/DECISIONS.md "3. adım kararları"). Tek "Kaydet": hepsi ya da
// hiçbiri; satır hataları satırın altında. Excel'den yapıştırılan tutar (ve ay) sütunu ekrandaki
// sırayla; sicil no sütunuyla birlikte yapıştırılırsa sicil no ile eşleşerek dolar. Gelecek aya devir
// girilmez.
import {
  Alert,
  Badge,
  Button,
  Checkbox,
  Group,
  Modal,
  Stack,
  Switch,
  Table,
  Text,
  TextInput,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type ClipboardEvent } from "react";
import { personnelCostKeys } from "../../api/costing";
import {
  getBatchErrors,
  payrollKeys,
  removeOpening,
  saveOpenings,
  type OpeningInput,
  type PayrollMonth,
  type PayrollOpening,
  type PayrollRow,
} from "../../api/payroll";
import { formatDate, formatMoney } from "../../i18n/format";
import { monthLabel, parseMoney } from "../costing/personnelCostFormat";
import { ErrorAlert } from "../costing/ReportTable";
import { isFutureMonth, monthsEmployedBefore, openingTarget } from "./payrollFormat";
import { ReasonModal } from "./ReasonModal";
import { pn, py } from "./strings";

interface Draft {
  taxBase: string;
  months: string;
  note: string;
}

/** Yapıştırmanın özeti (satırların altında). */
interface PasteNote {
  mode: "sicil" | "position";
  filled: number;
  /** Sicil no'su pencerede olmayan satırlar. */
  unmatched: string[];
  /** Sicil no'su eşleşen ama tutar hücresi boş satırlar. */
  noAmount: string[];
  /** Birden fazla satırda farklı değerle geçen sicil no'lar (o kişi doldurulmaz). */
  repeated: string[];
  /** Sicil no'dan sonra birden çok sayı sütunu (TC kimlik no, gün): hiçbir kutu dolmaz. */
  ambiguous: boolean;
}

// İstisna ay sayısı hücresi (0–11): devir ayından önceki ay sayısı en çok 11'dir.
const MONTHS_CELL = /^(?:\d|1[01])$/;

// Tutar ve ay kutularının açıklaması (öneri, olası hata) kutunun altında: satırlar hizalı kalır.
const BELOW: ("label" | "input" | "description" | "error")[] = [
  "label",
  "input",
  "description",
  "error",
];

/** Kişinin devir ayındaki etkin devri (satır, kişinin bu yıl bu aya kadarki devirlerini taşır). */
function existing(row: PayrollRow, target: number): PayrollOpening | null {
  return row.openings.find((opening) => opening.month === target) ?? null;
}

function blankDraft(row: PayrollRow, year: number, target: number): Draft {
  const months =
    row.entry_month === target
      ? row.suggestion_months
      : monthsEmployedBefore(row.employee, year, target);
  return { taxBase: "", months: String(months), note: "" };
}

function initialDraft(row: PayrollRow, year: number, target: number): Draft {
  const opening = existing(row, target);
  if (!opening) return blankDraft(row, year, target);
  return {
    taxBase: formatMoney(opening.tax_base),
    months: String(opening.exemption_months),
    note: opening.note,
  };
}

/** Tutar: Türkçe ya da İngilizce biçim (382.500,00 / 382,500.00 / 382500), başında ya da sonunda
 * TL / ₺ olabilir; sıfır olabilir. Sekme içeren metin (iki Excel hücresi) tutar değildir. */
function amount(text: string): string | null {
  const value = text
    .trim()
    .replace(/^(₺|TL)\s*/i, "")
    .replace(/\s*(₺|TL)$/i, "");
  if (!value || value.includes("\t")) return null;
  const english = /^\d{1,3}(,\d{3})+(\.\d{1,2})?$/.test(value);
  return parseMoney(english ? value.replace(/,/g, "") : value, { allowZero: true });
}

/** Sicil no anahtarı: büyük-küçük harf ve i / I / İ / ı farkı yok (Excel'de yazım değişebilir);
 * yalnızca rakamsa baştaki sıfırlar atılır (Excel sayıya çevirince siler). */
function sicilKey(text: string): string {
  const folded = text.trim().toLocaleUpperCase("tr").replace(/İ/g, "I");
  return /^\d+$/.test(folded) ? folded.replace(/^0+(?=\d)/, "") : folded;
}

/** Tutar olabilecek hücre: rakam, Excel hatası (#YOK) ya da tek tire (muhasebe biçiminde sıfır).
 * Tutar sütununu seçmek ve başlık satırını atlamak için kullanılır; seçilen sütundaki boş olmayan
 * hücre kutuya olduğu gibi yazılır (okunamayan tutar kaydı durdurur). */
const amountLike = (cell: string) => /[\d#]/.test(cell) || /^[-–]$/.test(cell);

/** Excel'den yapıştırılan metin: satırlar (yalnızca sondaki boş satırlar atılır; aradaki boş satır
 * o kişiyi atlar) ve satırda sekmeyle ayrılmış hücreler. */
function pastedCells(text: string): string[][] {
  return text
    .replace(/(\r?\n)+$/, "")
    .split(/\r?\n/)
    .map((line) => line.split("\t").map((cell) => cell.trim()));
}

export function OpeningsModal({
  payroll,
  target: requested,
  employeeId,
  onClose,
}: {
  payroll: PayrollMonth;
  target?: number;
  /** Yalnızca bu kişi (dökümden açıldığında). */
  employeeId?: number;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const year = payroll.year;
  // Devir ayı pencere açılırken sabitlenir: bir devir kaldırılıp veri yenilenince pencere başka aya
  // geçmez.
  const [target] = useState(() => requested ?? openingTarget(payroll));
  // Gelecek aya devir girilmez: bir önceki ayın kümülatifi o ay bitince belli olur (sunucuyla aynı).
  const future = isFutureMonth(year, target);
  const previous = monthLabel(year, target - 1);
  const computed = payroll.rows.filter((row) => !row.external);
  const [everyone, setEveryone] = useState(false);
  const [onlyMissing, setOnlyMissing] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [removing, setRemoving] = useState<PayrollOpening | null>(null);
  // Sunucunun eşitleme onayı istediği kişiler: onay kutusu onlar için de çıkar.
  const [serverOverrides, setServerOverrides] = useState<Set<number>>(() => new Set());
  const [pasteNote, setPasteNote] = useState<PasteNote | null>(null);
  // "Yalnızca girilmeyenler" açıkken düzenlenen satır, süzgeç yeniden açılana kadar görünür kalır
  // (yazarken girilmiş değere eşitlenince kutu kaybolmasın).
  const [touched, setTouched] = useState<Set<number>>(() => new Set());
  const touch = (ids: number[]) =>
    setTouched((current) =>
      ids.every((id) => current.has(id)) ? current : new Set([...current, ...ids]),
    );
  // Kaydedildikten sonra parametreleri değişen devir (zincirin çapası): istisna matrahı eskidi.
  const stale = (row: PayrollRow) =>
    row.carry_months.some(
      (link) =>
        link.kind === "opening" && link.month === target && link.flags.includes("opening_stale"),
    );
  // Bu yıl devir ayından önce bu işyerinde çalışmayan kişiye devir girilmez (kümülatif sıfırdır).
  const candidates = computed.filter((row) => {
    if (monthsEmployedBefore(row.employee, year, target) === 0) return false;
    if (employeeId !== undefined) return row.employee.id === employeeId;
    if (everyone) return true;
    if (existing(row, target) !== null && stale(row)) return true;
    return row.entry_month === target && (row.opening_needed || existing(row, target) !== null);
  });
  const [drafts, setDrafts] = useState<Record<number, Draft>>(() =>
    Object.fromEntries(computed.map((row) => [row.employee.id, initialDraft(row, year, target)])),
  );
  const draftOf = (row: PayrollRow, from: Record<number, Draft> = drafts) =>
    from[row.employee.id] ?? initialDraft(row, year, target);
  const change = (row: PayrollRow, values: Partial<Draft>) => {
    touch([row.employee.id]);
    setDrafts((current) => ({
      ...current,
      [row.employee.id]: { ...draftOf(row, current), ...values },
    }));
  };
  // Önceki ayı ERP'de hesaplanan kişide devir o ayların yerine geçer (eşitleme): onay ister.
  const overrides = (row: PayrollRow) =>
    (row.entry_month !== null && row.entry_month < target) || serverOverrides.has(row.employee.id);
  const maxMonths = (row: PayrollRow) => monthsEmployedBefore(row.employee, year, target);
  const monthsValid = (row: PayrollRow) => {
    const text = draftOf(row).months.trim();
    return /^\d+$/.test(text) && Number(text) <= maxMonths(row);
  };
  // Gönderilenler: tutarı yazılmış, girilmiş devirden farklı satırlar (değişmeyen devir yeniden
  // yazılmaz; kartın geçmişine boş "düzeltildi" notu düşmez). Kaydedildikten sonra parametreleri
  // değişen devir de gönderilir: sunucu istisna matrahını bugünkü parametrelerle yeniden yazar.
  const changed = (row: PayrollRow) => {
    const opening = existing(row, target);
    if (!opening || stale(row)) return true;
    const draft = draftOf(row);
    return (
      Number(amount(draft.taxBase)) !== Number(opening.tax_base) ||
      draft.months.trim() !== String(opening.exemption_months) ||
      draft.note.trim() !== opening.note
    );
  };
  const sent = candidates.filter((row) => amount(draftOf(row).taxBase) !== null && changed(row));
  // Yazılmış ama okunamayan tutar tek "Kaydet"i durdurur (hepsi ya da hiçbiri); boş satır atlanır.
  const unreadable = candidates.filter((row) => {
    const text = draftOf(row).taxBase.trim();
    return text !== "" && amount(text) === null;
  });
  const needsConfirm = sent.some(overrides);
  const save = useMutation({
    mutationFn: () =>
      saveOpenings(
        year,
        target,
        sent.map((row): OpeningInput => ({
          employee: row.employee.id,
          tax_base: amount(draftOf(row).taxBase) ?? "",
          exemption_months: Number(draftOf(row).months),
          note: draftOf(row).note.trim(),
          confirm_override: overrides(row) && confirmed,
        })),
      ),
    onSuccess: (saved) => {
      notifications.show({ color: "green", message: pn.openingSaved(saved.length) });
      void queryClient.invalidateQueries({ queryKey: payrollKeys.all });
      void queryClient.invalidateQueries({ queryKey: personnelCostKeys.all });
    },
    onError: (error) => {
      // Sunucu bir satır için eşitleme onayı istediyse onay kutusu o satır için de çıkar.
      const flagged = getBatchErrors(error)
        .filter((row) => row.code === "opening_overrides_chain" && row.employee !== null)
        .map((row) => row.employee as number);
      if (!flagged.length) return;
      setServerOverrides((current) => new Set([...current, ...flagged]));
      setConfirmed(false);
    },
  });
  const errors = save.isError ? getBatchErrors(save.error) : [];
  const errorFor = (row: PayrollRow) =>
    errors.find((item) => item.employee === row.employee.id)?.detail;
  const close = () => {
    if (!save.isPending) onClose();
  };
  // "Yalnızca girilmeyenler" yalnızca dokunulmamış girilmiş devirleri gizler: gönderilecek
  // (değişmiş, yapıştırılmış, yeniden kaydedilecek), okunamayan, ay sayısı geçersiz ya da sunucunun
  // reddettiği satır görünür kalır (gizli satır görünmeden kaydedilmesin).
  const pending = (row: PayrollRow) => {
    const text = draftOf(row).taxBase.trim();
    return (
      errorFor(row) !== undefined ||
      (text !== "" && (amount(text) === null || !monthsValid(row) || changed(row)))
    );
  };
  const shown = candidates.filter(
    (row) =>
      !onlyMissing ||
      existing(row, target) === null ||
      pending(row) ||
      touched.has(row.employee.id),
  );
  // Excel'den yapıştırma. Yalnızca tutar ya da tutar ve istisna ay (0–11) satırları yapıştırılan
  // kutudan aşağı ekrandaki sırayla dolar (aradaki boş satır o kişiyi atlar). Başka biçimli sekmeli
  // satırlar (sicil no ve tutar, araya ad soyad) sicil no ile eşleşir, sıra önemsizdir; eşleşmeyen
  // sicil no'lar listelenir, hiçbiri eşleşmezse hiçbir kutu dolmaz. Tutarın sağındaki hücre tam
  // sayıysa istisna ay sayısıdır.
  const paste = (start: PayrollRow, event: ClipboardEvent<HTMLInputElement>) => {
    const cells = pastedCells(event.clipboardData.getData("text"));
    const tabbed = cells.some((line) => line.length > 1);
    if (cells.length < 2 && !tabbed) return; // tek değer: tarayıcı kendisi yapıştırır
    event.preventDefault();
    // Aynı anahtara inen iki kart (ör. "S-1" ve "s-1") eşleşmez: satır listelenir.
    const bySicil = new Map<string, PayrollRow | null>();
    for (const row of candidates) {
      const key = sicilKey(row.employee.employee_no);
      if (key) bySicil.set(key, bySicil.has(key) ? null : row);
    }
    const keyed = (line: string[]) => {
      const rest = line.slice(1).filter(Boolean);
      return rest.length > 1 || (rest.length === 1 && !MONTHS_CELL.test(rest[0]));
    };
    const sicilMode =
      tabbed &&
      cells.some((line) => keyed(line) || (line.length > 1 && bySicil.get(sicilKey(line[0]))));
    const updates: { row: PayrollRow; taxBase: string; months?: string }[] = [];
    const unmatched: string[] = [];
    const noAmount: string[] = [];
    const repeated: string[] = [];
    let ambiguous = false;
    if (sicilMode) {
      // Tutar sütunu satır satır değil, sicil no'su eşleşen aynı genişlikteki satırlardan bir kez
      // seçilir (Excel'in kopyaladığı aralık dikdörtgendir): 0–11 dışında tutar olabilecek hücre
      // taşıyan tek sütun. Boş tutar hücresi yandaki ay hücresini tutar yapmaz; birden çok sayı
      // sütunu (TC kimlik no, gün) varsa hiçbir kutu dolmaz.
      const matched = cells.filter((line) => line.length > 1 && bySicil.get(sicilKey(line[0])));
      const amountColumn = new Map<number, number | null>();
      for (const width of new Set(matched.map((line) => line.length))) {
        const same = matched.filter((line) => line.length === width);
        const columns: number[] = [];
        for (let column = 1; column < width; column += 1)
          if (same.some((line) => amountLike(line[column]) && !MONTHS_CELL.test(line[column])))
            columns.push(column);
        if (columns.length > 1) ambiguous = true;
        amountColumn.set(width, columns.length === 1 ? columns[0] : null);
      }
      const found = new Map<PayrollRow, { sicil: string; taxBase: string; months?: string }[]>();
      const missing = new Map<PayrollRow, string>();
      for (const line of cells) {
        if (!line.some(Boolean)) continue;
        const row = bySicil.get(sicilKey(line[0]));
        if (!row) {
          // Başlık satırı ("Sicil no / Ad soyad / Matrah") tutar taşımaz: listelenmez.
          if (line.some((cell, position) => position > 0 && amountLike(cell)))
            unmatched.push(line[0] || line.join(" "));
          continue;
        }
        if (ambiguous) continue;
        const column = amountColumn.get(line.length);
        if (column == null || !line[column]) {
          if (!missing.has(row)) missing.set(row, line[0]);
          continue;
        }
        const entry = { sicil: line[0], taxBase: line[column], months: line[column + 1] };
        found.set(row, [...(found.get(row) ?? []), entry]);
      }
      // Aynı kişi farklı değerle birden çok satırdaysa hangisi doğru bilinmez: kutu dolmaz, sicil no
      // listelenir; aynı değerin tekrarı bir kez dolar.
      const sameAmount = (a: string, b: string) => {
        const x = amount(a);
        const y = amount(b);
        return x !== null && y !== null ? Number(x) === Number(y) : a === b;
      };
      for (const [row, list] of found) {
        const [first] = list;
        const agree = list.every(
          (entry) =>
            sameAmount(entry.taxBase, first.taxBase) &&
            (entry.months ?? "") === (first.months ?? ""),
        );
        if (agree) updates.push({ row, taxBase: first.taxBase, months: first.months });
        else repeated.push(first.sicil);
      }
      for (const [row, sicil] of missing) if (!found.has(row)) noAmount.push(sicil);
    } else {
      const first = shown.indexOf(start);
      cells.forEach((line, offset) => {
        const row = shown[first + offset];
        if (row && line[0]) updates.push({ row, taxBase: line[0], months: line[1] });
      });
    }
    setDrafts((current) => {
      const next = { ...current };
      for (const { row, taxBase, months } of updates) {
        const draft = { ...draftOf(row, next), taxBase };
        if (months !== undefined && /^\d+$/.test(months)) draft.months = months;
        next[row.employee.id] = draft;
      }
      return next;
    });
    // Görünen satırlara yazılan değerler süzgeç açıkken de görünür kalır.
    touch(updates.filter(({ row }) => shown.includes(row)).map(({ row }) => row.employee.id));
    setPasteNote({
      mode: sicilMode ? "sicil" : "position",
      filled: updates.length,
      unmatched,
      noAmount,
      repeated,
      ambiguous,
    });
  };
  const exemptionBase = Number(payroll.parameters.values.exemption_base);
  const hint = (row: PayrollRow): string | null => {
    const value = amount(draftOf(row).taxBase);
    if (value === null || !monthsValid(row)) return null;
    const months = Number(draftOf(row).months);
    const wage = Number(row.line.monthly_wage ?? 0);
    const base = Number(value);
    if (months && base < months * exemptionBase * 0.99) return pn.openingBelowExemption;
    const expected = months * wage * 0.85;
    if (expected && (base < expected * 0.5 || base > expected * 1.5))
      return pn.openingPlausible(formatMoney(expected));
    return null;
  };
  const entered = candidates.filter((row) => existing(row, target) !== null).length;
  const invalid =
    future ||
    !sent.length ||
    unreadable.length > 0 ||
    sent.some((row) => !monthsValid(row)) ||
    (needsConfirm && !confirmed);
  return (
    <Modal
      opened
      onClose={close}
      title={pn.openingTitle(monthLabel(year, target), previous)}
      size="100%"
      closeOnClickOutside={false}
      // Üstte gerekçe penceresi açıkken Esc yalnızca onu kapatır (taslaklar kaybolmaz).
      closeOnEscape={!save.isPending && !removing}
      withCloseButton={!save.isPending}
    >
      <Stack>
        <Text size="sm" c="dimmed" maw={980}>
          {pn.openingIntro(previous)}
        </Text>
        {future && (
          <Alert color="blue" variant="light">
            <Text size="sm">{pn.futureOpeningsHint}</Text>
          </Alert>
        )}
        <Group gap="lg" wrap="wrap">
          {employeeId === undefined && (
            <Switch
              label={pn.openingEveryone}
              checked={everyone}
              onChange={(event) => setEveryone(event.currentTarget.checked)}
              disabled={save.isPending || future}
            />
          )}
          <Switch
            label={pn.openingFilterNeeded}
            checked={onlyMissing}
            onChange={(event) => {
              setOnlyMissing(event.currentTarget.checked);
              setTouched(new Set());
            }}
          />
          <Badge variant="light">{pn.openingCount(entered, candidates.length)}</Badge>
        </Group>
        {!candidates.length ? (
          <Text c="dimmed">{pn.openingNoCandidates}</Text>
        ) : (
          <Table.ScrollContainer minWidth={980}>
            <Table striped withTableBorder verticalSpacing={6}>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>{pn.col.employeeNo}</Table.Th>
                  <Table.Th>{pn.col.fullName}</Table.Th>
                  <Table.Th>{pn.openingTaxBase(previous)}</Table.Th>
                  <Table.Th>{pn.openingMonths}</Table.Th>
                  <Table.Th>{pn.openingNote}</Table.Th>
                  {target === payroll.month && (
                    <Table.Th ta="right">{pn.openingResultTax}</Table.Th>
                  )}
                  <Table.Th />
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {shown.map((row) => {
                  const draft = draftOf(row);
                  const opening = existing(row, target);
                  const failure = errorFor(row);
                  const warning = hint(row);
                  const max = maxMonths(row);
                  return (
                    <Table.Tr key={row.employee.id} style={{ verticalAlign: "top" }}>
                      <Table.Td>{row.employee.employee_no}</Table.Td>
                      <Table.Td>
                        <Stack gap={0}>
                          <Text size="sm">{row.employee.full_name}</Text>
                          <Text size="xs" c="dimmed">
                            {row.employee.hire_date
                              ? pn.openingHire(formatDate(row.employee.hire_date))
                              : pn.openingHireUnknown}
                          </Text>
                          {opening && (
                            <Badge
                              color="green"
                              variant="light"
                              size="xs"
                              tt="none"
                              w="fit-content"
                            >
                              {pn.openingEntered}
                            </Badge>
                          )}
                          {opening && stale(row) && (
                            <Badge
                              color="orange"
                              variant="light"
                              size="xs"
                              tt="none"
                              w="fit-content"
                            >
                              {pn.chainFlags.opening_stale}
                            </Badge>
                          )}
                        </Stack>
                      </Table.Td>
                      <Table.Td miw={180}>
                        <TextInput
                          aria-label={`${pn.openingTaxBase(previous)}: ${row.employee.full_name}`}
                          inputMode="decimal"
                          value={draft.taxBase}
                          disabled={save.isPending || future}
                          inputWrapperOrder={BELOW}
                          error={
                            failure ??
                            (draft.taxBase.trim() && amount(draft.taxBase) === null
                              ? py.invalidAmount
                              : undefined)
                          }
                          description={warning ?? undefined}
                          onPaste={(event) => paste(row, event)}
                          onChange={(event) => change(row, { taxBase: event.currentTarget.value })}
                        />
                      </Table.Td>
                      <Table.Td miw={120}>
                        <TextInput
                          aria-label={`${pn.openingMonths}: ${row.employee.full_name}`}
                          inputMode="numeric"
                          value={draft.months}
                          disabled={save.isPending || future}
                          inputWrapperOrder={BELOW}
                          error={
                            draft.months.trim() && !monthsValid(row)
                              ? pn.invalidMonths(max)
                              : undefined
                          }
                          description={pn.openingSuggestion(
                            max,
                            formatMoney(
                              row.entry_month === target
                                ? row.suggestion_base
                                : String(max * exemptionBase),
                            ),
                          )}
                          onChange={(event) => change(row, { months: event.currentTarget.value })}
                        />
                      </Table.Td>
                      <Table.Td miw={160}>
                        <TextInput
                          aria-label={`${pn.openingNote}: ${row.employee.full_name}`}
                          maxLength={200}
                          value={draft.note}
                          disabled={save.isPending || future}
                          onChange={(event) => change(row, { note: event.currentTarget.value })}
                        />
                      </Table.Td>
                      {target === payroll.month && (
                        <Table.Td ta="right">{formatMoney(row.line.income_tax)}</Table.Td>
                      )}
                      <Table.Td>
                        {opening && (
                          <Button
                            variant="subtle"
                            color="red"
                            size="compact-xs"
                            aria-label={`${pn.removeOpening}: ${row.employee.full_name}`}
                            onClick={() => setRemoving(opening)}
                            disabled={save.isPending}
                          >
                            {pn.removeItem}
                          </Button>
                        )}
                      </Table.Td>
                    </Table.Tr>
                  );
                })}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        )}
        {pasteNote &&
          (pasteNote.ambiguous ||
            pasteNote.unmatched.length > 0 ||
            pasteNote.noAmount.length > 0 ||
            pasteNote.repeated.length > 0) && (
            <Alert color="orange" variant="light">
              {pasteNote.ambiguous && <Text size="sm">{pn.openingPasteAmbiguous}</Text>}
              {pasteNote.repeated.length > 0 && (
                <Text size="sm">{pn.openingPasteRepeated(pasteNote.repeated.join(", "))}</Text>
              )}
              {pasteNote.unmatched.length > 0 && (
                <Text size="sm">{pn.openingPasteUnmatched(pasteNote.unmatched.join(", "))}</Text>
              )}
              {pasteNote.noAmount.length > 0 && (
                <Text size="sm">{pn.openingPasteNoAmount(pasteNote.noAmount.join(", "))}</Text>
              )}
            </Alert>
          )}
        {pasteNote && pasteNote.filled > 0 && (
          <Text size="xs" c="dimmed">
            {pasteNote.mode === "sicil"
              ? pn.openingPasteSicil(pasteNote.filled)
              : pn.openingPastePosition(pasteNote.filled)}
          </Text>
        )}
        <Text size="xs" c="dimmed">
          {pn.openingMonthsHelp}
        </Text>
        {needsConfirm && (
          <Checkbox
            label={pn.openingOverride}
            checked={confirmed}
            onChange={(event) => setConfirmed(event.currentTarget.checked)}
            disabled={save.isPending}
          />
        )}
        {unreadable.length > 0 && (
          <Text size="sm" c="red">
            {pn.openingUnreadable(unreadable.length)}
          </Text>
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
      {removing && (
        <ReasonModal
          title={pn.removeOpening}
          intro={pn.removeOpeningIntro}
          confirmLabel={pn.removeOpening}
          onConfirm={(reason) => removeOpening(removing.id, reason)}
          onDone={() => {
            // Kaldırılan devrin değerleri taslakta kalmaz (yoksa sonraki "Kaydet" onu yeniden
            // girerdi); satır yenilenen veriden boş açılır.
            const removed = removing.employee;
            setDrafts((current) => {
              const next = { ...current };
              delete next[removed];
              return next;
            });
            notifications.show({ color: "green", message: pn.openingRemoved });
            void queryClient.invalidateQueries({ queryKey: payrollKeys.all });
            void queryClient.invalidateQueries({ queryKey: personnelCostKeys.all });
          }}
          onClose={() => setRemoving(null)}
        />
      )}
    </Modal>
  );
}
