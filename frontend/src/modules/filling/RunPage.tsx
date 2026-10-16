import {
  Alert,
  Anchor,
  Badge,
  Button,
  Grid,
  Group,
  Loader,
  Paper,
  SegmentedControl,
  SimpleGrid,
  Stack,
  Table,
  Text,
  TextInput,
  Textarea,
  Title,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconArrowLeft, IconFlagCheck, IconX } from "@tabler/icons-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getErrorMessage } from "../../api/client";
import {
  cancelRun,
  consumeBulk,
  finishRun,
  getRun,
  recordScrap,
  runReport,
  scanPackaging,
  type FillingRunDetail,
  type ScrapKind,
  type ScrapReason,
} from "../../api/filling";
import { useAuth } from "../../auth/AuthContext";
import { hasAnyRole } from "../../auth/roles";
import { errorFeedback } from "../../components/scan/feedback";
import { ScanInput, type ScanInputHandle } from "../../components/scan/ScanInput";
import { formatDateTime, formatNumber } from "../../i18n/format";
import { RecordPanel } from "../../workflow/RecordPanel";
import { normalizeDecimal } from "../common/forms";
import { lotPath } from "../inventory/config";
import { LotLabelButton } from "../inventory/LotLabels";
import { ExpiryText, Info, Qty } from "../inventory/shared";
import { ReasonModal } from "../production/shared";
import { fillingOrderPath, LINE_ROLES } from "./config";
import { ReportTable } from "./ReportTable";
import { RunStatusBadge } from "./shared";
import { ft } from "./strings";

/** Hangi fire türünde hangi nedenler hızlı düğme olarak çıkar. */
const REASONS: Record<ScrapKind, ScrapReason[]> = {
  FINISHED: ["LEAK", "UNDERFILL", "OVERFILL", "LABEL_ERROR", "CAP_ERROR", "OTHER"],
  PACKAGING: ["DAMAGED_PACKAGING", "LABEL_ERROR", "CAP_ERROR", "SETUP_LOSS", "OTHER"],
  BULK: ["SETUP_LOSS", "LEAK", "OTHER"],
};

/** Dolum hattı tableti: bulk tüketimi, ambalaj lotu okutma, fire, parti bitişi. */
export function RunPage() {
  const runId = Number(useParams().runId);
  const query = useQuery({ queryKey: ["filling", "run", runId], queryFn: () => getRun(runId) });
  if (query.isLoading) return <Loader />;
  if (query.isError || !query.data)
    return (
      <Alert color="red" variant="light">
        {getErrorMessage(query.error)}
      </Alert>
    );
  return (
    <Grid gutter="lg">
      <Grid.Col span={{ base: 12, lg: 8 }}>
        <Run run={query.data} />
      </Grid.Col>
      <Grid.Col span={{ base: 12, lg: 4 }}>
        <RecordPanel contentType="filling.fillingrun" objectId={query.data.id} />
      </Grid.Col>
    </Grid>
  );
}

function useRunUpdate(runId: number) {
  const queryClient = useQueryClient();
  return (saved: FillingRunDetail) => {
    queryClient.setQueryData(["filling", "run", runId], saved);
    void queryClient.invalidateQueries({ queryKey: ["filling"] });
  };
}

