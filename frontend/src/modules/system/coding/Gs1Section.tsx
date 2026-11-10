import {
  Alert,
  Badge,
  Button,
  Group,
  Loader,
  Modal,
  NumberInput,
  SimpleGrid,
  Stack,
  Table,
  Text,
  Textarea,
  TextInput,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconInfoCircle } from "@tabler/icons-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";
import { getErrorMessage } from "../../../api/client";
import {
  getGs1Settings,
  labelQueryKeys,
  updateGs1Settings,
  type Gs1Settings,
  type Gs1SettingsUpdate,
} from "../../../api/labels";
import { formatDateTime } from "../../../i18n/format";
import { ConfirmModal } from "../../common/ConfirmModal";
import { cs } from "./strings";

/** Sayı girişinin değeri; yazarken alan boş bırakılabilir. */
type NumberValue = number | "";

function toNumberValue(value: number | string): NumberValue {
  const number = typeof value === "number" ? value : Number(value);
  return value === "" || !Number.isFinite(number) ? "" : number;
}

/** Firma öneki: 6-12 rakam ya da boş (backend `invalid_gs1_prefix`). */
const PREFIX_PATTERN = /^\d{6,12}$/;

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <Table.Tr>
      <Table.Th scope="row" w={240} style={{ fontWeight: 500 }}>
        {label}
      </Table.Th>
      <Table.Td>{children}</Table.Td>
    </Table.Tr>
  );
}

function StateBadges({ settings }: { settings: Gs1Settings }) {
  return (
    <Group gap={4}>
      <Badge color={settings.sscc_enabled ? "teal" : "gray"}>
        {settings.sscc_enabled ? cs.gs1State.ssccOn : cs.gs1State.ssccOff}
      </Badge>
      <Badge color={settings.gtin_suggestion_enabled ? "teal" : "gray"}>
        {settings.gtin_suggestion_enabled ? cs.gs1State.gtinOn : cs.gs1State.gtinOff}
      </Badge>
    </Group>
  );
}

function None() {
  return (
    <Text size="sm" c="dimmed">
      {cs.gs1None}
    </Text>
  );
}

/** Kodlama > GS1: firma öneki, SSCC uzantı hanesi ve seri no, GTIN önerisinin ürün referansı. */
export function Gs1Section() {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const query = useQuery({ queryKey: labelQueryKeys.gs1, queryFn: getGs1Settings });
  const data = query.data;

  function saved(settings: Gs1Settings) {
    queryClient.setQueryData(labelQueryKeys.gs1, settings);
    // Etiket ayarları ve palet bölümü GS1 alanlarını ve SSCC durumunu gösterir (açık ekranlar
    // hemen yenilenir; refetchType varsayılanıyla aynıdır).
    void queryClient.invalidateQueries({
      queryKey: labelQueryKeys.settings,
      refetchType: "active",
    });
    setEditing(false);
  }

  return (
    <Stack>
      <Alert color="blue" variant="light" icon={<IconInfoCircle size={18} />}>
        <Text size="sm">{cs.gs1Intro}</Text>
      </Alert>
      {query.isLoading && <Loader />}
      {query.isError && (
        <Alert color="red" variant="light">
          {getErrorMessage(query.error)}
        </Alert>
      )}
      {data && (
        <Stack gap="sm" maw={720}>
          <Table.ScrollContainer minWidth={420}>
            <Table withTableBorder data-testid="gs1-settings">
              <Table.Tbody>
                <Row label={cs.gs1Prefix}>
                  {data.company_prefix ? (
                    <Text size="sm" ff="monospace">
                      {data.company_prefix}
                    </Text>
                  ) : (
                    <None />
                  )}
                </Row>
                <Row label={cs.gs1Extension}>{data.extension_digit}</Row>
                <Row label={cs.gs1NextSerial}>{data.next_sscc_serial}</Row>
                <Row label={cs.gs1Reference}>
                  {data.next_item_reference === null ? (
                    <None />
                  ) : (
                    <Text size="sm">
                      {data.next_item_reference}
                      {data.item_reference_digits !== null && (
                        <Text span size="sm" c="dimmed">
                          {` (${cs.gs1Digits(data.item_reference_digits)})`}
                        </Text>
                      )}
                    </Text>
                  )}
                </Row>
                <Row label={cs.colState}>
                  <StateBadges settings={data} />
                </Row>
                <Row label={cs.colChanged}>
                  <Text size="xs" c="dimmed">
                    {data.updated_at
                      ? `${formatDateTime(data.updated_at)}${
                          data.updated_by_name ? ` · ${data.updated_by_name}` : ""
                        }`
                      : ""}
                  </Text>
                </Row>
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
          <Group>
            <Button
              variant="light"
              onClick={() => setEditing(true)}
              aria-label={`${cs.edit}: ${cs.sections.gs1}`}
            >
              {cs.edit}
            </Button>
          </Group>
        </Stack>
      )}
      <Gs1Modal
        settings={editing ? (data ?? null) : null}
        onClose={() => setEditing(false)}
        onSaved={saved}
      />
    </Stack>
  );
}

interface ModalProps {
  settings: Gs1Settings | null;
  onClose: () => void;
  onSaved: (settings: Gs1Settings) => void;
}

