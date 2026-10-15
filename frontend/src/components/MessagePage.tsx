import { Button, Stack, Text, Title } from "@mantine/core";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { tr } from "../i18n/tr";

/** Hata/bilgi sayfaları için ortak düzen. */
export function MessagePage({
  icon,
  title,
  text,
  showHomeLink = true,
}: {
  icon?: ReactNode;
  title: string;
  text: string;
  showHomeLink?: boolean;
}) {
  return (
    <Stack align="center" gap="md" py="xl" ta="center">
      {icon}
      <Title order={2}>{title}</Title>
      <Text c="dimmed" maw={480}>
        {text}
      </Text>
      {showHomeLink && (
        <Button component={Link} to="/" size="md" variant="light">
          {tr.common.backToHome}
        </Button>
      )}
    </Stack>
  );
}
