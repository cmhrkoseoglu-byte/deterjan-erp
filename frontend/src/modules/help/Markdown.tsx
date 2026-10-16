import { Alert, Anchor, Code, Image, List, Stack, Text, Title } from "@mantine/core";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { parseMarkdown } from "./markdown";

// Kılavuzlar için küçük bir Markdown okuyucu: başlık (#, ##, ###), paragraf, madde ve numaralı
// liste, > not kutusu, ![görsel](yol), [bağlantı](yol), **kalın**, `kod`. Kılavuzlar depoda
// yazıldığından yalnızca bu alt küme desteklenir; HTML işlenmez.

const INLINE = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\))/g;

function inline(text: string): ReactNode[] {
  return text.split(INLINE).map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={index}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith("`") && part.endsWith("`") && part.length > 1) {
      return <Code key={index}>{part.slice(1, -1)}</Code>;
    }
    const link = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(part);
    if (link) {
      const [, label, href] = link;
      return href.startsWith("/") && !href.startsWith("/api/") ? (
        <Anchor key={index} component={Link} to={href}>
          {label}
        </Anchor>
      ) : (
        <Anchor key={index} href={href} target="_blank" rel="noreferrer">
          {label}
        </Anchor>
      );
    }
    return part;
  });
}

export function Markdown({ source }: { source: string }) {
  return (
    <Stack gap="sm">
      {parseMarkdown(source).map((block, index) => {
        switch (block.kind) {
          case "h":
            return (
              <Title
                key={index}
                order={(block.level + 1) as 2 | 3 | 4}
                mt={block.level === 1 ? 0 : "sm"}
              >
                {inline(block.text)}
              </Title>
            );
          case "p":
            return <Text key={index}>{inline(block.text)}</Text>;
          case "ul":
          case "ol":
            return (
              <List key={index} type={block.kind === "ol" ? "ordered" : "unordered"} spacing={4}>
                {block.items.map((item, i) => (
                  <List.Item key={i}>{inline(item)}</List.Item>
                ))}
              </List>
            );
          case "note":
            return (
              <Alert key={index} variant="light" color="blue">
                {inline(block.text)}
              </Alert>
            );
          case "img":
            return (
              <figure key={index} style={{ margin: 0 }}>
                <Image
                  src={block.src}
                  alt={block.alt}
                  maw={900}
                  radius="sm"
                  loading="lazy"
                  style={{ border: "1px solid var(--mantine-color-gray-3)" }}
                />
                {block.alt && (
                  <Text component="figcaption" size="sm" c="dimmed" mt={4}>
                    {block.alt}
                  </Text>
                )}
              </figure>
            );
        }
      })}
    </Stack>
  );
}