/** GS1 ayarlarını notla düzenler; önek değişince onay ister (SSCC seri no yeni önekte sürer). */
function Gs1Modal({ settings, onClose, onSaved }: ModalProps) {
  const [prefix, setPrefix] = useState("");
  const [extension, setExtension] = useState<NumberValue>(0);
  const [reference, setReference] = useState<NumberValue>("");
  // Ürün referansı elle yazıldı mı? (Önek değişince yazılmamış referans silinir.)
  const [referenceTyped, setReferenceTyped] = useState(false);
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const [confirming, setConfirming] = useState(false);

  useEffect(() => {
    if (!settings) return;
    setPrefix(settings.company_prefix);
    setExtension(settings.extension_digit);
    setReference(settings.next_item_reference ?? "");
    setReferenceTyped(false);
    setNote("");
    setError("");
    setConfirming(false);
  }, [settings]);

  const cleanPrefix = prefix.trim();
  const prefixChanged = settings !== null && cleanPrefix !== settings.company_prefix;
  const prefixError = cleanPrefix && !PREFIX_PATTERN.test(cleanPrefix) ? cs.gs1PrefixInvalid : "";
  // Ürün referansı önekten sonraki hanelerdir (12 - önek uzunluğu); önek yoksa girilmez.
  const digits = cleanPrefix && !prefixError ? 12 - cleanPrefix.length : null;
  // Referans önekin numaralamasıdır: önek silinince ya da değişince (yeni referans yazılmadıysa)
  // silinir; yeni önekte GS1 üyeliğindeki ilk boş referans girilir.
  const shownReference: NumberValue =
    !cleanPrefix || (prefixChanged && !referenceTyped) ? "" : reference;
  const referenceValue = shownReference === "" ? null : shownReference;
  const referenceError =
    digits !== null && referenceValue !== null && referenceValue >= 10 ** digits
      ? cs.gs1ReferenceInvalid(digits)
      : "";

  const body: Gs1SettingsUpdate = { note: note.trim() };
  if (settings) {
    if (prefixChanged) body.company_prefix = cleanPrefix;
    if (extension !== "" && extension !== settings.extension_digit) {
      body.extension_digit = extension;
    }
    if (referenceValue !== settings.next_item_reference) {
      body.next_item_reference = referenceValue;
    }
  }

  const mutation = useMutation({
    mutationFn: () => updateGs1Settings(body),
    onSuccess: (saved) => {
      notifications.show({ color: "green", message: cs.gs1Saved });
      setConfirming(false);
      onSaved(saved);
    },
    onError: (err) => {
      setConfirming(false);
      setError(getErrorMessage(err));
    },
  });

  if (!settings) return null;
  const changed = Object.keys(body).length > 1;
  const valid = !prefixError && !referenceError && extension !== "";
  const canSave = changed && valid && body.note.length > 0 && !mutation.isPending;

  function save() {
    setError("");
    if (prefixChanged) setConfirming(true);
    else mutation.mutate();
  }

  return (
    <Modal opened onClose={onClose} title={cs.gs1Title} size="lg">
      <Stack>
        {error && (
          <Alert color="red" variant="light">
            {error}
          </Alert>
        )}
        <SimpleGrid cols={{ base: 1, sm: 2 }}>
          <TextInput
            label={cs.gs1Prefix}
            description={cs.gs1PrefixHelp}
            inputMode="numeric"
            maxLength={12}
            value={prefix}
            error={prefixError || undefined}
            onChange={(event) => setPrefix(event.currentTarget.value.replace(/\D/g, ""))}
          />
          <NumberInput
            label={cs.gs1Extension}
            description={cs.gs1ExtensionHelp}
            min={0}
            max={9}
            clampBehavior="strict"
            allowDecimal={false}
            allowNegative={false}
            value={extension}
            onChange={(value) => setExtension(toNumberValue(value))}
            // Boş bırakılırsa kayıtlı haneye döner.
            onBlur={() =>
              setExtension((value) => (value === "" ? settings.extension_digit : value))
            }
          />
          <NumberInput
            label={cs.gs1Reference}
            description={
              digits === null
                ? cs.gs1ReferenceNeedsPrefix
                : `${prefixChanged ? `${cs.gs1ReferenceReset} ` : ""}${cs.gs1ReferenceHelp(digits)}`
            }
            min={0}
            allowDecimal={false}
            allowNegative={false}
            disabled={digits === null}
            value={shownReference}
            error={referenceError || undefined}
            onChange={(value) => {
              setReference(toNumberValue(value));
              setReferenceTyped(true);
            }}
          />
          <TextInput
            label={cs.gs1NextSerial}
            description={cs.gs1NextSerialHelp}
            value={String(settings.next_sscc_serial)}
            disabled
          />
        </SimpleGrid>
        <Textarea
          size="md"
          label={cs.note}
          placeholder={cs.auditNotePlaceholder}
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
          <Button disabled={!canSave} loading={mutation.isPending && !confirming} onClick={save}>
            {cs.save}
          </Button>
        </Group>
      </Stack>
      <ConfirmModal
        opened={confirming}
        message={cleanPrefix ? cs.gs1PrefixConfirm : cs.gs1PrefixClearConfirm}
        confirmLabel={cs.save}
        loading={mutation.isPending}
        onConfirm={() => mutation.mutate()}
        onClose={() => setConfirming(false)}
      />
    </Modal>
  );
}
