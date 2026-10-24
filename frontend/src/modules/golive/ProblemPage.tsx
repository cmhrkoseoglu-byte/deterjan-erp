import { Alert, Anchor, Card, Group, Image, Stack, Text, Title } from "@mantine/core";
import { IconArrowLeft } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { getErrorMessage } from "../../api/client";
import { getProblem, problemScreenshotUrl } from "../../api/golive";
import { useAuth } from "../../auth/AuthContext";
import { hasAnyRole } from "../../auth/roles";
import { safeAppPath } from "../../auth/safePath";
import { formatDateTime } from "../../i18n/format";
import { RecordPanel } from "../../workflow/RecordPanel";
import { gt } from "./strings";

/** Sorun bildirimi: bildiren ve admin görür; admin yorumla yanıtlar. */
export function ProblemPage() {
  const id = Number(useParams().problemId);
  const { user } = useAuth();
  const query = useQuery({ queryKey: ["golive", "problem", id], queryFn: () => getProblem(id) });
  const report = query.data;
  // Bildirimdeki adres yalnızca uygulama içi bir yolsa bağlantıdır; başka siteye giden adres düz
  // yazı kalır (açık yönlendirmeyi önler).
  const pagePath = safeAppPath(report?.page_url);

  return (
    <Stack>
      {hasAnyRole(user, ["admin"]) && (
        <Anchor component={Link} to="/gecis/sorunlar" size="sm">
          <Group gap={4}>
            <IconArrowLeft size={16} />
            {gt.problems.back}
          </Group>
        </Anchor>
      )}
      {query.isError && (
        <Alert color="red" variant="light">
          {getErrorMessage(query.error)}
        </Alert>
      )}
      {report && (
        <>
          <Title order={2}>{report.number}</Title>
          <Card withBorder>
            <Stack gap="xs">
              <Text size="sm" c="dimmed">
                {report.reporter} · {formatDateTime(report.created_at)}
              </Text>
              <Text style={{ whiteSpace: "pre-wrap" }}>{report.description}</Text>
              <Text size="sm">
                {gt.problems.page}: {report.page_title}{" "}
                {pagePath ? (
                  <Anchor component={Link} to={pagePath}>
                    {report.page_url}
                  </Anchor>
                ) : (
                  report.page_url
                )}
              </Text>
              <Text size="xs" c="dimmed">
                {gt.problems.browser}: {report.user_agent} {report.screen}
              </Text>
            </Stack>
          </Card>
          <Title order={4}>{gt.problems.screenshot}</Title>
          {report.has_screenshot ? (
            <Anchor href={problemScreenshotUrl(report.id)} target="_blank">
              <Image
                src={problemScreenshotUrl(report.id)}
                alt={gt.problems.screenshot}
                maw={960}
                radius="sm"
                style={{ border: "1px solid var(--mantine-color-gray-3)" }}
              />
            </Anchor>
          ) : (
            <Text c="dimmed">{gt.problems.noScreenshot}</Text>
          )}
          <RecordPanel contentType="golive.problemreport" objectId={report.id} />
        </>
      )}
    </Stack>
  );
}
