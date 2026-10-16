import { Badge, Grid, NavLink, Paper, Stack, Text, Title } from "@mantine/core";
import { Navigate, useNavigate, useParams } from "react-router-dom";
import { useAuth } from "../../auth/AuthContext";
import { tr } from "../../i18n/tr";
import { GUIDES } from "./guides";
import { Markdown } from "./Markdown";

/** Yardım: rol bazında kısa kullanım kılavuzları ve sayım günü planı (`/yardim/<kılavuz>`). */
export function HelpPage() {
  const { guide } = useParams();
  const { user } = useAuth();
  const navigate = useNavigate();
  const roles = user?.roles ?? [];
  const mine = GUIDES.filter((g) => g.roles.some((role) => roles.includes(role)));
  const others = GUIDES.filter((g) => !mine.includes(g));
  const current = GUIDES.find((g) => g.slug === (guide ?? (mine[0] ?? GUIDES[0]).slug));
  if (!current) return <Navigate to="/yardim" replace />;

  const item = (g: (typeof GUIDES)[number]) => (
    <NavLink
      key={g.slug}
      label={g.title}
      active={g.slug === current.slug}
      onClick={() => navigate(`/yardim/${g.slug}`)}
      style={{ borderRadius: 8 }}
    />
  );

  return (
    <Stack>
      <Title order={2}>{tr.menu.help}</Title>
      <Grid>
        <Grid.Col span={{ base: 12, md: 3 }}>
          <Paper withBorder p="xs">
            {mine.length > 0 && (
              <>
                <Text size="xs" c="dimmed" px="sm" pt={4}>
                  {tr.help.mine}
                </Text>
                {mine.map(item)}
                <Text size="xs" c="dimmed" px="sm" pt="sm">
                  {tr.help.others}
                </Text>
              </>
            )}
            {others.map(item)}
          </Paper>
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 9 }}>
          <Paper withBorder p="lg">
            {mine.includes(current) && (
              <Badge variant="light" mb="sm">
                {tr.help.yourRole}
              </Badge>
            )}
            <Markdown source={current.content} />
          </Paper>
        </Grid.Col>
      </Grid>
    </Stack>
  );
}
