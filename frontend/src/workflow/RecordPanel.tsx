// Kayıt yorum paneli: her belge/lot detay sayfasının sağ panelinde kullanılır.
//   <RecordPanel contentType="inventory.lot" objectId={lot.id} />
import {
  ActionIcon,
  Anchor,
  Avatar,
  Button,
  CloseButton,
  Group,
  Image,
  Loader,
  Paper,
  ScrollArea,
  Stack,
  Tabs,
  Text,
  Textarea,
  UnstyledButton,
} from "@mantine/core";
import { useDebouncedValue } from "@mantine/hooks";
import { notifications } from "@mantine/notifications";
import { IconCamera, IconFile, IconHistory, IconMessage, IconPaperclip } from "@tabler/icons-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Fragment,
  useLayoutEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { uploadAttachment, type Attachment } from "../api/attachments";
import { getErrorMessage } from "../api/client";
import { ACCEPT, MAX_ATTACHMENT_MB, prepareImage } from "../components/attachments/files";
import {
  addComment,
  editComment,
  fetchComments,
  fetchMentionableUsers,
  fetchRecordHistory,
  type AuditEntry,
  type Comment,
  type RecordRef,
  type UserBrief,
} from "../api/workflow";
import { formatDateTime } from "../i18n/format";
import { tr } from "../i18n/tr";
import { workflowKeys } from "./queryKeys";

interface Props {
  /** "app_label.model", ör. "inventory.lot" */
  contentType: string;
  objectId: number;
}

// Backend ile aynı: @ öncesi harf/rakam ya da @.+- olmamalı (e-posta adresi bahsetme değildir).
const MENTION_RE = /(^|[^\w@.+-])(@[\w.@+-]+)/gu;
// İmlecin hemen solundaki yarım bahsetme: "...@meh"
const TRAILING_MENTION_RE = /(?:^|[^\w@.+-])@([\w.+-]*)$/u;

/** Yorum metnindeki @kullanıcıadı ifadelerini vurgular. */
function renderBody(body: string, mentions: UserBrief[]): ReactNode {
  const known = new Set(mentions.map((u) => u.username.toLocaleLowerCase("tr-TR")));
  const parts: ReactNode[] = [];
  let last = 0;
  for (const match of body.matchAll(MENTION_RE)) {
    const start = (match.index ?? 0) + match[1].length;
    const token = match[2];
    const name = token.slice(1).replace(/\.+$/, "");
    if (!known.has(name.toLocaleLowerCase("tr-TR"))) continue;
    parts.push(body.slice(last, start));
    parts.push(
      <Text key={start} span fw={600} c="blue">
        @{name}
      </Text>,
    );
    last = start + 1 + name.length;
  }
  parts.push(body.slice(last));
  return parts.map((part, i) => <Fragment key={i}>{part}</Fragment>);
}

