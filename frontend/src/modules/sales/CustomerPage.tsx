import { Alert, Anchor, Group, Loader, Paper, SimpleGrid, Stack, Text, Title } from "@mantine/core";
import { IconArrowLeft } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { getErrorMessage } from "../../api/client";
import { getRecord, type Partner } from "../../api/masterdata";
import { listSalesOrders } from "../../api/sales";
import { RowsTable } from "../filling/FillingPage";
import { Info } from "../inventory/shared";
import { SALES_BASE, salesOrderPath } from "./config";
import { orderColumns } from "./columns";
import { st } from "./strings";

interface Customer extends Partner {
  min_remaining_shelf_life_days: number | null;
}

/** Müşteri kartı: bilgiler, asgari kalan raf ömrü ve sipariş geçmişi (sevk edilen lotlar 3.2). */
export function CustomerPage() {
  const customerId = Number(useParams().customerId);
  const navigate = useNavigate();
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
    </Stack>
  );
}
