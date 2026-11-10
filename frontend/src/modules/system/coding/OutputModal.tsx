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
import { useEffect, useId, useRef, useState } from "react";
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

/** Tarih alanlarının alt sınırı (backend `invalid_date`). Tarayıcının `min`'i elle yazılan yılı
 * (ör. 0026) form gönderilmeden durdurmaz: kaydetme ve revizyon ekleme de bu sınırla denetlenir. */
const DATE_FLOOR = "2000-01-01";

/** Alt sınırdan önceki tarihin satır içi hatası (boş tarih hata değildir). */
function dateError(value: string): string {
  return value && value < DATE_FLOOR ? cs.dateFloor : "";
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
              <Table.Td style={{ whiteSpace: "nowrap" }}>
                {cs.revNo(revision.revision_no)}
                {/* Revizyonla basılan doküman no (revizyon girildiğindeki). */}
                {revision.doc_code && (
                  <Text size="xs" c="dimmed" ff="monospace">
                    {revision.doc_code}
                  </Text>
                )}
              </Table.Td>
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

/**
 * Bir çıktının doküman kontrol bilgisi: doküman no, ilk yayın tarihi, bant ve revizyonlar. Doküman
 * no ve ilk yayın tarihi ilk revizyona kadar üstteki formda yazılır ve ilk revizyonla birlikte
 * kaydedilir; revizyonu olan çıktıda (`doc_locked`) yalnız yeni revizyonla değişir.
 */
export function OutputModal({ row, onClose, onSaved }: Props) {
  const revisionTitleId = useId();
  // Açık çıktının anahtarı. İstek sürerken pencere kapatılıp başka çıktı açılabilir: geç gelen
  // yanıt ya da hata pencereye yalnız kendi çıktısı hâlâ açıksa yazılır.
  const openKey = useRef<string | undefined>(undefined);
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
  // Revizyonu olan çıktıda yeni revizyonun doküman no ve ilk yayın tarihi (kayıttakilerle gelir).
  const [revisionCode, setRevisionCode] = useState("");
  const [revisionIssue, setRevisionIssue] = useState("");
  const [revisionError, setRevisionError] = useState("");
  const [confirming, setConfirming] = useState(false);

  /** Doküman bölümü kayıttaki değerlere döner; not ve hata boşalır. */
  function resetDocument(saved: OutputDocumentRow) {
    setDocCode(saved.doc_code);
    setFirstIssue(saved.first_issue_date ?? "");
    setActive(saved.is_active);
    setNote("");
    setError("");
  }

  /** Yeni revizyon bölümü boşalır; doküman no ve ilk yayın tarihi kayıttakilerle gelir. */
  function resetRevision(saved: OutputDocumentRow) {
    setRevisionDate(today());
    setApprovedOn(today());
    setApprover("");
    setChangeNote("");
    setFirstNumber(0);
    setRevisionCode(saved.doc_code);
    setRevisionIssue(saved.first_issue_date ?? "");
    setRevisionError("");
    setConfirming(false);
  }

  // Başka çıktı açılınca iki bölüm de kayıttaki değerlere döner. Kayıttan sonra yalnız kaydedilen
  // bölüm sıfırlanır: revizyon eklenince yazılmış doküman alanları ve not, doküman kaydedilince
  // yazılmış revizyon alanları kalır.
  useEffect(() => {
    openKey.current = row?.key;
    if (!row) return;
    resetDocument(row);
    resetRevision(row);
    // Pencere bölümle birlikte kaldırılınca da (ör. tarayıcının geri düğmesi) çıktı açık sayılmaz.
    return () => {
      openKey.current = undefined;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- yalnızca başka çıktı açılınca
  }, [row?.key]);

  /** İsteğin gönderildiği çıktı pencerede hâlâ açık mı? */
  function isOpen(target: OutputDocumentRow): boolean {
    return target.key === openKey.current;
  }

  const locked = row?.doc_locked ?? false;
  const code = docCode.trim().toUpperCase();
  const changes: OutputDocumentUpdate = { note };
  // Kilitli çıktıda doküman no ve ilk yayın tarihi gönderilmez (yeni revizyonla değişir).
  if (row && !locked) {
    if (code !== row.doc_code) changes.doc_code = code;
    if (firstIssue && firstIssue !== (row.first_issue_date ?? "")) {
      changes.first_issue_date = firstIssue;
    }
  }
  if (row && active !== row.is_active) changes.is_active = active;
  const changed = Object.keys(changes).length > 1;

  // İstekler gönderildikleri çıktıyla (`target`) çalışır: yanıt geldiğinde pencere kapanmış ya da
  // başka çıktıya geçmiş olabilir. O zaman liste yine güncellenir, hata bildirimle söylenir.
  const save = useMutation({
    mutationFn: (target: OutputDocumentRow) => updateOutput(target.key, changes),
    onSuccess: (saved, target) => {
      notifications.show({ color: "green", message: cs.outputSaved(saved.label) });
      if (isOpen(target)) resetDocument(saved);
      onSaved(saved);
    },
    onError: (err, target) => {
      const message = getErrorMessage(err);
      if (isOpen(target)) setError(message);
      else
        notifications.show({ color: "red", message: cs.outputSaveFailed(target.label, message) });
    },
  });

  const nextNumber = row?.revisions.length ? row.revisions[0].revision_no + 1 : null;
  const revisionLabel =
    nextNumber === null ? cs.revNo(firstNumber === "" ? 0 : firstNumber) : cs.revNo(nextNumber);
  // Revizyonun doküman no ve ilk yayın tarihi: ilk revizyonda üstte yazılanlar (ikisi de
  // gönderilir), sonra revizyon formundakiler (kayıttakinden farklıysa gönderilir).
  const revisionDocCode = locked ? revisionCode.trim().toUpperCase() : code;
  const revisionFirstIssue = locked ? revisionIssue : firstIssue;
  const addRevision = useMutation({
    mutationFn: (target: OutputDocumentRow) => {
      const body: OutputRevisionCreate = {
        revision_date: revisionDate,
        change_note: changeNote,
        approved_by_name: approver,
        approved_on: approvedOn,
      };
      if (nextNumber === null && firstNumber !== "" && firstNumber !== 0) {
        body.revision_no = firstNumber;
      }
      if (!locked || revisionDocCode !== target.doc_code) body.doc_code = revisionDocCode;
      if (!locked || revisionFirstIssue !== (target.first_issue_date ?? "")) {
        body.first_issue_date = revisionFirstIssue;
      }
      return addOutputRevision(target.key, body);
    },
    onSuccess: (saved, target) => {
      // Eklenen revizyon yanıttaki en yenisidir (pencerede başka çıktı açık olabilir).
      const added = saved.revisions[0];
      notifications.show({
        color: "green",
        message: added
          ? cs.revisionAdded(saved.label, cs.revNo(added.revision_no))
          : cs.outputSaved(saved.label),
      });
      if (isOpen(target)) {
        resetRevision(saved);
        // İlk revizyon doküman no ve ilk yayın tarihini de kaydetti: önceki doküman kaydının hatası
        // artık geçersizdir (yazılmış not ve bant seçimi kalır).
        if (!target.doc_locked) setError("");
      }
      onSaved(saved);
    },
    onError: (err, target) => {
      const message = getErrorMessage(err);
      if (isOpen(target)) {
        setConfirming(false);
        setRevisionError(message);
      } else {
        notifications.show({ color: "red", message: cs.revisionAddFailed(target.label, message) });
      }
    },
  });

  if (!row) return null;
  // Düğmeler yalnız bu çıktının isteğini bekler (kapatılan çıktının isteği sürüyor olabilir).
  const saving = save.isPending && save.variables?.key === row.key;
  const adding = addRevision.isPending && addRevision.variables?.key === row.key;
  // Kilitli çıktıda kayıttaki doküman no ve ilk yayın tarihi gösterilir (yeni revizyonla
  // değişince yenilenir), kilitsizde yazılanlar.
  const shownIssue = locked ? (row.first_issue_date ?? "") : firstIssue;
  // Bant ancak doküman no, ilk yayın tarihi ve revizyon varken açılabilir (kapatmak her zaman).
  const ready = Boolean((locked ? row.doc_code : code) && shownIssue && row.revisions.length);
  const firstIssueError = locked ? "" : dateError(firstIssue);
  // Kilitli çıktıda revizyon formundaki doküman no ve ilk yayın tarihi boş bırakılamaz: boş alan
  // "Revizyonu ekle"nin neden kapalı olduğunu söyler (öneri yer tutucusu dolu sanılmasın).
  const revisionCodeError = locked && !revisionDocCode ? cs.revisionDocRequired : "";
  const revisionIssueError = !locked
    ? ""
    : revisionIssue
      ? dateError(revisionIssue)
      : cs.revisionIssueRequired;
  const revisionDateError = dateError(revisionDate);
  const approvedOnError = dateError(approvedOn);
  const canSave =
    note.trim().length > 0 && changed && !(changes.first_issue_date && firstIssueError) && !saving;
  // Revizyon doküman no ve ilk yayın tarihiyle eklenir (ilk revizyonda üstte yazılanlarla).
  const hasDoc = Boolean(revisionDocCode && revisionFirstIssue);
  const canAdd =
    Boolean(revisionDate && approvedOn && approver.trim() && changeNote.trim()) &&
    hasDoc &&
    !(firstIssueError || revisionIssueError || revisionDateError || approvedOnError) &&
    firstNumber !== "" &&
    !adding;

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
            description={locked ? cs.docLockedHelp : cs.docCodeHelp}
            placeholder={row.suggested_code}
            maxLength={32}
            disabled={locked}
            value={locked ? row.doc_code : docCode}
            onChange={(event) => setDocCode(event.currentTarget.value.toUpperCase())}
          />
          <TextInput
            type="date"
            label={cs.firstIssue}
            min={DATE_FLOOR}
            max={today()}
            disabled={locked}
            value={shownIssue}
            error={firstIssueError || undefined}
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
          <Button disabled={!canSave} loading={saving} onClick={() => save.mutate(row)}>
            {cs.save}
          </Button>
        </Group>

        <Divider />
        <Title order={5}>{cs.revisions}</Title>
        <RevisionTable row={row} />
        <Stack role="group" aria-labelledby={revisionTitleId}>
          <Text id={revisionTitleId} fw={600} size="sm">
            {nextNumber === null ? cs.firstRevision : cs.newRevision(revisionLabel)}
          </Text>
          {!locked && (
            <Text size="sm" c={hasDoc ? "dimmed" : "var(--status-warning)"}>
              {hasDoc ? cs.firstRevisionWithDoc : cs.firstRevisionNeedsDoc}
            </Text>
          )}
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
            {locked && (
              <TextInput
                label={cs.docCode}
                placeholder={row.suggested_code}
                maxLength={32}
                value={revisionCode}
                error={revisionCodeError || undefined}
                onChange={(event) => setRevisionCode(event.currentTarget.value.toUpperCase())}
              />
            )}
            {locked && (
              <TextInput
                type="date"
                label={cs.firstIssue}
                min={DATE_FLOOR}
                max={today()}
                value={revisionIssue}
                error={revisionIssueError || undefined}
                onChange={(event) => setRevisionIssue(event.currentTarget.value)}
              />
            )}
            <TextInput
              type="date"
              label={cs.effectiveDate}
              min={DATE_FLOOR}
              max={today()}
              value={revisionDate}
              error={revisionDateError || undefined}
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
              min={DATE_FLOOR}
              max={revisionDate || today()}
              value={approvedOn}
              error={approvedOnError || undefined}
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
      </Stack>
      <ConfirmModal
        opened={confirming}
        message={cs.revisionConfirm}
        confirmLabel={cs.addRevision}
        loading={adding}
        onConfirm={() => addRevision.mutate(row)}
        onClose={() => setConfirming(false)}
      />
    </Modal>
  );
}