function MentionTextarea({
  record,
  value,
  onChange,
  onSubmit,
  placeholder,
  autoFocus,
}: {
  /** Öneriler yalnızca bu kaydı görebilen kişilerden gelir. */
  record: RecordRef;
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  placeholder?: string;
  autoFocus?: boolean;
}) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const pendingCaret = useRef<number | null>(null);
  const [caret, setCaret] = useState(0);
  const [highlight, setHighlight] = useState(0);
  const [dismissed, setDismissed] = useState(false);
  const partial = TRAILING_MENTION_RE.exec(value.slice(0, caret))?.[1] ?? null;
  const [search] = useDebouncedValue(partial, 200);
  const suggestions = useQuery({
    queryKey: workflowKeys.mentionable(record, search ?? ""),
    queryFn: () => fetchMentionableUsers(search ?? "", record),
    enabled: search !== null,
    staleTime: 60_000,
  });
  const options = partial !== null && !dismissed ? (suggestions.data ?? []) : [];

  function insert(user: UserBrief) {
    const before = value.slice(0, caret).replace(/@[\w.+-]*$/u, `@${user.username} `);
    const next = before + value.slice(caret);
    onChange(next);
    setCaret(before.length);
    pendingCaret.current = before.length;
  }

  // Seçilen kişi eklenince imleci, yeniden çizimden hemen sonra (sonraki tuştan önce) eklenen
  // adın sonuna taşı.
  useLayoutEffect(() => {
    if (pendingCaret.current === null || !ref.current) return;
    ref.current.focus();
    ref.current.setSelectionRange(pendingCaret.current, pendingCaret.current);
    pendingCaret.current = null;
  }, [value]);

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (options.length) {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        const delta = event.key === "ArrowDown" ? 1 : -1;
        setHighlight((h) => (h + delta + options.length) % options.length);
        return;
      }
      if (event.key === "Enter" || event.key === "Tab") {
        event.preventDefault();
        insert(options[Math.min(highlight, options.length - 1)]);
        return;
      }
      if (event.key === "Escape") {
        setDismissed(true);
        return;
      }
    }
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      onSubmit();
    }
  }

  return (
    <div>
      <Textarea
        ref={ref}
        value={value}
        placeholder={placeholder}
        autoFocus={autoFocus}
        autosize
        minRows={2}
        maxRows={8}
        maxLength={5000}
        aria-label={placeholder}
        onChange={(e) => {
          onChange(e.currentTarget.value);
          setCaret(e.currentTarget.selectionStart ?? e.currentTarget.value.length);
          setHighlight(0);
          setDismissed(false);
        }}
        onSelect={(e) => setCaret(e.currentTarget.selectionStart ?? 0)}
        onKeyDown={handleKeyDown}
      />
      {options.length > 0 && (
        <Paper withBorder shadow="sm" mt={4} role="listbox" aria-label="Kişi önerileri">
          {options.map((user, i) => (
            <UnstyledButton
              key={user.id}
              role="option"
              aria-selected={i === highlight}
              display="block"
              w="100%"
              px="sm"
              py={8}
              bg={i === highlight ? "var(--mantine-color-blue-light)" : undefined}
              onMouseDown={(e) => {
                e.preventDefault();
                insert(user);
              }}
            >
              <Text size="sm" fw={500} span>
                @{user.username}
              </Text>
              {user.full_name && (
                <Text size="sm" c="dimmed" span>
                  {" "}
                  {user.full_name}
                </Text>
              )}
            </UnstyledButton>
          ))}
        </Paper>
      )}
    </div>
  );
}

function CommentAttachments({ items }: { items: Attachment[] }) {
  if (!items.length) return null;
  return (
    <Group gap="xs" mt={4}>
      {items.map((item) =>
        item.mime_type.startsWith("image/") && item.mime_type !== "image/heic" ? (
          <Anchor key={item.id} href={item.download_url} target="_blank">
            <Image
              src={item.download_url}
              w={72}
              h={72}
              radius="sm"
              fit="cover"
              alt={item.original_name}
            />
          </Anchor>
        ) : (
          <Anchor key={item.id} href={item.download_url} target="_blank" size="xs">
            <Group gap={4} wrap="nowrap">
              <IconFile size={14} />
              {item.original_name}
            </Group>
          </Anchor>
        ),
      )}
    </Group>
  );
}

