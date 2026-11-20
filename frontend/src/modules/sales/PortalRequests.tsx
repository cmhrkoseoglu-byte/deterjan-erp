// Sevkiyat > Portal talepleri (docs/plan/musteri-siparis-takibi.md §4.4): müşterilerin portaldan
// gönderdiği sipariş talepleri. Satış siparişleri: Görür ile okunur; siparişe çevirme ve reddetme
// Değiştirir ister (asıl denetim sunucuda).
import {
  Alert,
  Anchor,
  Badge,
  Button,
  Card,
  Group,
  Loader,
  Modal,
  SegmentedControl,
  SimpleGrid,
  Stack,
  Table,
  Text,
  Textarea,
  Title,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconArrowLeft } from "@tabler/icons-react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { getErrorMessage } from "../../api/client";
import {
  convertRequest,
  getStaffRequest,
  listStaffRequests,
  rejectRequest,
  type RequestStatus,
  type StaffOrderRequest,
} from "../../api/portal";
import { useCan } from "../../auth/access";
import { PERM } from "../../auth/access.gen";
import { formatDate, formatDateTime, formatNumber } from "../../i18n/format";
import { RecordPanel } from "../../workflow/RecordPanel";
import { SALES_BASE, salesOrderPath } from "./config";

const PORTAL_REQUESTS_PATH = `${SALES_BASE}/portal-talepleri`;
const requestPath = (id: number) => `${PORTAL_REQUESTS_PATH}/${id}`;

const t = {
  intro:
    "Müşterilerin portaldan gönderdiği sipariş talepleri. Talep sipariş değildir: siparişe çevirince taslak sipariş açılır, fiyat ve termin taslakta girilir.",
  open: "Karar bekleyen",
  all: "Hepsi",
  number: "Talep no",
  customer: "Müşteri",
  date: "Gönderim",
  requested: "İstenen teslim",
  poNo: "Müşteri sipariş no",
  status: "Durum",
  lines: "Ürünler",
  none: "Talep yok.",
  sentBy: "Gönderen",
  address: "Teslim adresi",
  note: "Not",
  decidedBy: "Karar veren",
  product: "Ürün",
  quantity: "Miktar",
  convert: "Siparişe çevir",
  reject: "Reddet",
  rejectTitle: "Talebi reddet",
  rejectHint: "Gerekçe müşteriye portalda görünür.",
  reason: "Gerekçe",
  cancel: "Vazgeç",
  converted: (number: string) => `Taslak sipariş açıldı: ${number}`,
  rejected: "Talep reddedildi.",
  order: "Sipariş",
  rejectReason: "Ret gerekçesi",
  back: "Portal talepleri",
};

const STATUS_COLOR: Record<RequestStatus, string> = {
  SUBMITTED: "blue",
  CONVERTED: "green",
  REJECTED: "red",
  WITHDRAWN: "gray",
};

function RequestStatusBadge({ row }: { row: StaffOrderRequest }) {
  return (
    <Badge variant="light" color={STATUS_COLOR[row.status]}>
      {row.status_display}
    </Badge>
  );
}

const linesText = (row: StaffOrderRequest) =>
  row.lines
    .map((line) => `${line.product_code} × ${formatNumber(line.quantity)} ${line.unit_code}`)
    .join(", ");

