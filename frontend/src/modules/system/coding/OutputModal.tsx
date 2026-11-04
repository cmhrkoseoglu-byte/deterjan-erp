import {
  Alert,
  Button,
  Divider,
  Group,
  Modal,
  NumberInput,
  SimpleGrid,
  Stack,
  Switch,
  Table,
  Text,
  Textarea,
  TextInput,
  Title,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useMutation } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { getErrorMessage } from "../../../api/client";
import {
  addOutputRevision,
  updateOutput,
  type OutputDocumentRow,
  type OutputDocumentUpdate,
  type OutputRevisionCreate,
} from "../../../api/coding";
import { formatDate } from "../../../i18n/format";
import { ConfirmModal } from "../../common/ConfirmModal";
import { cs } from "./strings";

interface Props {
  row: OutputDocumentRow | null;
  onClose: () => void;
  onSaved: (row: OutputDocumentRow) => void;
}

/** Bugün, `YYYY-MM-DD` (Türkiye saatiyle). */
function today(): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Istanbul" }).format(new Date());
}

function RevisionTable({ row }: { row: OutputDocumentRow }) {
  if (!row.revisions.length) {
    return (
      <Text size="sm" c="dimmed">
        {cs.revisionsEmpty}
      </Text>
    );
  }
  return (
    <Table.ScrollContainer minWidth={620}>
      <Table striped>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>{cs.colRevision}</Table.Th>
            <Table.Th>{cs.colEffective}</Table.Th>
            <Table.Th>{cs.colChange}</Table.Th>
            <Table.Th>{cs.colApprover}</Table.Th>
            <Table.Th>{cs.colEntered}</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {row.revisions.map((revision) => (
            <Table.Tr key={revision.id}>
              <Table.Td style={{ whiteSpace: "nowrap" }}>{cs.revNo(revision.revision_no)}</Table.Td>
              <Table.Td>{formatDate(revision.revision_date)}</Table.Td>
              <Table.Td>
                <Text size="sm">{revision.change_note}</Text>
              </Table.Td>
              <Table.Td>
                <Text size="sm">
                  {revision.approved_by_name} · {formatDate(revision.approved_on)}
                </Text>
              </Table.Td>
              <Table.Td>
                <Text size="xs" c="dimmed">
                  {revision.created_by_name} · {formatDate(revision.created_at)}
                </Text>
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  );
}

/** Bir çıktının doküman kontrol bilgisi: doküman no, ilk yayın tarihi, bant ve revizyonlar. */
export function OutputModal({ row, onClose, onSaved }: Props) {
  const [docCode, setDocCode] = useState("");
  const [firstIssue, setFirstIssue] = useState("");
  const [active, setActive] = useState(false);
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const [revisionDate, setRevisionDate] = useState(today());
  const [approvedOn, setApprovedOn] = useState(today());
  const [approver, setApprover] = useState("");
  const [changeNote, setChangeNote] = useState("");
  const [firstNumber, setFirstNumber] = useState<number | "">(0);
  const [revisionError, setRevisionError] = useState("");
  const [confirming, setConfirming] = useState(false);

  // Kaydedince satır yenilenir: alanlar kayıttaki değerlere döner, notlar boşalır.
  useEffect(() => {
    if (!row) return;
    setDocCode(row.doc_code);
    setFirstIssue(row.first_issue_date ?? "");
    setActive(row.is_active);
    setNote("");
    setError("");
    setRevisionDate(today());
    setApprovedOn(today());
    setApprover("");
    setChangeNote("");
    setFirstNumber(0);
    setRevisionError("");
    setConfirming(false);
  }, [row]);

  const code = docCode.trim().toUpperCase();
  const changes: OutputDocumentUpdate = { note };
  if (row && code !== row.doc_code) changes.doc_code = code;
  if (row && firstIssue && firstIssue !== (row.first_issue_date ?? "")) {
    changes.first_issue_date = firstIssue;
  }
  if (row && active !== row.is_active) changes.is_active = active;
  const changed = Object.keys(changes).length > 1;

  const save = useMutation({
    mutationFn: () => updateOutput(row!.key, changes),
    onSuccess: (saved) => {
      notifications.show({ color: "green", message: cs.outputSaved(saved.label) });
      onSaved(saved);
    },
    onError: (err) => setError(getErrorMessage(err)),
  });

  const nextNumber = row?.revisions.length ? row.revisions[0].revision_no + 1 : null;
  const revisionLabel =
    nextNumber === null ? cs.revNo(firstNumber === "" ? 0 : firstNumber) : cs.revNo(nextNumber);
  const addRevision = useMutation({
    mutationFn: () => {
      const body: OutputRevisionCreate = {
        revision_date: revisionDate,
        change_note: changeNote,
        approved_by_name: approver,
        approved_on: approvedOn,
      };
      if (nextNumber === null && firstNumber !== "" && firstNumber !== 0) {
        body.revision_no = firstNumber;
      }
      return addOutputRevision(row!.key, body);
    },
    onSuccess: (saved) => {
      notifications.show({ color: "green", message: cs.revisionAdded(revisionLabel) });
      onSaved(saved);
    },
    onError: (err) => {
      setConfirming(false);
      setRevisionError(getErrorMessage(err));
    },
  });

  if (!row) return null;
  // Bant ancak doküman no, ilk yayın tarihi ve revizyon varken açılabilir (kapatmak her zaman).
  const ready = Boolean(code && firstIssue && row.revisions.length);
  const canSave = note.trim().length > 0 && changed && !save.isPending;
  const canAdd =
    Boolean(revisionDate && approvedOn && approver.trim() && changeNote.trim()) &&
    firstNumber !== "" &&
    !addRevision.isPending;

  return (
    <Modal opened onClose={onClose} title={cs.outputTitle(row.label)} size="xl">
      <Stack>
        {row.legal && (
          <Alert color="yellow" variant="light">
            {cs.legalHelp}
          </Alert>
        )}
        {row.template_changed && (
          <Alert color="orange" variant="light">
            {cs.templateChangedHelp}
          </Alert>
        )}
        {error && (
          <Alert color="red" variant="light">
            {error}
          </Alert>
        )}
        <SimpleGrid cols={{ base: 1, sm: 2 }}>
          <TextInput
            label={cs.docCode}
            description={cs.docCodeHelp}
            placeholder={row.suggested_code}
            maxLength={32}
            value={docCode}
            onChange={(event) => setDocCode(event.currentTarget.value.toUpperCase())}
          />
          <TextInput
            type="date"
            label={cs.firstIssue}
            max={today()}
            value={firstIssue}
            onChange={(event) => setFirstIssue(event.currentTarget.value)}
          />
        </SimpleGrid>
        <Switch
          label={cs.printBand}
          description={cs.printBandHelp}
          checked={active}
          disabled={!active && !ready}
          onChange={(event) => setActive(event.currentTarget.checked)}
        />
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
          <Button disabled={!canSave} loading={save.isPending} onClick={() => save.mutate()}>
            {cs.save}
          </Button>
        </Group>

        <Divider />
        <Title order={5}>{cs.revisions}</Title>
        <RevisionTable row={row} />
        <Text fw={600} size="sm">
          {nextNumber === null ? cs.firstRevision : cs.newRevision(revisionLabel)}
        </Text>
        {revisionError && (
          <Alert color="red" variant="light">
            {revisionError}
          </Alert>
        )}
        <SimpleGrid cols={{ base: 1, sm: 2 }}>
          {nextNumber === null && (
            <NumberInput
              size="md"
              label={cs.firstRevisionNo}
              description={cs.firstRevisionNoHelp}
              min={0}
              max={99}
              allowDecimal={false}
              allowNegative={false}
              value={firstNumber}
              onChange={(value) => setFirstNumber(value === "" ? "" : Number(value))}
            />
          )}
          <TextInput
            type="date"
            label={cs.effectiveDate}
            max={today()}
            value={revisionDate}
            onChange={(event) => setRevisionDate(event.currentTarget.value)}
          />
          <TextInput
            label={cs.approver}
            maxLength={150}
            value={approver}
            onChange={(event) => setApprover(event.currentTarget.value)}
          />
          <TextInput
            type="date"
            label={cs.approvedOn}
            description={cs.approvalHelp}
            max={revisionDate || today()}
            value={approvedOn}
            onChange={(event) => setApprovedOn(event.currentTarget.value)}
          />
        </SimpleGrid>
        <Textarea
          size="md"
          label={cs.changeNote}
          withAsterisk
          autosize
          minRows={2}
          value={changeNote}
          onChange={(event) => setChangeNote(event.currentTarget.value)}
        />
        <Group justify="flex-end">
          <Button variant="light" disabled={!canAdd} onClick={() => setConfirming(true)}>
            {cs.addRevision}
          </Button>
        </Group>
      </Stack>
      <ConfirmModal
        opened={confirming}
        message={cs.revisionConfirm}
        confirmLabel={cs.addRevision}
        loading={addRevision.isPending}
        onConfirm={() => addRevision.mutate()}
        onClose={() => setConfirming(false)}
      />
    </Modal>
  );
}
