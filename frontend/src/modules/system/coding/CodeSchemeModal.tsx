import {
  Alert,
  Button,
  Group,
  Modal,
  NumberInput,
  Select,
  SimpleGrid,
  Stack,
  Switch,
  Table,
  Text,
  Textarea,
  TextInput,
} from "@mantine/core";
import { useDebouncedValue } from "@mantine/hooks";
import { notifications } from "@mantine/notifications";
import { IconInfoCircle } from "@tabler/icons-react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { getErrorMessage } from "../../../api/client";
import {
  previewCodeType,
  updateCodeType,
  type CodeFormatValues,
  type CodePreviewRequest,
  type CodeSchemeUpdate,
  type CodeTypeOption,
  type CodeTypeRow,
  type DateFormat,
  type YearFormat,
} from "../../../api/coding";
import { ConfirmModal } from "../../common/ConfirmModal";
import { cs } from "./strings";

interface Props {
  row: CodeTypeRow | null;
  onClose: () => void;
  onSaved: (row: CodeTypeRow) => void;
}

// Sıradaki numara en çok 15 hane (backend core.coding.formats.MAX_COUNTER).
const MAX_COUNTER = 999_999_999_999_999;
const WIDTHS = { master: [2, 9], document: [4, 7], lot: [3, 5] } as const;

/** Sayı girişinin değeri; yazarken alan boş bırakılabilir. */
type NumberValue = number | "";