function Run({ run }: { run: FillingRunDetail }) {
  const { user } = useAuth();
  const canFill = hasAnyRole(user, LINE_ROLES);
  const open = run.status === "IN_PROGRESS";
  const editable = canFill && open;
  const [cancelOpen, setCancelOpen] = useState(false);
  const update = useRunUpdate(run.id);
  const report = useQuery({
    queryKey: ["filling", "run-report", run.id],
    queryFn: () => runReport(run.id),
    enabled: run.status === "COMPLETED",
  });

  return (
    <Stack>
      <Anchor component={Link} to={fillingOrderPath(run.order)} size="sm">
        <Group gap={4}>
          <IconArrowLeft size={14} />
          {ft.orderTitle(run.order_number)}
        </Group>
      </Anchor>
      <Group justify="space-between">
        <Group>
          <Title order={2}>{ft.runTitle(run.output_lot_no)}</Title>
          <RunStatusBadge status={run.status} />
        </Group>
        <Group gap="xs">
          <LotLabelButton
            caseFirst
            label={ft.printCaseLabel}
            lot={{
              id: run.output_lot,
              material_type: "FINISHED",
              material_gtin: run.finished_product_gtin,
            }}
          />
          {editable && (
            <Button
              color="red"
              variant="light"
              leftSection={<IconX size={16} />}
              onClick={() => setCancelOpen(true)}
            >
              {ft.cancelRun}
            </Button>
          )}
        </Group>
      </Group>
      <Paper withBorder p="md" radius="md">
        <SimpleGrid cols={{ base: 2, sm: 4 }}>
          <Info label={ft.product}>
            <Text size="sm">{`${run.finished_product_code} - ${run.finished_product_name}`}</Text>
          </Info>
          <Info label={ft.outputLot}>
            <Anchor component={Link} to={lotPath(run.output_lot)} size="sm">
              {`${run.output_lot_no} (${run.output_lot_status_display})`}
            </Anchor>
          </Info>
          <Info label={ft.fill}>
            <Text size="sm">{`${formatNumber(run.fill_quantity)} ${run.fill_unit_code}`}</Text>
          </Info>
          <Info label={ft.plannedUnits}>
            <Text size="sm">{formatNumber(run.planned_units)}</Text>
          </Info>
          <Info label={ft.operator}>
            <Text size="sm">{`${run.operator_name ?? ""} · ${formatDateTime(run.started_at)}`}</Text>
          </Info>
          <Info label={ft.lineLocation}>
            <Text size="sm">{run.line_location_code ?? "—"}</Text>
          </Info>
          {run.good_units !== null && (
            <Info label={ft.goodUnits}>
              <Text size="sm">{formatNumber(run.good_units)}</Text>
            </Info>
          )}
          {run.finished_at && (
            <Info label={ft.finishedAt}>
              <Text size="sm">{`${run.finished_by_name ?? ""} · ${formatDateTime(run.finished_at)}`}</Text>
            </Info>
          )}
        </SimpleGrid>
      </Paper>

      {editable && <BulkForm run={run} onSaved={update} />}
      {editable && <PackagingScan run={run} onSaved={update} />}
      {editable && <ScrapForm run={run} onSaved={update} />}
      {editable && <FinishForm run={run} onSaved={update} />}

      <RecordsTables run={run} />
      {report.data && <ReportTable report={report.data} />}

      <ReasonModal
        opened={cancelOpen}
        title={ft.cancelRunTitle}
        hint={ft.cancelRunHint}
        label={ft.cancelReason}
        confirmLabel={ft.cancelRun}
        submit={(reason) => cancelRun(run.id, reason)}
        onClose={() => setCancelOpen(false)}
        onDone={(saved) => {
          setCancelOpen(false);
          update(saved);
        }}
      />
    </Stack>
  );
}

function ErrorText({ error, testId }: { error: string; testId?: string }) {
  if (!error) return null;
  return (
    <Alert color="red" variant="light" data-testid={testId}>
      {error}
    </Alert>
  );
}

function packagingMaterials(run: FillingRunDetail) {
  return run.packaging.map((line) => ({ id: line.material, code: line.material_code ?? "" }));
}

/** Seçilen (okutulan ya da listeden) lot numarası. */
function ChosenLot({ lotNo }: { lotNo: string }) {
  if (!lotNo) return null;
  return (
    <Text size="sm">
      {`${ft.lotNo}: `}
      <Text span fw={700}>
        {lotNo}
      </Text>
    </Text>
  );
}

