import {
  Alert,
  Anchor,
  Badge,
  Button,
  Group,
  Loader,
  Paper,
  Stack,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { IconSearch } from "@tabler/icons-react";
import { useQueries } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { Paginated, Role } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { hasAnyRole } from "../auth/roles";
import { tr } from "../i18n/tr";
import { menuRoles } from "../layout/menu";
import { ORDER_READ_ROLES } from "../modules/purchasing/config";
import { RECORD_ROUTES } from "../workflow/recordLinks";

const MIN_LENGTH = 2;
const PAGE_SIZE = 5;

type Row = Record<string, unknown> & { id: number; status_display?: string };

interface Source {
  key: keyof typeof tr.search.groups;
  url: string;
  model: string;
  /** Listeyi okuyabilen roller (asıl yetki backend'de; burada boşuna 403 almamak için). */
  roles: readonly Role[];
  title: (row: Row) => string;
  detail: (row: Row) => string;
}

const text = (...parts: unknown[]) => parts.filter(Boolean).join(" · ");

/** Aranan listeler: lot ve belge numaraları (backend `search` süzgeci, ilk 5 kayıt). */
function sources(): Source[] {
  return [
    {
      key: "lots",
      url: "/inventory/lots/",
      model: "inventory.lot",
      roles: menuRoles("inventory"),
      title: (r) => String(r.lot_no),
      detail: (r) => text(`${r.material_code} — ${r.material_name}`, r.supplier_lot_no),
    },
    {
      key: "receipts",
      url: "/inventory/goods-receipts/",
      model: "inventory.goodsreceipt",
      roles: ["depo", "planlama", "yonetim", "satin_alma", "laboratuvar"],
      title: (r) => String(r.number),
      detail: (r) => text(r.supplier_name, r.delivery_note_no),
    },
    {
      key: "productionOrders",
      url: "/production/orders/",
      model: "production.productionorder",
      roles: menuRoles("production"),
      title: (r) => String(r.number),
      detail: (r) => `${r.product_code} — ${r.product_name}`,
    },
    {
      key: "batches",
      url: "/production/batches/",
      model: "production.productionbatch",
      roles: menuRoles("production"),
      title: (r) => String(r.batch_no),
      detail: (r) => text(r.order_number, r.product_name, r.output_lot_no),
    },
    {
      key: "fillingOrders",
      url: "/filling/orders/",
      model: "filling.fillingorder",
      roles: menuRoles("filling"),
      title: (r) => String(r.number),
      detail: (r) => `${r.finished_product_code} — ${r.finished_product_name}`,
    },
    {
      key: "runs",
      url: "/filling/runs/",
      model: "filling.fillingrun",
      roles: menuRoles("filling"),
      title: (r) => String(r.output_lot_no),
      detail: (r) => text(r.order_number, r.finished_product_name),
    },
    {
      key: "salesOrders",
      url: "/sales/orders/",
      model: "sales.salesorder",
      roles: menuRoles("sales"),
      title: (r) => String(r.number),
      detail: (r) => text(r.customer_name, r.customer_po_no),
    },
    {
      key: "shipments",
      url: "/sales/shipments/",
      model: "sales.shipment",
      roles: menuRoles("sales"),
      title: (r) => String(r.number),
      detail: (r) => text(r.customer_name, r.order_number, r.vehicle_plate),
    },
    {
      key: "purchaseOrders",
      url: "/purchasing/orders/",
      model: "purchasing.purchaseorder",
      roles: ORDER_READ_ROLES,
      title: (r) => String(r.number),
      detail: (r) => String(r.supplier_name ?? ""),
    },
    {
      key: "samples",
      url: "/quality/samples/",
      model: "quality.sample",
      roles: menuRoles("quality"),
      title: (r) => String(r.number),
      detail: (r) => text(r.lot_no, r.material_name, r.stage_display),
    },
    {
      key: "returns",
      url: "/returns/",
      model: "returns.customerreturn",
      roles: menuRoles("returns"),
      title: (r) => String(r.number),
      detail: (r) => text(r.customer_name, r.shipment_number),
    },
  ];
}

async function search(url: string, query: string): Promise<Paginated<Row>> {
  const { data } = await api.get<Paginated<Row>>(url, {
    params: { search: query, page_size: PAGE_SIZE },
  });
  return data;
}

/** Lot ve belge numarası araması (üst çubuktaki kutu buraya getirir; `?q=`). */
export function SearchPage() {
  const { user } = useAuth();
  const [params, setParams] = useSearchParams();
  const query = (params.get("q") ?? "").trim();
  const [draft, setDraft] = useState(query);
  // Bu sayfadayken üst çubuktan yeniden aranırsa kutu yeni aramayı göstersin.
  useEffect(() => setDraft(query), [query]);
  const ready = query.length >= MIN_LENGTH;
  const visible = sources().filter((source) => hasAnyRole(user, source.roles));
  const results = useQueries({
    queries: visible.map((source) => ({
      queryKey: ["search", source.key, query],
      queryFn: () => search(source.url, query),
      enabled: ready,
      retry: false,
    })),
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    setParams(draft.trim() ? { q: draft.trim() } : {});
  }

  const loading = ready && results.some((r) => r.isLoading);
  const failed = results.some((r) => r.isError);
  const groups = visible
    .map((source, i) => ({ source, page: results[i]?.data }))
    .filter(({ page }) => page && page.results.length > 0);

  return (
    <Stack gap="lg" maw={900}>
      <Title order={2}>{tr.search.title}</Title>
      <form onSubmit={submit}>
        <Group gap="sm" wrap="nowrap" align="flex-end">
          <TextInput
            flex={1}
            value={draft}
            onChange={(event) => setDraft(event.currentTarget.value)}
            placeholder={tr.search.placeholder}
            aria-label={tr.search.title}
            leftSection={<IconSearch size={18} />}
            autoFocus
          />
          <Button type="submit">{tr.search.submit}</Button>
        </Group>
      </form>
      {!ready && <Text c="dimmed">{tr.search.hint}</Text>}
      {loading && <Loader />}
      {ready && !loading && failed && (
        <Alert color="orange" variant="light">
          {tr.search.failed}
        </Alert>
      )}
      {ready && !loading && groups.length === 0 && <Text c="dimmed">{tr.search.empty}</Text>}
      {groups.map(({ source, page }) => (
        <Paper key={source.key} withBorder p="md">
          <Title order={4} mb="sm">
            {tr.search.groups[source.key]}
          </Title>
          <Stack gap="xs">
            {page!.results.map((row) => (
              <Group key={row.id} justify="space-between" wrap="nowrap" gap="sm">
                <div style={{ minWidth: 0 }}>
                  <Anchor component={Link} to={RECORD_ROUTES[source.model](row.id)} fw={600}>
                    {source.title(row)}
                  </Anchor>
                  <Text size="sm" c="dimmed" truncate>
                    {source.detail(row)}
                  </Text>
                </div>
                {row.status_display && <Badge variant="light">{row.status_display}</Badge>}
              </Group>
            ))}
            {page!.count > page!.results.length && (
              <Text size="sm" c="dimmed">
                {tr.search.more(page!.count - page!.results.length)}
              </Text>
            )}
          </Stack>
        </Paper>
      ))}
    </Stack>
  );
}
