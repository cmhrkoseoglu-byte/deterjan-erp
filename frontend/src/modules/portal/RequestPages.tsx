import {
  ActionIcon,
  Alert,
  Anchor,
  Button,
  Card,
  Group,
  NumberInput,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
  Textarea,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconPlus, IconTrash } from "@tabler/icons-react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { getErrorMessage } from "../../api/client";
import {
  createRequest,
  getRequest,
  listOrderableProducts,
  listRequests,
  withdrawRequest,
  type OrderRequest,
  type RequestLine,
} from "../../api/portal";
import { formatDate, formatDateTime, formatNumber } from "../../i18n/format";
import { orderPath, PORTAL_PATHS, requestPath } from "./config";
import { PAGE_SIZE, useListFilters } from "./filters";
import {
  DataTable,
  Field,
  Fields,
  ListFilters,
  PageHeader,
  Pages,
  QueryState,
  StatusBadge,
  type Column,
} from "./shared";
import { pt } from "./strings";

const REQUEST_STATUSES = [
  { value: "SUBMITTED", label: "Gönderildi" },
  { value: "CONVERTED", label: "Siparişe çevrildi" },
  { value: "REJECTED", label: "Reddedildi" },
  { value: "WITHDRAWN", label: "Geri çekildi" },
];

const linesText = (row: OrderRequest) =>
  row.lines
    .map((line) => `${line.product_code} × ${formatNumber(line.quantity)} ${line.unit_code}`)
    .join(", ");

const requestColumns: Column<OrderRequest>[] = [
  { header: pt.number, render: (row) => row.number },
  { header: pt.date, render: (row) => formatDate(row.created_at) },
  { header: pt.customerPoNo, render: (row) => row.customer_po_no },
  { header: pt.requested, render: (row) => formatDate(row.requested_delivery_date) },
  {
    header: pt.status,
    render: (row) => <StatusBadge status={row.status} label={row.status_display} />,
  },
  { header: pt.product, render: linesText },
];

/** Taleplerim (müşteri). */
export function RequestsPage() {
  const navigate = useNavigate();
  const filters = useListFilters();
  const params = {
    page: filters.page,
    page_size: PAGE_SIZE,
    search: filters.debounced || undefined,
    status: filters.status ?? undefined,
  };
  const query = useQuery({
    queryKey: ["portal", "customer", "requests", params],
    queryFn: () => listRequests(params),
    placeholderData: keepPreviousData,
  });
  return (
    <Stack>
      <PageHeader
        title={pt.menu.requests}
        intro={pt.requestsIntro}
        actions={
          <Button
            component={Link}
            to={PORTAL_PATHS.newRequest}
            leftSection={<IconPlus size={16} />}
          >
            {pt.newRequest}
          </Button>
        }
      />
      <ListFilters filters={filters} statuses={REQUEST_STATUSES} />
      <QueryState isLoading={query.isLoading} error={query.error} />
      {query.data && (
        <DataTable
          testId="portal-requests"
          columns={requestColumns}
          rows={query.data.results}
          rowKey={(row) => row.id}
          onOpen={(row) => navigate(requestPath(row.id))}
        />
      )}
      <Pages count={query.data?.count ?? 0} filters={filters} />
    </Stack>
  );
}

interface DraftLine {
  key: number;
  product: string | null;
  quantity: number | string;
  unit: string | null;
}

let nextKey = 1;
const emptyLine = (): DraftLine => ({ key: nextKey++, product: null, quantity: "", unit: null });

