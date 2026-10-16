import {
  Alert,
  Anchor,
  Badge,
  Button,
  Card,
  Group,
  Loader,
  SimpleGrid,
  Stack,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getErrorMessage } from "../../api/client";
import {
  getGoLive,
  getReadiness,
  setGoLive,
  type CheckStatus,
  type ReadinessCheck,
} from "../../api/golive";
import { useAuth } from "../../auth/AuthContext";
import { hasAnyRole } from "../../auth/roles";
import { gt } from "./strings";

const COLORS: Record<CheckStatus, string> = { OK: "green", WARNING: "yellow", MISSING: "red" };

function CheckCard({ check }: { check: ReadinessCheck }) {
  const external = check.link.startsWith("/admin/");
  return (
    <Card withBorder padding="sm" data-testid={`check-${check.code}`}>
      <Group justify="space-between" wrap="nowrap" align="flex-start">
        <Text fw={600}>{check.title}</Text>
        <Badge color={COLORS[check.status]} variant="light" style={{ flexShrink: 0 }}>
          {gt.status[check.status]}
        </Badge>
      </Group>
      <Text size="sm" c="dimmed" mt={4}>
        {check.detail}
      </Text>
      {check.items.length > 0 && (
        <Text size="sm" mt={4}>
          {check.items.join(", ")}
          {check.more > 0 && ` ${gt.more(check.more)}`}
        </Text>
      )}
      {check.link &&
        (external ? (
          <Anchor href={check.link} size="sm" mt={6}>
            {gt.open}
          </Anchor>
        ) : (
          <Anchor component={Link} to={check.link} size="sm" mt={6}>
            {gt.open}
          </Anchor>
        ))}
    </Card>
  );
}

function GoLiveCard() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const canEdit = hasAnyRole(user, ["yonetim"]);
  const query = useQuery({ queryKey: ["golive", "go-live"], queryFn: getGoLive });
  const [value, setValue] = useState("");
  useEffect(() => setValue(query.data?.go_live_date ?? ""), [query.data]);

  const save = useMutation({
    mutationFn: (date: string | null) => setGoLive(date),
    onSuccess: () => {
      notifications.show({ color: "green", message: gt.goLiveSaved });
      void queryClient.invalidateQueries({ queryKey: ["golive"] });
    },
    onError: (error) => notifications.show({ color: "red", message: getErrorMessage(error) }),
  });

  return (
    <Card withBorder>
      <Stack gap="xs">
        <Title order={4}>{gt.goLive}</Title>
        <Text size="sm" c="dimmed">
          {gt.goLiveHelp}
        </Text>
        {query.data && (
          <Text size="sm" c={query.data.opening_open ? "green" : "orange"}>
            {query.data.opening_open ? gt.openingOpen : gt.openingClosed}
          </Text>
        )}
        <Group align="flex-end">
          <TextInput
            type="date"
            label={gt.goLive}
            value={value}
            disabled={!canEdit}
            onChange={(event) => setValue(event.currentTarget.value)}
            w={200}
          />
          {canEdit && (
            <>
              <Button
                onClick={() => save.mutate(value || null)}
                loading={save.isPending}
                disabled={!value}
              >
                {gt.goLiveSave}
              </Button>
              {query.data?.go_live_date && (
                <Button variant="default" onClick={() => save.mutate(null)}>
                  {gt.goLiveClear}
                </Button>
              )}
            </>
          )}
        </Group>
      </Stack>
    </Card>
  );
}

export function ReadinessTab() {
  const query = useQuery({ queryKey: ["golive", "readiness"], queryFn: getReadiness });
  const groups = new Map<string, ReadinessCheck[]>();
  for (const check of query.data ?? []) {
    groups.set(check.group, [...(groups.get(check.group) ?? []), check]);
  }

  return (
    <Stack>
      <Text size="sm">{gt.readinessIntro}</Text>
      <Alert variant="light" color="blue" title={gt.guide}>
        <Text size="sm">{gt.guideText}</Text>
        <Anchor component={Link} to="/yardim/gecis" size="sm">
          {gt.guide}
        </Anchor>
      </Alert>
      <GoLiveCard />
      {query.isLoading && <Loader />}
      {query.isError && (
        <Alert color="red" variant="light">
          {getErrorMessage(query.error)}
        </Alert>
      )}
      {[...groups.entries()].map(([group, checks]) => (
        <Stack key={group} gap="xs">
          <Title order={4}>{group}</Title>
          <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }}>
            {checks.map((check) => (
              <CheckCard key={check.code} check={check} />
            ))}
          </SimpleGrid>
        </Stack>
      ))}
    </Stack>
  );
}
