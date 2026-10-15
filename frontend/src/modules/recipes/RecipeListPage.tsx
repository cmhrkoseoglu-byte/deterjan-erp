import {
  Alert,
  Button,
  Group,
  Pagination,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useDebouncedValue } from "@mantine/hooks";
import { IconPlus, IconSearch } from "@tabler/icons-react";
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { getErrorMessage } from "../../api/client";
import { listRecipes, saveRecipe, type Recipe } from "../../api/recipes";
import { useAuth } from "../../auth/AuthContext";
import { hasAnyRole } from "../../auth/roles";
import { ActiveBadge } from "../common/ActiveBadge";
import { RecordFormModal } from "../common/RecordFormModal";
import { ct } from "../common/strings";
import { RECIPE_WRITE_ROLES, RECIPES_BASE, recipeFields } from "./config";
import { rt } from "./strings";

const PAGE_SIZE = 50;

export function RecipeListPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const canWrite = hasAnyRole(user, RECIPE_WRITE_ROLES);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [debounced] = useDebouncedValue(search, 300);
  const [formOpen, setFormOpen] = useState(false);

  const params = { page, page_size: PAGE_SIZE, search: debounced || undefined };
  const list = useQuery({
    queryKey: ["recipes", params],
    queryFn: () => listRecipes(params),
    placeholderData: keepPreviousData,
  });
  const rows = list.data?.results ?? [];
  const pages = Math.max(1, Math.ceil((list.data?.count ?? 0) / PAGE_SIZE));

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={2}>{rt.title}</Title>
        {canWrite && (
          <Button leftSection={<IconPlus size={16} />} onClick={() => setFormOpen(true)}>
            {rt.newRecipe}
          </Button>
        )}
      </Group>
      <TextInput
        aria-label={ct.search}
        placeholder={ct.search}
        leftSection={<IconSearch size={16} />}
        value={search}
        maw={360}
        onChange={(event) => {
          setSearch(event.currentTarget.value);
          setPage(1);
        }}
      />
      {list.isError && (
        <Alert color="red" variant="light">
          {getErrorMessage(list.error)}
        </Alert>
      )}
      <Table.ScrollContainer minWidth={640}>
        <Table striped highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Kod</Table.Th>
              <Table.Th>Ad</Table.Th>
              <Table.Th>{rt.product}</Table.Th>
              <Table.Th>{rt.approvedVersion}</Table.Th>
              <Table.Th>{rt.latestVersion}</Table.Th>
              <Table.Th>{ct.statusFilter}</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {rows.map((row: Recipe) => (
              <Table.Tr
                key={row.id}
                style={{ cursor: "pointer" }}
                onClick={() => navigate(`${RECIPES_BASE}/${row.id}`)}
              >
                <Table.Td>{row.code}</Table.Td>
                <Table.Td>{row.name}</Table.Td>
                <Table.Td>{`${row.product_code} - ${row.product_name}`}</Table.Td>
                <Table.Td>
                  {row.approved_version ? (
                    `v${row.approved_version.version_no}`
                  ) : (
                    <Text size="sm" c="dimmed">
                      {rt.noApproved}
                    </Text>
                  )}
                </Table.Td>
                <Table.Td>{row.latest_version_no ? `v${row.latest_version_no}` : ""}</Table.Td>
                <Table.Td>
                  <ActiveBadge active={row.is_active} />
                </Table.Td>
              </Table.Tr>
            ))}
            {!list.isLoading && rows.length === 0 && (
              <Table.Tr>
                <Table.Td colSpan={6}>
                  <Text c="dimmed" ta="center" py="md">
                    {ct.empty}
                  </Text>
                </Table.Td>
              </Table.Tr>
            )}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
      {pages > 1 && <Pagination value={page} onChange={setPage} total={pages} />}

      <RecordFormModal<Recipe>
        opened={formOpen}
        title={rt.newRecipe}
        fields={recipeFields}
        record={null}
        onClose={() => setFormOpen(false)}
        onSubmit={(payload) => saveRecipe(null, payload)}
        onSaved={(recipe) => {
          setFormOpen(false);
          void queryClient.invalidateQueries({ queryKey: ["recipes"] });
          navigate(`${RECIPES_BASE}/${recipe.id}`);
        }}
      />
    </Stack>
  );
}
