// Kartın özlük belgeleri: kimlik fotokopisi, sözleşme, bordro, diploma (admin ve yönetim).
// Belge yeni sekmede açılır ve her açılış kartın geçmişine yazılır; bu yüzden küçük resim yoktur.
import {
  ActionIcon,
  Alert,
  Anchor,
  Badge,
  Button,
  FileInput,
  Group,
  Loader,
  Modal,
  Paper,
  Select,
  Stack,
  Text,
  Textarea,
  TextInput,
  Tooltip,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconFile, IconFileText, IconPhoto, IconTrash, IconUpload } from "@tabler/icons-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { getErrorMessage } from "../../api/client";
import {
  listEmployeeDocuments,
  removeEmployeeDocument,
  uploadEmployeeDocument,
  type Employee,
  type EmployeeDocument,
  type EmployeeDocumentKind,
} from "../../api/personnel";
import { MAX_ATTACHMENT_MB, formatSize, prepareImage } from "../../components/attachments/files";
import { formatDate, formatDateTime } from "../../i18n/format";
import { today } from "../inventory/config";
import { pe, PERSONNEL_KEY } from "./strings";

/** Kartta gösterim sırası. */
const KIND_ORDER: EmployeeDocumentKind[] = ["ID_COPY", "CONTRACT", "PAYROLL", "DIPLOMA"];
const KIND_OPTIONS = KIND_ORDER.map((value) => ({ value, label: pe.documentKinds[value] }));
const ACCEPT = ".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png";
const MONTH = /^\d{4}-(0[1-9]|1[0-2])$/;

/** "2026-09-01" → "Eylül 2026" */
function formatPeriod(value: string): string {
  const [year, month] = value.split("-");
  return `${pe.months[Number(month) - 1]} ${year}`;
}

function documentDetail(item: EmployeeDocument): string {
  if (item.period) return formatPeriod(item.period);
  if (item.valid_from) {
    const until = item.valid_until ? formatDate(item.valid_until) : pe.indefinite;
    return `${formatDate(item.valid_from)} – ${until}`;
  }
  return "";
}

function DocumentRow({ item, onRemove }: { item: EmployeeDocument; onRemove: () => void }) {
  const detail = documentDetail(item);
  const ended = item.valid_until !== null && item.valid_until < today();
  const Icon = item.mime_type.startsWith("image/") ? IconPhoto : IconFileText;
  return (
    <Group wrap="nowrap" align="flex-start" gap="sm">
      <Icon size={24} style={{ flexShrink: 0 }} />
      <Stack gap={2} style={{ flex: 1, minWidth: 0 }}>
        <Group gap={6}>
          {detail && (
            <Text size="sm" fw={500}>
              {detail}
            </Text>
          )}
          {ended && (
            <Badge size="xs" color="gray" variant="light">
              {pe.contractEnded}
            </Badge>
          )}
          <Anchor
            href={item.download_url}
            target="_blank"
            rel="noopener"
            size="sm"
            style={{ wordBreak: "break-all" }}
          >
            {item.original_name}
          </Anchor>
        </Group>
        <Text size="xs" c="dimmed">
          {[formatSize(item.size), item.uploaded_by_name, formatDateTime(item.created_at)]
            .filter(Boolean)
            .join(" · ")}
        </Text>
        {item.note && <Text size="xs">{item.note}</Text>}
      </Stack>
      <Tooltip label={pe.removeDocument}>
        <ActionIcon
          variant="subtle"
          color="red"
          aria-label={`${pe.removeDocument}: ${item.original_name}`}
          onClick={onRemove}
        >
          <IconTrash size={16} />
        </ActionIcon>
      </Tooltip>
    </Group>
  );
}

type UploadErrors = Partial<Record<"file" | "period" | "validFrom" | "validUntil", string>>;

