import {
  Alert,
  Anchor,
  Group,
  Loader,
  Paper,
  SimpleGrid,
  Stack,
  Table,
  Text,
  Title,
} from "@mantine/core";
import { IconArrowLeft } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { getErrorMessage } from "../../api/client";
import { getRecord, type Partner } from "../../api/masterdata";
import { listSalesOrders, listShippedLots } from "../../api/sales";
import { useAuth } from "../../auth/AuthContext";
import { hasAnyRole } from "../../auth/roles";
import { formatDateTime, formatNumber } from "../../i18n/format";
import { RowsTable } from "../filling/FillingPage";
import { ExpiryText, Info } from "../inventory/shared";
import { SALES_BASE, salesOrderPath, SHIPPED_LOT_ROLES, shipmentPath } from "./config";
import { orderColumns } from "./columns";
import { st } from "./strings";

interface Customer extends Partner {
  min_remaining_shelf_life_days: number | null;
}

/** Müşteri kartı: bilgiler, asgari kalan raf ömrü, sipariş geçmişi ve sevk edilen lotlar. */
export function CustomerPage() {
  const customerId = Number(useParams().customerId);
  const navigate = useNavigate();
  const { user } = useAuth();
  const showLots = hasAnyRole(user, SHIPPED_LOT_ROLES);
  const customer = useQuery({
    queryKey: ["sales", "customer", customerId],
    queryFn: () => getRecord<Customer>("customers", customerId),
  });
  const orders = useQuery({
    queryKey: ["sales", "orders", "customer", customerId],
    queryFn: () => listSalesOrders({ customer: customerId, page_size: 100 }),
  });

  if (customer.isLoading) return <Loader />;
  if (customer.isError || !customer.data)
    return (
      <Alert color="red" variant="light">
        {getErrorMessage(customer.error)}
      </Alert>
    );
  const row = customer.data;
  const days = row.min_remaining_shelf_life_days;

  return (
    <Stack>
      <Anchor component={Link} to={`${SALES_BASE}/musteriler`} size="sm">
        <Group gap={4}>
          <IconArrowLeft size={14} />
          {st.tabs.customers}
        </Group>
      </Anchor>
      <Title order={2}>{st.customerCard(row.name)}</Title>
      <Paper withBorder p="md" radius="md">
        <SimpleGrid cols={{ base: 1, xs: 2, sm: 3 }}>
          <Info label={st.code}>
            <Text size="sm">{row.code}</Text>
          </Info>
          <Info label={st.taxNumber}>
            <Text size="sm">{row.tax_number}</Text>
          </Info>
          <Info label={st.shelfLife}>
            <Text size="sm">{days != null ? st.shelfLifeDays(days) : st.noShelfLife}</Text>
          </Info>
          <Info label={st.contact}>
            <Text size="sm">{row.contact_person}</Text>
          </Info>
          <Info label={st.phone}>
            <Text size="sm">{row.phone}</Text>
          </Info>
          <Info label={st.email}>
            <Text size="sm">{row.email}</Text>
          </Info>
          <Info label={st.address}>
            <Text size="sm">{row.address}</Text>
          </Info>
        </SimpleGrid>
      </Paper>
      <Title order={4}>{st.orderHistory}</Title>
      <RowsTable
        testId="customer-orders"
        columns={orderColumns.filter((column) => column.header !== st.customer)}
        rows={orders.data?.results ?? []}
        loading={orders.isLoading}
        error={orders.error}
        onOpen={(order) => navigate(salesOrderPath(order.id))}
      />
      {showLots && <ShippedLots customerId={customerId} />}
    </Stack>
  );
}

/** Müşteriye sevk edilen lotlar (geri çağırmada kime ne gittiği). */
function ShippedLots({ customerId }: { customerId: number }) {
  const query = useQuery({
    queryKey: ["sales", "shipped-lots", customerId],
    queryFn: () => listShippedLots(customerId),
  });
  const rows = query.data?.results ?? [];
  return (
    <Stack gap="xs">
      <Title order={4}>{st.shippedLots}</Title>
      {query.isError && (
        <Alert color="red" variant="light">
          {getErrorMessage(query.error)}
        </Alert>
      )}
      {query.isLoading ? (
        <Loader size="sm" />
      ) : rows.length === 0 ? (
        <Text size="sm" c="dimmed">
          {st.noShippedLots}
        </Text>
      ) : (
        <Table.ScrollContainer minWidth={760}>
          <Table striped fz="sm" data-testid="shipped-lots">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{st.lot}</Table.Th>
                <Table.Th>{st.product}</Table.Th>
                <Table.Th>{st.expiry}</Table.Th>
                <Table.Th ta="right">{st.quantity}</Table.Th>
                <Table.Th>{st.shipmentNumber}</Table.Th>
                <Table.Th>{st.number}</Table.Th>
                <Table.Th>{st.dispatchedAt}</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {rows.map((row) => (
                <Table.Tr key={row.id}>
                  <Table.Td>
                    <Anchor component={Link} to={`/depo/lotlar/${row.lot}`} size="sm">
                      {row.lot_no}
                    </Anchor>
                  </Table.Td>
                  <Table.Td>{`${row.product_code} - ${row.product_name}`}</Table.Td>
                  <Table.Td>
                    <ExpiryText date={row.expiry_date} />
                  </Table.Td>
                  <Table.Td ta="right">{formatNumber(row.quantity)}</Table.Td>
                  <Table.Td>
                    <Anchor component={Link} to={shipmentPath(row.shipment)} size="sm">
                      {row.shipment_number}
                    </Anchor>
                  </Table.Td>
                  <Table.Td>{row.order_number}</Table.Td>
                  <Table.Td>{formatDateTime(row.dispatched_at)}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
    </Stack>
  );
}