function toNumberValue(value: number | string): NumberValue {
  const number = typeof value === "number" ? value : Number(value);
  return value === "" || !Number.isFinite(number) ? "" : number;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

/** Bir kod türünün biçimini düzenler: önek, sıra hanesi, yıl ya da tarih, etkinlik, sayaç. */
export function CodeSchemeModal({ row, onClose, onSaved }: Props) {
  const [prefix, setPrefix] = useState("");
  const [width, setWidth] = useState<NumberValue>(5);
  const [typePrefixes, setTypePrefixes] = useState<Record<string, string>>({});
  const [yearFormat, setYearFormat] = useState<YearFormat>("YYYY");
  const [dateFormat, setDateFormat] = useState<DateFormat>("YYYYMMDD");
  const [active, setActive] = useState(false);
  // Elle yazılan "sıradaki numara" (türe göre önekte tür değeri → numara). Yazılmamışsa
  // (undefined) düzenlenen önekin sayacı gösterilir.
  const [typeCounters, setTypeCounters] = useState<Record<string, NumberValue>>({});
  const [nextNumber, setNextNumber] = useState<NumberValue | undefined>(undefined);
  const [note, setNote] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!row) return;
    setPrefix(row.prefix);
    setWidth(row.width);
    setTypePrefixes({ ...row.type_prefixes });
    setYearFormat((row.year_format || "YYYY") as YearFormat);
    setDateFormat((row.date_format || "YYYYMMDD") as DateFormat);
    setActive(row.is_active);
    setTypeCounters({});
    setNextNumber(undefined);
    setNote("");
    setError("");
    setConfirming(false);
  }, [row]);

  const kind = row?.kind;
  const sequence = kind === "master" && Boolean(row) && !row?.free;
  const typed = Boolean(row?.type_field);
  const hasFormat = Boolean(row) && !row?.free && kind !== "standard";
  const [minWidth, maxWidth] =
    kind === "lot" ? WIDTHS.lot : kind === "document" ? WIDTHS.document : WIDTHS.master;
  const widthError =
    typeof width === "number" && (width < minWidth || width > maxWidth)
      ? cs.widthRange(minWidth, maxWidth)
      : "";
  const widthReady = typeof width === "number" && !widthError;

  const values = useMemo<CodeFormatValues>(() => {
    if (!hasFormat || typeof width !== "number") return {};
    if (typed) return { width, type_prefixes: typePrefixes };
    if (kind === "document") return { prefix, width, year_format: yearFormat };
    if (kind === "lot") return { prefix, width, date_format: dateFormat };
    return { prefix, width };
  }, [hasFormat, kind, typed, prefix, width, typePrefixes, yearFormat, dateFormat]);

  /** Elle yazılan sıradaki numaralar, düzenlenen önekle: {"MLZ": 25}. */
  const typedCounters = useMemo(() => {
    const result: Record<string, number> = {};
    if (!sequence) return result;
    if (typed) {
      for (const [type, value] of Object.entries(typeCounters)) {
        const target = typePrefixes[type];
        if (typeof value === "number" && value >= 1 && target) result[target] = value;
      }
    } else if (typeof nextNumber === "number" && nextNumber >= 1 && prefix) {
      result[prefix] = nextNumber;
    }
    return result;
  }, [sequence, typed, typeCounters, typePrefixes, nextNumber, prefix]);

  // Önizleme geçerli sıra hanesiyle istenir; yazılan sayaçlar örnekteki sıradaki koda yansır.
  const request = useMemo<CodePreviewRequest | null>(() => {
    if (!hasFormat || !widthReady) return null;
    return Object.keys(typedCounters).length ? { ...values, counters: typedCounters } : values;
  }, [hasFormat, widthReady, values, typedCounters]);
  const [debounced] = useDebouncedValue(request, 300);
  // Yazarken önizleme 300 ms geride kalır; o arada eski biçimin örneği kullanılmaz.
  const current = request !== null && JSON.stringify(debounced) === JSON.stringify(request);

  const preview = useQuery({
    queryKey: ["system", "coding", "preview", row?.key, debounced],
    queryFn: () => previewCodeType(row!.key, debounced!),
    enabled: Boolean(row) && current,
    retry: false,
  });
  const example = current ? (preview.data?.example ?? null) : null;

  // Düzenlenen önekin sıradaki numarası: önizlemeden; önek kayıttakiyse kayıttan.
  const naturalNext: NumberValue = example
    ? example.last_number + 1
    : row && prefix === row.prefix
      ? row.last_number + 1
      : "";

  function naturalTypeNext(type: CodeTypeOption): NumberValue {
    const fresh = example?.types.find((item) => item.value === type.value);
    if (fresh) return fresh.last_number + 1;
    return typePrefixes[type.value] === type.prefix ? type.last_number + 1 : "";
  }

  /** Kaydedilecek sayaçlar: elle yazılanlar; önek değiştiyse gösterilen numara da gönderilir. */
  function countersToSave(): Record<string, number> {
    const result: Record<string, number> = { ...typedCounters };
    if (!row || !sequence) return result;
    if (typed) {
      for (const type of row.types) {
        const target = typePrefixes[type.value];
        const shown = naturalTypeNext(type);
        if (target && target !== type.prefix && typeCounters[type.value] === undefined) {
          if (typeof shown === "number") result[target] = shown;
        }
      }
    } else if (prefix && prefix !== row.prefix && nextNumber === undefined) {
      if (typeof naturalNext === "number") result[prefix] = naturalNext;
    }
    return result;
  }

  const mutation = useMutation({
    mutationFn: () => {
      const body: CodeSchemeUpdate = { ...values, note };
      if (kind === "master") body.is_active = active;
      const counters = countersToSave();
      if (Object.keys(counters).length) body.counters = counters;
      return updateCodeType(row!.key, body);
    },
    onSuccess: (saved) => {
      notifications.show({ color: "green", message: cs.saved(saved.label) });
      setConfirming(false);
      onSaved(saved);
    },
    onError: (err) => {
      setConfirming(false);
      setError(getErrorMessage(err));
    },
  });

  if (!row) return null;
  const previewError = !current
    ? ""
    : preview.isError
      ? getErrorMessage(preview.error)
      : preview.data && !preview.data.valid
        ? (preview.data.error?.detail ?? "")
        : "";
  // Biçimli türde örnek güncel ve geçerli olmadan kaydedilmez.
  const previewReady =
    !hasFormat || (current && !preview.isFetching && preview.data?.valid === true);
  const canSave = note.trim().length > 0 && previewReady;
  const widthInput = {
    size: "md" as const,
    label: cs.width,
    description: cs.widthHelp(minWidth, maxWidth),
    min: minWidth,
    max: maxWidth,
    allowDecimal: false,
    allowNegative: false,
    value: width,
    error: widthError || undefined,
    onChange: (value: number | string) => setWidth(toNumberValue(value)),
    // Aralık dışı değer çıkışta sınıra çekilir; boş bırakılırsa kayıtlı haneye döner.
    onBlur: () =>
      setWidth((value) => (value === "" ? row.width : clamp(value, minWidth, maxWidth))),
  };

  return (
    <Modal opened onClose={onClose} title={cs.editTitle(row.label)} size="lg">
      <Stack>
        {error && (
          <Alert color="red" variant="light">
            {error}
          </Alert>
        )}
        {row.free && (
          <Alert color="gray" variant="light" icon={<IconInfoCircle size={18} />}>
            <Text size="sm">{cs.freeHelp}</Text>
          </Alert>
        )}
        {sequence && !typed && (
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <TextInput
              label={cs.prefix}
              description={cs.prefixHelp}
              value={prefix}
              maxLength={12}
              onChange={(event) => setPrefix(event.currentTarget.value.toUpperCase())}
            />
            <NumberInput {...widthInput} />
          </SimpleGrid>
        )}
        {sequence && typed && (
          <Stack gap="xs">
            <NumberInput {...widthInput} maw={220} />
            <Text size="sm" fw={500}>
              {cs.typePrefixes}
            </Text>
            <Table withTableBorder>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>{cs.colType}</Table.Th>
                  <Table.Th>{cs.prefix}</Table.Th>
                  <Table.Th>{cs.counter}</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {row.types.map((type) => (
                  <Table.Tr key={type.value}>
                    <Table.Td>{type.label}</Table.Td>
                    <Table.Td>
                      <TextInput
                        aria-label={`${cs.prefix}: ${type.label}`}
                        value={typePrefixes[type.value] ?? ""}
                        maxLength={12}
                        onChange={(event) =>
                          setTypePrefixes({
                            ...typePrefixes,
                            [type.value]: event.currentTarget.value.toUpperCase(),
                          })
                        }
                      />
                    </Table.Td>
                    <Table.Td>
                      <NumberInput
                        size="md"
                        aria-label={`${cs.counter}: ${type.label}`}
                        min={1}
                        max={MAX_COUNTER}
                        allowDecimal={false}
                        allowNegative={false}
                        value={typeCounters[type.value] ?? naturalTypeNext(type)}
                        onChange={(value) =>
                          setTypeCounters({ ...typeCounters, [type.value]: toNumberValue(value) })
                        }
                        // Boş bırakılırsa düzenlenen önekin sayacı yeniden gösterilir.
                        onBlur={() =>
                          setTypeCounters((counters) => {
                            if (counters[type.value] !== "") return counters;
                            const next = { ...counters };
                            delete next[type.value];
                            return next;
                          })
                        }
                      />
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Stack>
        )}
        {kind === "document" && (
          <Stack gap="sm">
            <SimpleGrid cols={{ base: 1, sm: 2 }}>
              <TextInput
                label={cs.prefix}
                description={cs.prefixHelp}
                value={prefix}
                maxLength={10}
                onChange={(event) => setPrefix(event.currentTarget.value.toUpperCase())}
              />
              <NumberInput {...widthInput} />
            </SimpleGrid>
            <Select
              label={cs.yearFormat}
              data={Object.entries(cs.years).map(([value, label]) => ({ value, label }))}
              value={yearFormat}
              allowDeselect={false}
              onChange={(value) => value && setYearFormat(value as YearFormat)}
            />
          </Stack>
        )}
        {kind === "lot" && (
          <Stack gap="sm">
            <SimpleGrid cols={{ base: 1, sm: 2 }}>
              <TextInput
                label={cs.prefix}
                description={cs.lotPrefixHelp}
                value={prefix}
                maxLength={4}
                onChange={(event) => setPrefix(event.currentTarget.value.toUpperCase())}
              />
              <NumberInput {...widthInput} />
            </SimpleGrid>
            <Select
              label={cs.dateFormat}
              data={Object.entries(cs.dates).map(([value, label]) => ({ value, label }))}
              value={dateFormat}
              allowDeselect={false}
              onChange={(value) => value && setDateFormat(value as DateFormat)}
            />
          </Stack>
        )}
        {kind === "master" && (
          <Switch
            label={cs.activate}
            description={cs.activeHelp}
            checked={active}
            onChange={(event) => setActive(event.currentTarget.checked)}
          />
        )}
        {sequence && !typed && (
          <NumberInput
            size="md"
            label={cs.counter}
            description={cs.counterHelp}
            min={1}
            max={MAX_COUNTER}
            allowDecimal={false}
            allowNegative={false}
            maw={260}
            value={nextNumber ?? naturalNext}
            onChange={(value) => setNextNumber(toNumberValue(value))}
            // Boş bırakılırsa düzenlenen önekin sayacı yeniden gösterilir.
            onBlur={() => setNextNumber((value) => (value === "" ? undefined : value))}
          />
        )}
        {hasFormat && (
          <Alert
            color={previewError ? "red" : "gray"}
            variant="light"
            title={cs.preview}
            data-testid="coding-preview"
          >
            {previewError ? (
              <Text size="sm">{previewError}</Text>
            ) : example && example.types.length > 0 ? (
              <Stack gap={2}>
                {example.types.map((type) => (
                  <Text key={type.value} size="sm">
                    {type.label}: <b>{type.next}</b>
                  </Text>
                ))}
              </Stack>
            ) : example ? (
              <Text size="sm">
                {cs.next}: <b>{example.next}</b> · {cs.longest}: {example.longest}
              </Text>
            ) : (
              <Text size="sm" c="dimmed">
                …
              </Text>
            )}
          </Alert>
        )}
        <Textarea
          size="md"
          label={cs.note}
          placeholder={cs.notePlaceholder}
          withAsterisk
          autosize
          minRows={2}
          value={note}
          onChange={(event) => setNote(event.currentTarget.value)}
        />
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            {cs.cancel}
          </Button>
          <Button disabled={!canSave} onClick={() => setConfirming(true)}>
            {cs.save}
          </Button>
        </Group>
      </Stack>
      <ConfirmModal
        opened={confirming}
        message={cs.confirm}
        confirmLabel={cs.save}
        loading={mutation.isPending}
        onConfirm={() => mutation.mutate()}
        onClose={() => setConfirming(false)}
      />
    </Modal>
  );
}
