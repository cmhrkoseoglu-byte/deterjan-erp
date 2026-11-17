import {
  Alert,
  Button,
  Group,
  List,
  Loader,
  Modal,
  Stack,
  Text,
  Textarea,
  Title,
} from "@mantine/core";
import { IconAlertCircle, IconAlertTriangle } from "@tabler/icons-react";
import { useMutation } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import {
  saveUserAccess,
  type AccessSaveInput,
  type AccessSaveResult,
  type Cell,
} from "../../../api/access";
import { getErrorCode, getErrorMessage } from "../../../api/client";
import type { Role } from "../../../api/types";
import { describeAccess } from "../../../auth/access";
import { tr } from "../../../i18n/tr";
import { menuDiff } from "./menuDiff";
import { END_REASONS, ua } from "./strings";

const NOTE_MIN = 5;

function rolesText(roles: readonly Role[]): string {
  return roles.length > 0 ? roles.map((role) => tr.roles[role] ?? role).join(", ") : ua.noRoles;
}

function cellText(cell: Cell): string {
  return describeAccess(cell) ?? `${cell.key} (${cell.level})`;
}

function Block({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <Stack gap={4}>
      <Title order={5}>{title}</Title>
      <List size="sm" spacing={2}>
        {items.map((item) => (
          <List.Item key={item}>{item}</List.Item>
        ))}
      </List>
    </Stack>
  );
}

interface Props {
  userId: number;
  superuser: boolean;
  input: Omit<AccessSaveInput, "note" | "dry_run">;
  onClose: () => void;
  onSaved: (result: AccessSaveResult) => void;
  /** Eşzamanlı değişiklikte (`access_changed`) taslağı atıp sayfayı yeniler. */
  onReload: () => void;
}

/**
 * Kaydetme özeti: önce sunucunun ön izlemesi (`dry_run`), sonra zorunlu değişiklik notuyla kayıt
 * (plan §6.1 "Kaydet").
 */
export function SaveSummaryModal({ userId, superuser, input, onClose, onSaved, onReload }: Props) {
  const [note, setNote] = useState("");
  const [noteError, setNoteError] = useState<string | null>(null);
  const preview = useMutation({
    mutationFn: () => saveUserAccess(userId, { ...input, dry_run: true }),
  });
  const save = useMutation({
    mutationFn: () => saveUserAccess(userId, { ...input, note: note.trim() }),
    onSuccess: onSaved,
  });
  const { mutate } = preview;
  useEffect(() => {
    mutate();
  }, [mutate]);

  const error = save.error ?? preview.error;
  const changed = getErrorCode(error) === "access_changed";
  const result = preview.data;

  function confirm() {
    if (note.trim().length < NOTE_MIN) {
      setNoteError(ua.noteRequired);
      return;
    }
    setNoteError(null);
    save.mutate();
  }

  const menu = result ? menuDiff(result, superuser) : null;
  const rolesChanged = result && result.roles.before.join(",") !== result.roles.after.join(",");
  return (
    <Modal opened onClose={onClose} title={ua.summaryTitle} size="lg" closeOnClickOutside={false}>
      <Stack>
        {error && (
          <Alert color="red" variant="light" icon={<IconAlertCircle size={18} />} role="alert">
            <Stack gap="xs">
              <Text size="sm">{getErrorMessage(error)}</Text>
              {changed && (
                <Group>
                  <Button size="xs" color="red" variant="light" onClick={onReload}>
                    {ua.reloadPage}
                  </Button>
                </Group>
              )}
            </Stack>
          </Alert>
        )}
        {preview.isPending && (
          <Group>
            <Loader size="sm" />
            <Text size="sm">{ua.summaryLoading}</Text>
          </Group>
        )}
        {result && (
          <>
            {rolesChanged && (
              <Stack gap={4}>
                <Title order={5}>{ua.rolesChange}</Title>
                <Text size="sm">
                  {rolesText(result.roles.before)} → {rolesText(result.roles.after)}
                </Text>
              </Stack>
            )}
            <Block title={ua.granted} items={result.access.granted.map(cellText)} />
            <Block title={ua.removed} items={result.access.removed.map(cellText)} />
            <Block
              title={ua.ended}
              items={result.overrides.ended.map(
                (row) => `${END_REASONS[row.reason] ?? row.reason}: ${cellText(row)}`,
              )}
            />
            {menu && <Block title={ua.menuAdded} items={menu.added} />}
            {menu && <Block title={ua.menuRemoved} items={menu.removed} />}
            {result.access.granted.length === 0 && result.access.removed.length === 0 && (
              <Text size="sm" c="dimmed">
                {ua.noEffect}
              </Text>
            )}
            {result.warnings.length > 0 && (
              <Alert
                color="orange"
                variant="light"
                icon={<IconAlertTriangle size={18} />}
                title={ua.warnings}
                data-testid="access-warnings"
              >
                <Stack gap={4}>
                  {result.warnings.map((warning) => (
                    <Text size="sm" key={`${warning.code}:${warning.text}`}>
                      {warning.text}
                    </Text>
                  ))}
                </Stack>
              </Alert>
            )}
            <Textarea
              label={ua.note}
              placeholder={ua.notePlaceholder}
              required
              autosize
              minRows={2}
              maxLength={1000}
              value={note}
              error={noteError}
              onChange={(event) => setNote(event.currentTarget.value)}
              data-autofocus
            />
          </>
        )}
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose} disabled={save.isPending}>
            {ua.discard}
          </Button>
          <Button
            onClick={confirm}
            loading={save.isPending}
            disabled={!result || !result.changed || changed}
          >
            {ua.confirmSave}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
