import {
  Alert,
  Anchor,
  Button,
  Group,
  Loader,
  Paper,
  Stack,
  Table,
  Text,
  Title,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconArrowLeft, IconPlus } from "@tabler/icons-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { getErrorMessage } from "../../api/client";
import {
  createVersion,
  getRecipe,
  listVersions,
  saveRecipe,
  setRecipeActive,
  type Recipe,
  type RecipeVersionDetail,
} from "../../api/recipes";
import { useAuth } from "../../auth/AuthContext";
import { hasAnyRole } from "../../auth/roles";
import { formatDateTime, formatNumber } from "../../i18n/format";
import { ActiveBadge } from "../common/ActiveBadge";
import { ConfirmModal } from "../common/ConfirmModal";
import { RecordFormModal } from "../common/RecordFormModal";
import { ct } from "../common/strings";
import { RECIPE_WRITE_ROLES, RECIPES_BASE, recipeFields, versionFields } from "./config";
import { StatusBadge } from "./StatusBadge";
import { rt } from "./strings";

/** Reçete detayı: bilgiler ve sürüm listesi. */
export function RecipePage() {
  const recipeId = Number(useParams().recipeId);
  const { user } = useAuth();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const canWrite = hasAnyRole(user, RECIPE_WRITE_ROLES);
  const [editOpen, setEditOpen] = useState(false);
  const [versionOpen, setVersionOpen] = useState(false);
  const [confirmDeactivate, setConfirmDeactivate] = useState(false);

  const recipe = useQuery({ queryKey: ["recipe", recipeId], queryFn: () => getRecipe(recipeId) });
  const versions = useQuery({
    queryKey: ["recipe", recipeId, "versions"],
    queryFn: () => listVersions(recipeId),
  });

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["recipe", recipeId] });
    void queryClient.invalidateQueries({ queryKey: ["recipes"] });
  };

  const toggleActive = useMutation({
    mutationFn: (active: boolean) => setRecipeActive(recipeId, active),
    onSuccess: refresh,
    onError: (error) => notifications.show({ color: "red", message: getErrorMessage(error) }),
    onSettled: () => setConfirmDeactivate(false),
  });

  if (recipe.isLoading) return <Loader />;
  if (recipe.isError || !recipe.data)
    return (
      <Alert color="red" variant="light">
        {getErrorMessage(recipe.error)}
      </Alert>
    );
  const data = recipe.data;
  const latest = versions.data?.[0];

  return (
    <Stack>
      <Anchor component={Link} to={RECIPES_BASE} size="sm">
        <Group gap={4}>
          <IconArrowLeft size={14} />
          {rt.back}
        </Group>
      </Anchor>
      <Group justify="space-between" align="flex-start">
        <div>
          <Title order={2}>{`${data.code} - ${data.name}`}</Title>
          <Text c="dimmed">{`${rt.product}: ${data.product_code} - ${data.product_name}`}</Text>
        </div>
        <Group>
          <ActiveBadge active={data.is_active} />
          {canWrite && (
            <>
              <Button variant="default" onClick={() => setEditOpen(true)}>
                {ct.edit}
              </Button>
              <Button
                variant="subtle"
                color={data.is_active ? "red" : undefined}
                onClick={() =>
                  data.is_active ? setConfirmDeactivate(true) : toggleActive.mutate(true)
                }
              >
                {data.is_active ? ct.deactivate : ct.activate}
              </Button>
            </>
          )}
        </Group>
      </Group>
      {data.notes && (
        <Paper withBorder p="sm" radius="md">
          <Text size="sm" style={{ whiteSpace: "pre-wrap" }}>
            {data.notes}
          </Text>
        </Paper>
      )}

      <Group justify="space-between" mt="md">
        <Title order={3}>{rt.versions}</Title>
        {canWrite && data.is_active && (
          <Button leftSection={<IconPlus size={16} />} onClick={() => setVersionOpen(true)}>
            {rt.newVersion}
          </Button>
        )}
      </Group>
      {versions.data?.length === 0 && <Text c="dimmed">{rt.noVersions}</Text>}
      {Boolean(versions.data?.length) && (
        <Table.ScrollContainer minWidth={640}>
          <Table striped highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Sürüm</Table.Th>
                <Table.Th>{ct.statusFilter}</Table.Th>
                <Table.Th>{rt.batch}</Table.Th>
                <Table.Th>{rt.changeNote}</Table.Th>
                <Table.Th>{rt.approvedBy}</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {versions.data!.map((version) => (
                <Table.Tr
                  key={version.id}
                  style={{ cursor: "pointer" }}
                  onClick={() => navigate(`${RECIPES_BASE}/${recipeId}/surumler/${version.id}`)}
                >
                  <Table.Td>
                    {`v${version.version_no}`}
                    {version.copied_from_no ? (
                      <Text
                        span
                        size="xs"
                        c="dimmed"
                      >{` (${rt.copiedFrom(version.copied_from_no)})`}</Text>
                    ) : null}
                  </Table.Td>
                  <Table.Td>
                    <StatusBadge status={version.status} />
                  </Table.Td>
                  <Table.Td>{`${formatNumber(version.batch_size)} ${version.batch_unit_code}`}</Table.Td>
                  <Table.Td>{version.change_note}</Table.Td>
                  <Table.Td>
                    {version.approved_by_name
                      ? `${version.approved_by_name}, ${formatDateTime(version.approved_at)}`
                      : ""}
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}

      <RecordFormModal<Recipe>
        opened={editOpen}
        title={`${rt.recipe}: ${data.code}`}
        fields={recipeFields}
        record={data}
        onClose={() => setEditOpen(false)}
        onSubmit={(payload) => saveRecipe(recipeId, payload)}
        onSaved={() => {
          setEditOpen(false);
          refresh();
        }}
      />
      <RecordFormModal<RecipeVersionDetail>
        opened={versionOpen}
        title={rt.newVersion}
        fields={versionFields}
        record={null}
        defaults={
          latest
            ? {
                batch_size: latest.batch_size.replace(/\.?0+$/, ""),
                batch_unit: String(latest.batch_unit),
              }
            : {}
        }
        onClose={() => setVersionOpen(false)}
        onSubmit={(payload) =>
          createVersion(recipeId, payload as Parameters<typeof createVersion>[1])
        }
        onSaved={(version) => {
          setVersionOpen(false);
          refresh();
          navigate(`${RECIPES_BASE}/${recipeId}/surumler/${version.id}`);
        }}
      />
      <ConfirmModal
        opened={confirmDeactivate}
        message={ct.confirmDeactivate(data.code)}
        confirmLabel={ct.deactivate}
        danger
        loading={toggleActive.isPending}
        onConfirm={() => toggleActive.mutate(false)}
        onClose={() => setConfirmDeactivate(false)}
      />
    </Stack>
  );
}