function CommentItem({ comment, record }: { comment: Comment; record: RecordRef }) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(comment.body);
  const save = useMutation({
    mutationFn: () => editComment(comment.id, draft),
    onSuccess: () => {
      setEditing(false);
      void queryClient.invalidateQueries({ queryKey: workflowKeys.comments(record) });
      void queryClient.invalidateQueries({ queryKey: workflowKeys.history(record) });
    },
    onError: (error) => notifications.show({ message: getErrorMessage(error), color: "red" }),
  });
  const name = comment.author.full_name || comment.author.username;

  return (
    <Group align="flex-start" wrap="nowrap" gap="sm">
      <Avatar radius="xl" size="md" color="blue">
        {name.charAt(0).toLocaleUpperCase("tr-TR")}
      </Avatar>
      <Stack gap={2} style={{ flex: 1, minWidth: 0 }}>
        <Group gap={6}>
          <Text size="sm" fw={600}>
            {name}
          </Text>
          <Text size="xs" c="dimmed">
            {formatDateTime(comment.created_at)}
            {comment.edited_at ? ` · ${tr.record.edited}` : ""}
          </Text>
        </Group>
        {editing ? (
          <Stack gap="xs">
            <MentionTextarea
              record={record}
              value={draft}
              onChange={setDraft}
              onSubmit={() => save.mutate()}
              autoFocus
            />
            <Group gap="xs">
              <Button
                size="xs"
                loading={save.isPending}
                disabled={!draft.trim()}
                onClick={() => save.mutate()}
              >
                {tr.record.save}
              </Button>
              <Button
                size="xs"
                variant="default"
                onClick={() => {
                  setDraft(comment.body);
                  setEditing(false);
                }}
              >
                {tr.record.cancel}
              </Button>
            </Group>
          </Stack>
        ) : (
          <>
            <Text size="sm" style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
              {renderBody(comment.body, comment.mentions)}
            </Text>
            <CommentAttachments items={comment.attachments ?? []} />
            {comment.can_edit && (
              <Button
                variant="subtle"
                size="compact-xs"
                w="fit-content"
                onClick={() => setEditing(true)}
              >
                {tr.record.edit}
              </Button>
            )}
          </>
        )}
      </Stack>
    </Group>
  );
}

function formatChange(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (Array.isArray(value)) return value.join(", ");
  return String(value);
}

function HistoryItem({ entry }: { entry: AuditEntry }) {
  const changes = Object.entries(entry.changes ?? {});
  return (
    <Stack gap={2}>
      <Group gap={6}>
        <Text size="sm" fw={600}>
          {entry.action_label}
        </Text>
        <Text size="xs" c="dimmed">
          {entry.actor_name || tr.record.system} · {formatDateTime(entry.timestamp)}
        </Text>
      </Group>
      {changes.map(([field, [before, after]]) => (
        <Text key={field} size="xs" c="dimmed" style={{ wordBreak: "break-word" }}>
          {field}: {formatChange(before)} → {formatChange(after)}
        </Text>
      ))}
      {entry.note && <Text size="xs">{entry.note}</Text>}
    </Stack>
  );
}

