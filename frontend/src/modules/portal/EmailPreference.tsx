import { Alert, Card, Loader, Stack, Switch, Text, Title } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import * as portalApi from "../../api/portal";
import { getErrorMessage } from "../../api/client";
import { useAuth } from "../../auth/AuthContext";
import { SecurityPage } from "../security/SecurityPage";
import { portalKind } from "./config";
import { pt } from "./strings";

const PREF_KEY = ["portal", "email-preference"] as const;

/** Müşteri yetkilisinin sipariş ve sevk e-postası tercihi (docs/plan/musteri-siparis-takibi.md §4.5). */
export function EmailPreferenceCard() {
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: PREF_KEY, queryFn: portalApi.fetchEmailPreference });
  const mutation = useMutation({
    mutationFn: portalApi.setEmailPreference,
    onSuccess: (data) => {
      queryClient.setQueryData(PREF_KEY, data);
      notifications.show({
        color: "green",
        message: data.enabled ? pt.emailOn : pt.emailOff,
      });
    },
    onError: (error) => notifications.show({ color: "red", message: getErrorMessage(error) }),
  });

  return (
    <Card withBorder>
      <Stack gap="xs">
        <Title order={4}>{pt.emailTitle}</Title>
        <Text size="sm" c="dimmed">
          {pt.emailIntro}
        </Text>
        {query.isLoading && <Loader size="sm" />}
        {query.isError && <Alert color="red">{getErrorMessage(query.error)}</Alert>}
        {query.data && (
          <>
            {query.data.email ? (
              <Text size="sm">
                {pt.emailAddress}: <b>{query.data.email}</b>
              </Text>
            ) : (
              <Alert color="yellow">{pt.emailMissing}</Alert>
            )}
            <Switch
              label={pt.emailSwitch}
              checked={query.data.enabled}
              disabled={mutation.isPending || !query.data.email}
              onChange={(event) => mutation.mutate(event.currentTarget.checked)}
            />
          </>
        )}
      </Stack>
    </Card>
  );
}

/** Portalın Güvenlik sayfası: ortak güvenlik ayarları; müşteride e-posta tercihi de. */
export function PortalSecurityPage() {
  const { user } = useAuth();
  return (
    <Stack maw={760}>
      <SecurityPage />
      {/* Geçici şifre değişmeden başka istek açılmaz; kart sonra görünür. */}
      {portalKind(user) === "customer" && !user?.password_change_required && (
        <EmailPreferenceCard />
      )}
    </Stack>
  );
}