function BulkForm({
  run,
  onSaved,
}: {
  run: FillingRunDetail;
  onSaved: (r: FillingRunDetail) => void;
}) {
  const scanRef = useRef<ScanInputHandle>(null);
  const quantityRef = useRef<HTMLInputElement>(null);
  const [lotNo, setLotNo] = useState("");
  const [lotId, setLotId] = useState<number | null>(null);
  const [quantity, setQuantity] = useState("");
  const [error, setError] = useState("");
  const consume = useMutation({
    mutationFn: () =>
      consumeBulk(run.id, {
        ...(lotId ? { lot: lotId } : { lot_no: lotNo.trim() }),
        quantity: normalizeDecimal(quantity),
      }),
    onSuccess: (saved) => {
      notifications.show({ color: "green", message: ft.consumedOk(lotNo || "Bulk") });
      setError("");
      setLotNo("");
      setLotId(null);
      setQuantity("");
      onSaved(saved);
    },
    onError: (err) => {
      setError(getErrorMessage(err));
      errorFeedback();
      scanRef.current?.focus();
    },
  });
  const canSubmit = (lotId !== null || lotNo.trim() !== "") && quantity.trim() !== "";
  return (
    <Paper withBorder p="md" radius="md">
      <Stack>
        <Title order={4}>{`${ft.bulkSection}: ${run.bulk_product_code}`}</Title>
        <Text size="sm" c="dimmed">
          {ft.bulkHint}
        </Text>
        <Group align="flex-start" grow>
          <ScanInput
            ref={scanRef}
            expect="lot"
            expectedMaterial={{ id: run.bulk_product, code: run.bulk_product_code }}
            label={ft.scan}
            placeholder={ft.scanPlaceholder}
            onLot={(lot) => {
              setLotNo(lot.lot_no);
              setLotId(lot.id);
              setError("");
              quantityRef.current?.focus();
            }}
          />
          <TextInput
            ref={quantityRef}
            size="lg"
            label={`${ft.quantity} (${run.bulk_unit})`}
            inputMode="decimal"
            value={quantity}
            onChange={(event) => setQuantity(event.currentTarget.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && canSubmit) consume.mutate();
            }}
          />
          <Button
            size="lg"
            disabled={!canSubmit}
            loading={consume.isPending}
            onClick={() => consume.mutate()}
          >
            {ft.consumeBulk}
          </Button>
        </Group>
        <ChosenLot lotNo={lotNo} />
        <ErrorText error={error} testId="bulk-error" />
        <Text fw={600} size="sm">
          {ft.bulkLots}
        </Text>
        {run.bulk_lots.length === 0 ? (
          <Text size="sm" c="dimmed">
            {ft.noBulk}
          </Text>
        ) : (
          <Table fz="md" highlightOnHover data-testid="bulk-lots">
            <Table.Tbody>
              {run.bulk_lots.map((row) => (
                <Table.Tr
                  key={`${row.lot}-${row.location}`}
                  style={{ cursor: "pointer" }}
                  bg={lotId === row.lot ? "var(--mantine-color-blue-light)" : undefined}
                  onClick={() => {
                    setLotId(row.lot);
                    setLotNo(row.lot_no);
                  }}
                >
                  <Table.Td>{row.lot_no}</Table.Td>
                  <Table.Td>{row.location_code}</Table.Td>
                  <Table.Td>
                    <ExpiryText date={row.expiry_date} />
                  </Table.Td>
                  <Table.Td ta="right">
                    <Qty value={row.quantity} unit={row.unit} />
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        )}
      </Stack>
    </Paper>
  );
}

function PackagingScan({
  run,
  onSaved,
}: {
  run: FillingRunDetail;
  onSaved: (r: FillingRunDetail) => void;
}) {
  const ref = useRef<ScanInputHandle>(null);
  const scan = useMutation({
    mutationFn: (lot: { id: number; lot_no: string }) => scanPackaging(run.id, { lot: lot.id }),
    onSuccess: (saved, lot) => {
      notifications.show({ color: "green", message: ft.scannedOk(lot.lot_no) });
      onSaved(saved);
    },
    // Sunucunun reddi (ör. lot hat başında değil) okutma alanında kırmızı gösterilir.
    onError: (err) => ref.current?.showError(getErrorMessage(err)),
  });
  const scanned = new Set(run.scanned_lots.map((row) => row.lot));
  return (
    <Paper withBorder p="md" radius="md">
      <Stack>
        <Title order={4}>{ft.packagingSection}</Title>
        <Text size="sm" c="dimmed">
          {ft.packagingHint}
        </Text>
        <ScanInput
          ref={ref}
          expect="lot"
          expectedMaterial={packagingMaterials(run)}
          label={ft.scan}
          placeholder={ft.scanPlaceholder}
          disabled={scan.isPending}
          onLot={(lot) => scan.mutate(lot)}
        />
        <Text fw={600} size="sm">
          {ft.lineStock}
        </Text>
        <Table fz="sm" data-testid="line-stock">
          <Table.Tbody>
            {run.line_stock.map((row) => (
              <Table.Tr key={`${row.lot}-${row.location}`}>
                <Table.Td>{row.material_code}</Table.Td>
                <Table.Td>
                  <Group gap="xs">
                    {row.lot_no}
                    {scanned.has(row.lot) && (
                      <Badge size="xs" color="green">
                        {ft.scanned}
                      </Badge>
                    )}
                  </Group>
                </Table.Td>
                <Table.Td ta="right">
                  <Qty value={row.quantity} unit={row.unit} />
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Stack>
    </Paper>
  );
}

function ScrapForm({
  run,
  onSaved,
}: {
  run: FillingRunDetail;
  onSaved: (r: FillingRunDetail) => void;
}) {
  const [kind, setKind] = useState<ScrapKind>("FINISHED");
  const [reason, setReason] = useState<ScrapReason | null>(null);
  const [quantity, setQuantity] = useState("");
  const [lotNo, setLotNo] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const needsLot = kind !== "FINISHED";
  const noteMissing = reason === "OTHER" && !note.trim();
  const save = useMutation({
    mutationFn: () =>
      recordScrap(run.id, {
        kind,
        reason_code: reason!,
        quantity: normalizeDecimal(quantity),
        ...(needsLot ? { lot_no: lotNo.trim() } : {}),
        note: note.trim(),
      }),
    onSuccess: (saved) => {
      notifications.show({ color: "green", message: ft.scrapOk });
      setError("");
      setQuantity("");
      setNote("");
      setReason(null);
      onSaved(saved);
    },
    onError: (err) => setError(getErrorMessage(err)),
  });
  const unit = kind === "BULK" ? run.bulk_unit : "ADET";
  const canSubmit =
    reason !== null && quantity.trim() !== "" && (!needsLot || lotNo.trim() !== "") && !noteMissing;
  return (
    <Paper withBorder p="md" radius="md">
      <Stack>
        <Title order={4}>{ft.scrapSection}</Title>
        <Text size="sm" c="dimmed">
          {ft.scrapHint}
        </Text>
        <SegmentedControl
          size="md"
          aria-label={ft.scrapKindLabel}
          value={kind}
          onChange={(value) => {
            setKind(value as ScrapKind);
            setLotNo("");
            setReason(null);
          }}
          data={(["FINISHED", "PACKAGING", "BULK"] as ScrapKind[]).map((value) => ({
            value,
            label: ft.scrapKind[value],
          }))}
        />
        <Group gap="xs" data-testid="scrap-reasons">
          {REASONS[kind].map((value) => (
            <Button
              key={value}
              size="md"
              variant={reason === value ? "filled" : "default"}
              onClick={() => setReason(value)}
            >
              {ft.scrapReason[value]}
            </Button>
          ))}
        </Group>
        <Group align="flex-end" grow>
          {needsLot && (
            <ScanInput
              key={kind}
              expect="lot"
              expectedMaterial={
                kind === "BULK"
                  ? { id: run.bulk_product, code: run.bulk_product_code }
                  : packagingMaterials(run)
              }
              label={ft.scan}
              placeholder={ft.scanPlaceholder}
              onLot={(lot) => setLotNo(lot.lot_no)}
            />
          )}
          <TextInput
            size="lg"
            label={`${ft.quantity} (${unit})`}
            inputMode={kind === "BULK" ? "decimal" : "numeric"}
            value={quantity}
            onChange={(event) => setQuantity(event.currentTarget.value)}
          />
        </Group>
        {needsLot && <ChosenLot lotNo={lotNo} />}
        <Textarea
          label={ft.scrapNote}
          withAsterisk={reason === "OTHER"}
          error={noteMissing && quantity ? ft.scrapNoteRequired : undefined}
          autosize
          minRows={1}
          value={note}
          onChange={(event) => setNote(event.currentTarget.value)}
        />
        <ErrorText error={error} testId="scrap-error" />
        <Group justify="flex-end">
          <Button
            size="lg"
            color="orange"
            disabled={!canSubmit}
            loading={save.isPending}
            onClick={() => save.mutate()}
          >
            {ft.recordScrap}
          </Button>
        </Group>
      </Stack>
    </Paper>
  );
}

function FinishForm({
  run,
  onSaved,
}: {
  run: FillingRunDetail;
  onSaved: (r: FillingRunDetail) => void;
}) {
  const [goodUnits, setGoodUnits] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const finish = useMutation({
    mutationFn: () => finishRun(run.id, { good_units: Number(goodUnits), note: note.trim() }),
    onSuccess: (saved) => {
      notifications.show({ color: "green", message: ft.finishedOk });
      setError("");
      onSaved(saved);
    },
    onError: (err) => setError(getErrorMessage(err)),
  });
  return (
    <Paper withBorder p="md" radius="md">
      <Stack>
        <Title order={4}>{ft.finishRun}</Title>
        <Text size="sm" c="dimmed">
          {ft.finishRunHint}
        </Text>
        <Group align="flex-end" grow>
          <TextInput
            size="lg"
            label={ft.goodUnits}
            inputMode="numeric"
            value={goodUnits}
            onChange={(event) => setGoodUnits(event.currentTarget.value.replace(/\D/g, ""))}
          />
          <TextInput
            size="lg"
            label={ft.finishNote}
            value={note}
            onChange={(event) => setNote(event.currentTarget.value)}
          />
          <Button
            size="lg"
            color="green"
            leftSection={<IconFlagCheck size={20} />}
            disabled={!goodUnits || Number(goodUnits) <= 0}
            loading={finish.isPending}
            onClick={() => finish.mutate()}
          >
            {ft.finishRun}
          </Button>
        </Group>
        <ErrorText error={error} testId="finish-error" />
      </Stack>
    </Paper>
  );
}

function RecordsTables({ run }: { run: FillingRunDetail }) {
  return (
    <>
      {run.consumptions.length > 0 && (
        <>
          <Title order={4}>{ft.consumptions}</Title>
          <Table.ScrollContainer minWidth={560}>
            <Table striped fz="sm" data-testid="consumptions">
              <Table.Tbody>
                {run.consumptions.map((row) => (
                  <Table.Tr key={row.id}>
                    <Table.Td>{row.kind_display}</Table.Td>
                    <Table.Td>{row.material_code}</Table.Td>
                    <Table.Td>{row.lot_no}</Table.Td>
                    <Table.Td>{row.location_code}</Table.Td>
                    <Table.Td ta="right">
                      <Qty value={row.quantity} unit={row.unit} />
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        </>
      )}
      {run.scraps.length > 0 && (
        <>
          <Title order={4}>{ft.scraps}</Title>
          <Table.ScrollContainer minWidth={560}>
            <Table striped fz="sm" data-testid="scraps">
              <Table.Tbody>
                {run.scraps.map((row) => (
                  <Table.Tr key={row.id}>
                    <Table.Td>{row.kind_display}</Table.Td>
                    <Table.Td>{row.reason_display}</Table.Td>
                    <Table.Td>{row.material_code}</Table.Td>
                    <Table.Td>{row.lot_no ?? "—"}</Table.Td>
                    <Table.Td ta="right">
                      <Qty value={row.quantity} unit={row.unit} />
                    </Table.Td>
                    <Table.Td>{row.note}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        </>
      )}
    </>
  );
}