/** Belge ekleme penceresi: türüne göre dönem (bordro) ya da tarihler (sözleşme) istenir. */
function UploadModal({
  employee,
  onClose,
  onDone,
}: {
  employee: Employee;
  onClose: () => void;
  onDone: () => void;
}) {
  const [kind, setKind] = useState<EmployeeDocumentKind>("ID_COPY");
  const [file, setFile] = useState<File | null>(null);
  const [period, setPeriod] = useState("");
  const [validFrom, setValidFrom] = useState("");
  const [validUntil, setValidUntil] = useState("");
  const [note, setNote] = useState("");
  const [errors, setErrors] = useState<UploadErrors>({});
  const mutation = useMutation({
    mutationFn: async () => {
      // Büyük fotoğraflar yüklemeden önce küçültülür.
      const prepared = await prepareImage(file!);
      if (prepared.size > MAX_ATTACHMENT_MB * 1024 * 1024) {
        throw new Error(pe.fileTooLarge(MAX_ATTACHMENT_MB));
      }
      return uploadEmployeeDocument(employee.id, {
        kind,
        file: prepared,
        period: kind === "PAYROLL" ? period : undefined,
        valid_from: kind === "CONTRACT" ? validFrom : undefined,
        valid_until: kind === "CONTRACT" && validUntil ? validUntil : undefined,
        note: note.trim() || undefined,
      });
    },
    onSuccess: onDone,
  });

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const payroll = kind === "PAYROLL";
    const contract = kind === "CONTRACT";
    // Tarayıcı ay seçiciyi göstermezse (ör. Firefox) dönem elle "2026-09" diye yazılır.
    let periodError: string | undefined;
    if (payroll && !period) periodError = pe.required;
    else if (payroll && !MONTH.test(period)) periodError = pe.periodInvalid;
    const next: UploadErrors = {
      file: file ? undefined : pe.required,
      period: periodError,
      validFrom: contract && !validFrom ? pe.required : undefined,
      validUntil:
        contract && validFrom && validUntil && validUntil < validFrom
          ? pe.validUntilBeforeStart
          : undefined,
    };
    setErrors(next);
    if (Object.values(next).some(Boolean)) return;
    mutation.mutate();
  }

  const error = mutation.error;
  return (
    <Modal
      opened
      onClose={onClose}
      title={pe.uploadTitle(employee.full_name)}
      closeOnClickOutside={false}
    >
      <form onSubmit={handleSubmit} noValidate>
        <Stack>
          <Select
            label={pe.documentKind}
            data={KIND_OPTIONS}
            value={kind}
            onChange={(value) => value && setKind(value as EmployeeDocumentKind)}
            allowDeselect={false}
          />
          <FileInput
            label={pe.documentFile}
            placeholder={pe.documentFilePlaceholder}
            description={pe.documentFileHelp(MAX_ATTACHMENT_MB)}
            accept={ACCEPT}
            value={file}
            onChange={setFile}
            error={errors.file}
            leftSection={<IconFile size={16} />}
            required
            clearable
            size="md"
          />
          {kind === "PAYROLL" && (
            <TextInput
              type="month"
              label={pe.period}
              placeholder={pe.periodPlaceholder}
              value={period}
              onChange={(e) => setPeriod(e.currentTarget.value)}
              error={errors.period}
              required
            />
          )}
          {kind === "CONTRACT" && (
            <>
              <TextInput
                type="date"
                label={pe.validFrom}
                value={validFrom}
                onChange={(e) => setValidFrom(e.currentTarget.value)}
                error={errors.validFrom}
                required
              />
              <TextInput
                type="date"
                label={pe.validUntil}
                description={pe.validUntilHelp}
                value={validUntil}
                onChange={(e) => setValidUntil(e.currentTarget.value)}
                error={errors.validUntil}
              />
            </>
          )}
          <Textarea
            label={pe.note}
            value={note}
            onChange={(e) => setNote(e.currentTarget.value)}
            autosize
            minRows={2}
            maxLength={500}
            size="md"
          />
          {mutation.isError && (
            <Alert color="red" variant="light" role="alert">
              {error instanceof Error && !("isAxiosError" in error)
                ? error.message
                : getErrorMessage(error)}
            </Alert>
          )}
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose} disabled={mutation.isPending}>
              {pe.cancel}
            </Button>
            <Button
              type="submit"
              leftSection={<IconUpload size={16} />}
              loading={mutation.isPending}
            >
              {pe.upload}
            </Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}

