import { Button, Stack, Text, Title } from "@mantine/core";
import { IconLock } from "@tabler/icons-react";
import { Link } from "react-router-dom";
import { getErrorRequired } from "../api/client";
import type { RequiredAccess } from "../api/types";
import { describeAccess } from "../auth/access";
import { tr } from "../i18n/tr";

/**
 * "Yetkiniz yok" sayfası (plan §5.9, §8 madde 4). Eksik yetki biliniyorsa (rota korumasının
 * `need`'i ya da 403 yanıtındaki `required`) "Gerekli yetki: Modül › Bölüm (Düzey)" satırı çıkar;
 * birden çok seçenek "ya da" ile birleşir. Başlık eşlik testinin okuduğu metindir; değişmez.
 */
export function ForbiddenPage({
  need,
  error,
}: {
  need?: readonly RequiredAccess[];
  /** 403 yanıtı: gövdesindeki `required` gösterilir. */
  error?: unknown;
}) {
  const items = need && need.length > 0 ? need : getErrorRequired(error);
  const described = items.map(describeAccess).filter((text): text is string => Boolean(text));
  return (
    <Stack align="center" gap="md" py="xl" ta="center">
      <IconLock size={48} stroke={1.4} />
      <Title order={2}>{tr.errors.forbiddenTitle}</Title>
      <Text c="dimmed" maw={480}>
        {tr.errors.forbiddenText}
      </Text>
      {described.length > 0 && (
        <Text fw={500} maw={520} data-testid="required-access">
          {tr.errors.requiredAccess(described.join(" ya da "))}
        </Text>
      )}
      <Button component={Link} to="/" size="md" variant="light">
        {tr.common.backToHome}
      </Button>
    </Stack>
  );
}