/** Yeni sipariş talebi (müşteri): ürünler, miktar ve birim; fiyat ve stok gösterilmez. */
export function NewRequestPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const products = useQuery({ queryKey: ["portal", "products"], queryFn: listOrderableProducts });
  const [lines, setLines] = useState<DraftLine[]>([emptyLine()]);
  const [wanted, setWanted] = useState("");
  const [poNo, setPoNo] = useState("");
  const [address, setAddress] = useState("");
  const [note, setNote] = useState("");
  const mutation = useMutation({
    mutationFn: () =>
      createRequest({
        requested_delivery_date: wanted || null,
        customer_po_no: poNo.trim(),
        delivery_address: address.trim(),
        note: note.trim(),
        lines: lines.map((line) => ({
          product: Number(line.product),
          quantity: String(line.quantity),
          unit: Number(line.unit),
        })),
      }),
    onSuccess: (created) => {
      notifications.show({ color: "green", message: pt.requestSent(created.number) });
      void queryClient.invalidateQueries({ queryKey: ["portal", "customer", "requests"] });
      navigate(requestPath(created.id));
    },
  });
  const catalog = products.data ?? [];
  const productOptions = catalog.map((p) => ({
    value: String(p.id),
    label: `${p.code} — ${p.name}`,
  }));
  const unitsOf = (productId: string | null) =>
    (catalog.find((p) => String(p.id) === productId)?.units ?? []).map((u) => ({
      value: String(u.id),
      label: u.name || u.code,
    }));
  const complete = lines.every((line) => line.product && line.unit && Number(line.quantity) > 0);

  function update(key: number, change: Partial<DraftLine>) {
    setLines((current) =>
      current.map((line) => (line.key === key ? { ...line, ...change } : line)),
    );
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    mutation.mutate();
  }

  return (
    <form onSubmit={submit}>
      <Stack>
        <PageHeader title={pt.newRequest} intro={pt.newRequestIntro} back={PORTAL_PATHS.requests} />
        <QueryState isLoading={products.isLoading} error={products.error} />
        <Card withBorder>
          <Stack gap="sm">
            {lines.map((line, index) => (
              <Group key={line.key} align="flex-end" wrap="wrap" data-testid="request-line">
                <Select
                  label={index === 0 ? pt.product : undefined}
                  aria-label={pt.product}
                  data={productOptions}
                  value={line.product}
                  onChange={(value) => {
                    const units = unitsOf(value);
                    update(line.key, { product: value, unit: units[0]?.value ?? null });
                  }}
                  searchable
                  w={340}
                />
                <NumberInput
                  label={index === 0 ? pt.quantity : undefined}
                  aria-label={pt.quantity}
                  value={line.quantity}
                  onChange={(value) => update(line.key, { quantity: value })}
                  min={0}
                  decimalScale={4}
                  w={120}
                />
                <Select
                  label={index === 0 ? pt.unit : undefined}
                  aria-label={pt.unit}
                  data={unitsOf(line.product)}
                  value={line.unit}
                  onChange={(value) => update(line.key, { unit: value })}
                  w={140}
                />
                <ActionIcon
                  variant="subtle"
                  color="red"
                  aria-label={pt.removeLine}
                  disabled={lines.length === 1}
                  onClick={() => setLines((current) => current.filter((l) => l.key !== line.key))}
                  mb={4}
                >
                  <IconTrash size={16} />
                </ActionIcon>
              </Group>
            ))}
            <Button
              variant="light"
              leftSection={<IconPlus size={16} />}
              onClick={() => setLines((current) => [...current, emptyLine()])}
              w="fit-content"
            >
              {pt.addLine}
            </Button>
          </Stack>
        </Card>
        <Card withBorder>
          <Stack gap="sm">
            <Group grow align="flex-start">
              <TextInput
                type="date"
                label={pt.requested}
                value={wanted}
                onChange={(event) => setWanted(event.currentTarget.value)}
              />
              <TextInput
                label={pt.customerPoNo}
                value={poNo}
                maxLength={64}
                onChange={(event) => setPoNo(event.currentTarget.value)}
              />
            </Group>
            <Textarea
              label={pt.deliveryAddress}
              description={pt.addressHint}
              value={address}
              autosize
              minRows={2}
              onChange={(event) => setAddress(event.currentTarget.value)}
            />
            <Textarea
              label={pt.note}
              value={note}
              maxLength={1000}
              autosize
              minRows={2}
              onChange={(event) => setNote(event.currentTarget.value)}
            />
          </Stack>
        </Card>
        {mutation.isError && (
          <Alert color="red" variant="light">
            {getErrorMessage(mutation.error)}
          </Alert>
        )}
        <Group justify="flex-end">
          <Button type="submit" loading={mutation.isPending} disabled={!complete}>
            {pt.sendRequest}
          </Button>
        </Group>
      </Stack>
    </form>
  );
}

const lineColumns: Column<RequestLine>[] = [
  { header: pt.product, render: (row) => `${row.product_code} · ${row.product_name}` },
  {
    header: pt.quantity,
    render: (row) => `${formatNumber(row.quantity)} ${row.unit_code}`,
    align: "right",
  },
];

/** Talep sayfası (müşteri): durum, ret gerekçesi, çevrildiği sipariş; karar yoksa geri çekme. */
export function RequestPage() {
  const id = Number(useParams().requestId);
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: ["portal", "customer", "request", id],
    queryFn: () => getRequest(id),
  });
  const withdraw = useMutation({
    mutationFn: () => withdrawRequest(id),
    onSuccess: (row) => {
      queryClient.setQueryData(["portal", "customer", "request", id], row);
      void queryClient.invalidateQueries({ queryKey: ["portal", "customer", "requests"] });
      notifications.show({ color: "green", message: pt.requestWithdrawn });
    },
    onError: (error) => notifications.show({ color: "red", message: getErrorMessage(error) }),
  });
  const row = query.data;
  return (
    <Stack>
      <PageHeader
        title={row ? `${pt.request} ${row.number}` : pt.request}
        back={PORTAL_PATHS.requests}
        actions={
          row?.status === "SUBMITTED" && (
            <Button
              variant="light"
              color="red"
              loading={withdraw.isPending}
              onClick={() => withdraw.mutate()}
            >
              {pt.withdraw}
            </Button>
          )
        }
      />
      <QueryState isLoading={query.isLoading} error={query.error} />
      {row && (
        <>
          <Card withBorder>
            <Fields>
              <Field label={pt.status}>
                <StatusBadge status={row.status} label={row.status_display} />
              </Field>
              <Field label={pt.date}>{formatDateTime(row.created_at)}</Field>
              <Field label={pt.requested}>{formatDate(row.requested_delivery_date)}</Field>
              <Field label={pt.customerPoNo}>{row.customer_po_no}</Field>
              <Field label={pt.deliveryAddress}>{row.delivery_address}</Field>
              <Field label={pt.note}>{row.note}</Field>
            </Fields>
          </Card>
          {row.status === "REJECTED" && (
            <Alert color="red" variant="light" title={pt.rejectedTitle}>
              {row.reject_reason}
            </Alert>
          )}
          {row.status === "CONVERTED" && (
            <Alert color="green" variant="light" title={pt.convertedTitle}>
              {row.order_id ? (
                <Anchor component={Link} to={orderPath(row.order_id)}>
                  {row.order_number}
                </Anchor>
              ) : (
                <Text size="sm">{pt.orderPending(row.order_number ?? "")}</Text>
              )}
            </Alert>
          )}
          <Table.ScrollContainer minWidth={400}>
            <DataTable
              testId="portal-request-lines"
              columns={lineColumns}
              rows={row.lines}
              rowKey={(line) => line.line_no}
            />
          </Table.ScrollContainer>
        </>
      )}
    </Stack>
  );
}
