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
  type CodeSchemeUpdate,
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

const WIDTHS = { master: [2, 9], document: [4, 7], lot: [3, 5] } as const;

/** Bir kod türünün biçimini düzenler: önek, sıra hanesi, yıl ya da tarih, etkinlik, sayaç. */
export function CodeSchemeModal({ row, onClose, onSaved }: Props) {
  const [prefix, setPrefix] = useState("");
  const [width, setWidth] = useState(5);
  const [typePrefixes, setTypePrefixes] = useState<Record<string, string>>({});
  const [yearFormat, setYearFormat] = useState<YearFormat>("YYYY");
  const [dateFormat, setDateFormat] = useState<DateFormat>("YYYYMMDD");
  const [active, setActive] = useState(false);
  // Sıradaki numara düzeltmesi: türe göre önekte tür değeri → numara, değilse tek numara.
  const [typeCounters, setTypeCounters] = useState<Record<string, number | "">>({});
  const [nextNumber, setNextNumber] = useState<number | "">("");
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
    setNextNumber("");
    setNote("");
    setError("");
    setConfirming(false);
  }, [row]);

  const kind = row?.kind;
  const sequence = kind === "master" && row && !row.free;
  const typed = Boolean(row?.type_field);

  const values = useMemo<CodeFormatValues>(() => {
    if (!row || row.free || kind === "standard") return {};
    if (typed) return { width, type_prefixes: typePrefixes };
    if (kind === "document") return { prefix, width, year_format: yearFormat };
    if (kind === "lot") return { prefix, width, date_format: dateFormat };
    return { prefix, width };
  }, [row, kind, typed, prefix, width, typePrefixes, yearFormat, dateFormat]);
  const [debounced] = useDebouncedValue(values, 300);

  const preview = useQuery({
    queryKey: ["system", "coding", "preview", row?.key, debounced],
    queryFn: () => previewCodeType(row!.key, debounced),
    enabled: Boolean(row) && Object.keys(debounced).length > 0,
    retry: false,
  });

  /** Sayaç düzeltmeleri: yalnızca değiştirilen "sıradaki numara"lar, güncel önekle. */
  function changedCounters(): Record<string, number> {
    const result: Record<string, number> = {};
    if (!row) return result;
    if (typed) {
      for (const type of row.types) {
        const value = typeCounters[type.value];
        const target = typePrefixes[type.value];
        if (value !== undefined && value !== "" && value !== type.last_number + 1 && target) {
          result[target] = value;
        }
      }
    } else if (nextNumber !== "" && nextNumber !== row.last_number + 1 && prefix) {
      result[prefix] = nextNumber;
    }
    return result;
  }

  const mutation = useMutation({
    mutationFn: () => {
      const body: CodeSchemeUpdate = { ...values, note };
      if (kind === "master") body.is_active = active;
      const fixed = changedCounters();
      if (Object.keys(fixed).length) body.counters = fixed;
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
  const [minWidth, maxWidth] =
    kind === "lot" ? WIDTHS.lot : kind === "document" ? WIDTHS.document : WIDTHS.master;
  const example = preview.data?.example;
  const previewError = preview.data && !preview.data.valid ? preview.data.error?.detail : "";
  const canSave = note.trim().length > 0 && !previewError && !preview.isFetching;

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
            <NumberInput
              size="md"
              label={cs.width}
              description={cs.widthHelp(minWidth, maxWidth)}
              min={minWidth}
              max={maxWidth}
              allowDecimal={false}
              value={width}
              onChange={(value) => setWidth(Number(value) || minWidth)}
            />
          </SimpleGrid>
        )}
        {sequence && typed && (
          <Stack gap="xs">
            <NumberInput
              size="md"
              label={cs.width}
              description={cs.widthHelp(minWidth, maxWidth)}
              min={minWidth}
              max={maxWidth}
              allowDecimal={false}
              value={width}
              onChange={(value) => setWidth(Number(value) || minWidth)}
              maw={220}
            />
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
                        allowDecimal={false}
                        value={typeCounters[type.value] ?? type.last_number + 1}
                        onChange={(value) =>
                          setTypeCounters({
                            ...typeCounters,
                            [type.value]: value === "" ? "" : Number(value),
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
              <NumberInput
                size="md"
                label={cs.width}
                description={cs.widthHelp(minWidth, maxWidth)}
                min={minWidth}
                max={maxWidth}
                allowDecimal={false}
                value={width}
                onChange={(value) => setWidth(Number(value) || minWidth)}
              />
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
              <NumberInput
                size="md"
                label={cs.width}
                description={cs.widthHelp(minWidth, maxWidth)}
                min={minWidth}
                max={maxWidth}
                allowDecimal={false}
                value={width}
                onChange={(value) => setWidth(Number(value) || minWidth)}
              />
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
            allowDecimal={false}
            maw={260}
            value={nextNumber === "" ? row.last_number + 1 : nextNumber}
            onChange={(value) => setNextNumber(value === "" ? "" : Number(value))}
          />
        )}
        {Object.keys(values).length > 0 && (
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