export function RecordPanel({ contentType, objectId }: Props) {
  const record: RecordRef = { contentType, objectId };
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<string | null>("comments");
  const [body, setBody] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const fileRef = useRef<HTMLInputElement>(null);
  const cameraRef = useRef<HTMLInputElement>(null);
  const comments = useQuery({
    queryKey: workflowKeys.comments(record),
    queryFn: () => fetchComments(record),
  });
  const history = useQuery({
    queryKey: workflowKeys.history(record),
    queryFn: () => fetchRecordHistory(record),
    enabled: tab === "history",
  });
  const send = useMutation({
    mutationFn: async () => {
      const comment = await addComment(record, body);
      // Ekler yorum kaydedildikten sonra yoruma bağlanır; biri yüklenemezse yorum yine durur.
      const failed: string[] = [];
      for (const file of files) {
        try {
          const prepared = await prepareImage(file);
          await uploadAttachment("workflow.comment", comment.id, prepared, {
            kind: prepared.type.startsWith("image/") ? "PHOTO" : "DOCUMENT",
          });
        } catch (error) {
          failed.push(`${file.name}: ${getErrorMessage(error)}`);
        }
      }
      return failed;
    },
    onSuccess: (failed) => {
      setBody("");
      setFiles([]);
      if (failed.length) {
        notifications.show({
          color: "red",
          title: tr.record.uploadFailed,
          message: failed.join("\n"),
        });
      }
      void queryClient.invalidateQueries({ queryKey: workflowKeys.comments(record) });
      void queryClient.invalidateQueries({ queryKey: workflowKeys.history(record) });
    },
    onError: (error) => notifications.show({ message: getErrorMessage(error), color: "red" }),
  });
  const addFiles = (list: FileList | null) => {
    const picked = Array.from(list ?? []);
    const tooBig = picked.find(
      (f) => f.size > MAX_ATTACHMENT_MB * 1024 * 1024 && !f.type.startsWith("image/"),
    );
    if (tooBig) {
      notifications.show({ color: "red", message: tr.attachments.tooLarge(MAX_ATTACHMENT_MB) });
      return;
    }
    setFiles((current) => [...current, ...picked]);
  };
  const submit = () => {
    if (body.trim() && !send.isPending) send.mutate();
  };

  return (
    <Paper withBorder radius="md" p="sm">
      <Tabs value={tab} onChange={setTab}>
        <Tabs.List grow>
          <Tabs.Tab value="comments" leftSection={<IconMessage size={16} />}>
            {tr.record.comments}
            {comments.data?.length ? ` (${comments.data.length})` : ""}
          </Tabs.Tab>
          <Tabs.Tab value="history" leftSection={<IconHistory size={16} />}>
            {tr.record.history}
          </Tabs.Tab>
        </Tabs.List>

        <Tabs.Panel value="comments" pt="sm">
          <Stack gap="md">
            <ScrollArea.Autosize mah={480}>
              <Stack gap="md">
                {comments.isPending && <Loader size="sm" />}
                {comments.data?.length === 0 && (
                  <Text size="sm" c="dimmed">
                    {tr.record.noComments}
                  </Text>
                )}
                {comments.data?.map((c) => (
                  <CommentItem key={c.id} comment={c} record={record} />
                ))}
              </Stack>
            </ScrollArea.Autosize>
            <MentionTextarea
              record={record}
              value={body}
              onChange={setBody}
              onSubmit={submit}
              placeholder={tr.record.placeholder}
            />
            {files.length > 0 && (
              <Stack gap={2}>
                {files.map((file, index) => (
                  <Group key={`${file.name}-${index}`} gap={4} wrap="nowrap">
                    <IconPaperclip size={14} />
                    <Text size="xs" style={{ flex: 1, wordBreak: "break-all" }}>
                      {file.name}
                    </Text>
                    <CloseButton
                      size="sm"
                      aria-label={tr.record.removeFile(file.name)}
                      onClick={() => setFiles((current) => current.filter((_, i) => i !== index))}
                    />
                  </Group>
                ))}
              </Stack>
            )}
            <Group gap="xs">
              <Button
                onClick={submit}
                loading={send.isPending}
                disabled={!body.trim()}
                w="fit-content"
              >
                {tr.record.send}
              </Button>
              <ActionIcon
                variant="default"
                size="lg"
                aria-label={tr.record.attachFile}
                onClick={() => fileRef.current?.click()}
              >
                <IconPaperclip size={18} />
              </ActionIcon>
              <ActionIcon
                variant="default"
                size="lg"
                aria-label={tr.record.takePhoto}
                onClick={() => cameraRef.current?.click()}
              >
                <IconCamera size={18} />
              </ActionIcon>
            </Group>
            <input
              ref={fileRef}
              type="file"
              multiple
              accept={ACCEPT}
              hidden
              data-testid="comment-file"
              onChange={(event) => {
                addFiles(event.currentTarget.files);
                event.currentTarget.value = "";
              }}
            />
            <input
              ref={cameraRef}
              type="file"
              accept="image/*"
              capture="environment"
              hidden
              onChange={(event) => {
                addFiles(event.currentTarget.files);
                event.currentTarget.value = "";
              }}
            />
          </Stack>
        </Tabs.Panel>

        <Tabs.Panel value="history" pt="sm">
          <ScrollArea.Autosize mah={560}>
            <Stack gap="md">
              {history.isPending && <Loader size="sm" />}
              {history.data?.length === 0 && (
                <Text size="sm" c="dimmed">
                  {tr.record.noHistory}
                </Text>
              )}
              {history.data?.map((entry) => (
                <HistoryItem key={entry.id} entry={entry} />
              ))}
            </Stack>
          </ScrollArea.Autosize>
        </Tabs.Panel>
      </Tabs>
    </Paper>
  );
}