/** Sevkiyat > Portal talepleri: liste (varsayılan karar bekleyenler). */
export function PortalRequestsTab() {
  const navigate = useNavigate();
  const [scope, setScope] = useState<"open" | "all">("open");
  const params = { page_size: 100, status: scope === "open" ? "SUBMITTED" : undefined };
  const query = useQuery({
    queryKey: ["portal", "staff", "requests", params],
    queryFn: () => listStaffRequests(params),
    placeholderData: keepPreviousData,
  });
  const rows = query.data?.results ?? [];
  return (
    <Stack>
      <Text size="sm" c="dimmed">
        {t.intro}
      </Text>
      <SegmentedControl
        value={scope}
        onChange={(value) => setScope(value as "open" | "all")}
        data={[
          { value: "open", label: t.open },
          { value: "all", label: t.all },
        ]}
        w="fit-content"
      />
      {query.isError && (
        <Alert color="red" variant="light">
          {getErrorMessage(query.error)}
        </Alert>
      )}
      {query.isLoading && <Loader size="sm" />}
      {query.isSuccess && rows.length === 0 && (
        <Text size="sm" c="dimmed">
          {t.none}
        </Text>
      )}
      {rows.length > 0 && (
        <Table.ScrollContainer minWidth={760}>
          <Table striped highlightOnHover data-testid="portal-requests-staff">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{t.number}</Table.Th>
                <Table.Th>{t.customer}</Table.Th>
                <Table.Th>{t.date}</Table.Th>
                <Table.Th>{t.requested}</Table.Th>
                <Table.Th>{t.status}</Table.Th>
                <Table.Th>{t.lines}</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {rows.map((row) => (
                <Table.Tr
                  key={row.id}
                  style={{ cursor: "pointer" }}
                  onClick={() => navigate(requestPath(row.id))}
                >
                  <Table.Td>{row.number}</Table.Td>
                  <Table.Td>
                    {row.customer_code} — {row.customer_name}
                  </Table.Td>
                  <Table.Td>{formatDateTime(row.created_at)}</Table.Td>
                  <Table.Td>{formatDate(row.requested_delivery_date)}</Table.Td>
                  <Table.Td>
                    <RequestStatusBadge row={row} />
                  </Table.Td>
                  <Table.Td>{linesText(row)}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
    </Stack>
  );
}

function Info({ label, children }: { label: string; children: ReactNode }) {
  return (
    <Stack gap={0}>
      <Text size="xs" c="dimmed">
        {label}
      </Text>
      <Text size="sm">{children || "—"}</Text>
    </Stack>
  );
}

/** Portal talebi sayfası: ayrıntı, siparişe çevirme ve reddetme (Değiştirir), geçmiş ve yorumlar. */
export function PortalRequestPage() {
  const id = Number(useParams().requestId);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { can } = useCan();
  const writer = can(PERM.SALES_ORDERS, "change");
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const key = ["portal", "staff", "request", id];
  const query = useQuery({ queryKey: key, queryFn: () => getStaffRequest(id) });
  const reload = () => queryClient.invalidateQueries({ queryKey: ["portal", "staff"] });
  const convert = useMutation({
    mutationFn: () => convertRequest(id),
    onSuccess: (row) => {
      notifications.show({ color: "green", message: t.converted(row.order_number ?? "") });
      void reload();
      if (row.sales_order) navigate(salesOrderPath(row.sales_order));
    },
    onError: (error) => notifications.show({ color: "red", message: getErrorMessage(error) }),
  });
  const reject = useMutation({
    mutationFn: () => rejectRequest(id, reason.trim()),
    onSuccess: (row) => {
      queryClient.setQueryData(key, row);
      setRejecting(false);
      notifications.show({ color: "green", message: t.rejected });
      void reload();
    },
  });
  const row = query.data;
  if (query.isLoading) return <Loader />;
  if (!row)
    return (
      <Alert color="red" variant="light">
        {getErrorMessage(query.error)}
      </Alert>
    );
  const open = row.status === "SUBMITTED";
  return (
    <Stack>
      <Anchor component={Link} to={PORTAL_REQUESTS_PATH} size="sm">
        <Group gap={4}>
          <IconArrowLeft size={14} />
          {t.back}
        </Group>
      </Anchor>
      <Group justify="space-between">
        <Group>
          <Title order={2}>{row.number}</Title>
          <RequestStatusBadge row={row} />
        </Group>
        {writer && open && (
          <Group>
            <Button variant="light" color="red" onClick={() => setRejecting(true)}>
              {t.reject}
            </Button>
            <Button loading={convert.isPending} onClick={() => convert.mutate()}>
              {t.convert}
            </Button>
          </Group>
        )}
      </Group>
      <Card withBorder>
        <SimpleGrid cols={{ base: 1, xs: 2, sm: 3 }}>
          <Info label={t.customer}>
            {row.customer_code} — {row.customer_name}
          </Info>
          <Info label={t.sentBy}>
            {row.created_by_name} · {formatDateTime(row.created_at)}
          </Info>
          <Info label={t.requested}>{formatDate(row.requested_delivery_date)}</Info>
          <Info label={t.poNo}>{row.customer_po_no}</Info>
          <Info label={t.address}>{row.delivery_address}</Info>
          <Info label={t.note}>{row.note}</Info>
          {row.decided_by_name && (
            <Info label={t.decidedBy}>
              {row.decided_by_name} · {formatDateTime(row.decided_at)}
            </Info>
          )}
          {row.sales_order && (
            <Info label={t.order}>
              <Anchor component={Link} to={salesOrderPath(row.sales_order)}>
                {row.order_number}
              </Anchor>
            </Info>
          )}
          {row.reject_reason && <Info label={t.rejectReason}>{row.reject_reason}</Info>}
        </SimpleGrid>
      </Card>
      <Table.ScrollContainer minWidth={400}>
        <Table striped data-testid="portal-request-staff-lines">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{t.product}</Table.Th>
              <Table.Th ta="right">{t.quantity}</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {row.lines.map((line) => (
              <Table.Tr key={line.line_no}>
                <Table.Td>
                  {line.product_code} · {line.product_name}
                </Table.Td>
                <Table.Td ta="right">
                  {formatNumber(line.quantity)} {line.unit_code}
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
      <RecordPanel contentType="portal.orderrequest" objectId={row.id} />
      <Modal opened={rejecting} onClose={() => setRejecting(false)} title={t.rejectTitle}>
        <Stack>
          <Textarea
            label={t.reason}
            description={t.rejectHint}
            value={reason}
            onChange={(event) => setReason(event.currentTarget.value)}
            autosize
            minRows={3}
            maxLength={1000}
          />
          {reject.isError && (
            <Alert color="red" variant="light">
              {getErrorMessage(reject.error)}
            </Alert>
          )}
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setRejecting(false)}>
              {t.cancel}
            </Button>
            <Button
              color="red"
              loading={reject.isPending}
              disabled={!reason.trim()}
              onClick={() => reject.mutate()}
            >
              {t.reject}
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}
