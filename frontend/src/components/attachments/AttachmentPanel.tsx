// Kayda bağlı dosya ekleri paneli (Adım 2.4): lot, mal kabul, numune.
//   <AttachmentPanel contentType="inventory.lot" objectId={lot.id} defaultKind="SUPPLIER_COA" />
// Tablette "Fotoğraf çek" arka kamerayı açar; büyük fotoğraflar yüklemeden önce küçültülür.
import {
  ActionIcon,
  Anchor,
  Badge,
  Button,
  Group,
  Image,
  Loader,
  Modal,
  Paper,
  Select,
  Stack,
  Text,
  TextInput,
  Title,
  Tooltip,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconCamera, IconFile, IconPaperclip, IconTrash, IconUpload } from "@tabler/icons-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import {
  attachmentKeys,
  listAttachments,
  removeAttachment,
  uploadAttachment,
  type Attachment,
  type AttachmentKind,
} from "../../api/attachments";
import { getErrorMessage } from "../../api/client";
import { formatDateTime } from "../../i18n/format";
import { tr } from "../../i18n/tr";
import { ACCEPT, MAX_ATTACHMENT_MB, formatSize, prepareImage } from "./files";

const t = tr.attachments;
const KIND_OPTIONS = (Object.keys(t.kinds) as AttachmentKind[]).map((value) => ({
  value,
  label: t.kinds[value],
}));

function isImage(item: Attachment): boolean {
  return item.mime_type.startsWith("image/") && item.mime_type !== "image/heic";
}

function AttachmentRow({ item, onRemove }: { item: Attachment; onRemove: () => void }) {
  return (
    <Group wrap="nowrap" align="flex-start" gap="sm">
      {isImage(item) ? (
        <Anchor href={item.download_url} target="_blank">
          <Image src={item.download_url} w={56} h={56} radius="sm" fit="cover" alt="" />
        </Anchor>
      ) : (
        <IconFile size={32} style={{ flexShrink: 0 }} />
      )}
      <Stack gap={2} style={{ flex: 1, minWidth: 0 }}>
        <Anchor
          href={item.download_url}
          target="_blank"
          size="sm"
          style={{ wordBreak: "break-all" }}
        >
          {item.original_name}
        </Anchor>
        <Group gap={6}>
          <Badge size="xs" variant="light">
            {item.kind_display}
          </Badge>
          <Text size="xs" c="dimmed">
            {`${formatSize(item.size)} · ${item.uploaded_by_name ?? ""} · ${formatDateTime(item.created_at)}`}
          </Text>
        </Group>
        {item.note && <Text size="xs">{item.note}</Text>}
      </Stack>
      {item.can_remove && (
        <Tooltip label={t.remove}>
          <ActionIcon
            variant="subtle"
            color="red"
            aria-label={`${t.remove}: ${item.original_name}`}
            onClick={onRemove}
          >
            <IconTrash size={16} />
          </ActionIcon>
        </Tooltip>
      )}
    </Group>
  );
}

export function AttachmentPanel({
  contentType,
  objectId,
  defaultKind = "OTHER",
  title = t.title,
}: {
  contentType: string;
  objectId: number;
  defaultKind?: AttachmentKind;
  title?: string;
}) {
  const queryClient = useQueryClient();
  const key = attachmentKeys.list(contentType, objectId);
  const fileRef = useRef<HTMLInputElement>(null);
  const cameraRef = useRef<HTMLInputElement>(null);
  const [kind, setKind] = useState<AttachmentKind>(defaultKind);
  const [note, setNote] = useState("");
  const [removing, setRemoving] = useState<Attachment | null>(null);
  const [reason, setReason] = useState("");
  const list = useQuery({ queryKey: key, queryFn: () => listAttachments(contentType, objectId) });

  const upload = useMutation({
    mutationFn: async ({ file, asKind }: { file: File; asKind: AttachmentKind }) => {
      const prepared = await prepareImage(file);
      if (prepared.size > MAX_ATTACHMENT_MB * 1024 * 1024) {
        throw new Error(t.tooLarge(MAX_ATTACHMENT_MB));
      }
      return uploadAttachment(contentType, objectId, prepared, { kind: asKind, note });
    },
    onSuccess: () => {
      setNote("");
      notifications.show({ color: "green", message: t.uploaded });
      void queryClient.invalidateQueries({ queryKey: key });
    },
    onError: (err) =>
      notifications.show({
        color: "red",
        message:
          err instanceof Error && !("isAxiosError" in err) ? err.message : getErrorMessage(err),
      }),
  });
  const remove = useMutation({
    mutationFn: () => removeAttachment(removing!.id, reason),
    onSuccess: () => {
      setRemoving(null);
      setReason("");
      notifications.show({ color: "green", message: t.removed });
      void queryClient.invalidateQueries({ queryKey: key });
    },
    onError: (err) => notifications.show({ color: "red", message: getErrorMessage(err) }),
  });

  function pick(files: FileList | null, asKind: AttachmentKind) {
    for (const file of Array.from(files ?? [])) upload.mutate({ file, asKind });
  }

  const items = list.data ?? [];
  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Group gap={6}>
          <IconPaperclip size={18} />
          <Title order={4}>
            {title}
            {items.length ? ` (${items.length})` : ""}
          </Title>
        </Group>
        {list.isPending && <Loader size="sm" />}
        {list.isSuccess && items.length === 0 && (
          <Text size="sm" c="dimmed">
            {t.empty}
          </Text>
        )}
        {items.map((item) => (
          <AttachmentRow key={item.id} item={item} onRemove={() => setRemoving(item)} />
        ))}
        <Group align="flex-end" gap="xs">
          <Select
            label={t.kind}
            data={KIND_OPTIONS}
            value={kind}
            onChange={(value) => value && setKind(value as AttachmentKind)}
            allowDeselect={false}
            w={220}
          />
          <TextInput
            label={t.note}
            value={note}
            onChange={(event) => setNote(event.currentTarget.value)}
            maxLength={500}
            style={{ flex: 1, minWidth: 160 }}
          />
        </Group>
        <Group gap="xs">
          <Button
            variant="light"
            leftSection={<IconUpload size={16} />}
            loading={upload.isPending}
            onClick={() => fileRef.current?.click()}
          >
            {t.upload}
          </Button>
          <Button
            variant="light"
            leftSection={<IconCamera size={16} />}
            loading={upload.isPending}
            onClick={() => cameraRef.current?.click()}
          >
            {t.photo}
          </Button>
        </Group>
        <input
          ref={fileRef}
          type="file"
          multiple
          accept={ACCEPT}
          hidden
          data-testid="attachment-file"
          onChange={(event) => {
            pick(event.currentTarget.files, kind);
            event.currentTarget.value = "";
          }}
        />
        <input
          ref={cameraRef}
          type="file"
          accept="image/*"
          capture="environment"
          hidden
          data-testid="attachment-camera"
          onChange={(event) => {
            pick(event.currentTarget.files, kind === "OTHER" ? "PHOTO" : kind);
            event.currentTarget.value = "";
          }}
        />
      </Stack>

      <Modal opened={removing !== null} onClose={() => setRemoving(null)} title={t.removeTitle}>
        <Stack>
          <Text size="sm">{removing?.original_name}</Text>
          <TextInput
            label={t.removeReason}
            value={reason}
            onChange={(event) => setReason(event.currentTarget.value)}
          />
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setRemoving(null)}>
              {tr.record.cancel}
            </Button>
            <Button color="red" loading={remove.isPending} onClick={() => remove.mutate()}>
              {t.remove}
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Paper>
  );
}