/** Kaldırma penceresi: neden zorunlu. */
function RemoveModal({
  item,
  onClose,
  onDone,
}: {
  item: EmployeeDocument;
  onClose: () => void;
  onDone: () => void;
}) {
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | undefined>();
  const mutation = useMutation({
    mutationFn: () => removeEmployeeDocument(item.id, reason.trim()),
    onSuccess: onDone,
  });

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const missing = !reason.trim();
    setError(missing ? pe.required : undefined);
    if (!missing) mutation.mutate();
  }

  return (
    <Modal opened onClose={onClose} title={pe.removeTitle}>
      <form onSubmit={handleSubmit} noValidate>
        <Stack>
          <Text size="sm">{pe.removeIntro}</Text>
          <Text size="sm" fw={500} style={{ wordBreak: "break-all" }}>
            {`${item.kind_display} · ${item.original_name}`}
          </Text>
          <TextInput
            label={pe.removeReason}
            value={reason}
            onChange={(e) => setReason(e.currentTarget.value)}
            error={error}
            required
            maxLength={500}
            data-autofocus
          />
          {mutation.isError && (
            <Alert color="red" variant="light" role="alert">
              {getErrorMessage(mutation.error)}
            </Alert>
          )}
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose} disabled={mutation.isPending}>
              {pe.cancel}
            </Button>
            <Button type="submit" color="red" loading={mutation.isPending}>
              {pe.removeDocument}
            </Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}

/** Kartın "Belgeler" bölümü: türüne göre gruplanmış liste, ekleme ve kaldırma. */
export function EmployeeDocuments({ employee }: { employee: Employee }) {
  const queryClient = useQueryClient();
  const [adding, setAdding] = useState(false);
  const [removing, setRemoving] = useState<EmployeeDocument | null>(null);
  const list = useQuery({
    queryKey: [...PERSONNEL_KEY, "employee", employee.id, "documents"],
    queryFn: () => listEmployeeDocuments(employee.id),
  });

  function done(message: string) {
    setAdding(false);
    setRemoving(null);
    notifications.show({ color: "green", message });
    // Belgeler ve kartın geçmişi birlikte yenilenir.
    void queryClient.invalidateQueries({ queryKey: [...PERSONNEL_KEY, "employee", employee.id] });
  }

  const items = list.data ?? [];
  const groups = KIND_ORDER.map((kind) => ({
    kind,
    items: items.filter((item) => item.kind === kind),
  })).filter((group) => group.items.length > 0);

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="md">
        <Group justify="space-between" align="flex-start">
          <Stack gap={2} style={{ flex: 1, minWidth: 220 }}>
            <Text fw={600}>{pe.documents}</Text>
            <Text size="xs" c="dimmed">
              {pe.documentsIntro}
            </Text>
          </Stack>
          <Button
            variant="light"
            leftSection={<IconUpload size={16} />}
            onClick={() => setAdding(true)}
          >
            {pe.addDocument}
          </Button>
        </Group>
        {list.isPending && <Loader size="sm" />}
        {list.isError && (
          <Alert color="red" variant="light">
            {getErrorMessage(list.error)}
          </Alert>
        )}
        {list.isSuccess && items.length === 0 && (
          <Text size="sm" c="dimmed">
            {pe.noDocuments}
          </Text>
        )}
        {groups.map((group) => (
          <Stack key={group.kind} gap="xs" data-testid={`documents-${group.kind}`}>
            <Text size="sm" fw={600}>
              {`${pe.documentKinds[group.kind]} (${group.items.length})`}
            </Text>
            {group.items.map((item) => (
              <DocumentRow key={item.id} item={item} onRemove={() => setRemoving(item)} />
            ))}
          </Stack>
        ))}
      </Stack>
      {adding && (
        <UploadModal
          employee={employee}
          onClose={() => setAdding(false)}
          onDone={() => done(pe.uploaded)}
        />
      )}
      {removing && (
        <RemoveModal
          item={removing}
          onClose={() => setRemoving(null)}
          onDone={() => done(pe.documentRemoved)}
        />
      )}
    </Paper>
  );
}
