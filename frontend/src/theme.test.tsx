import { Badge, Group, MantineProvider } from "@mantine/core";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { theme } from "./theme";

describe("tema", () => {
  it("durum etiketi dar satır ya da sütunda kısalmaz", () => {
    render(
      <MantineProvider theme={theme}>
        <Group wrap="nowrap" w={80}>
          <span>Uzun bir lot açıklaması</span>
          <Badge>Analiz bekliyor</Badge>
        </Group>
      </MantineProvider>,
    );
    expect(screen.getByText("Analiz bekliyor").closest(".mantine-Badge-root")).toHaveStyle({
      flexShrink: "0",
      minWidth: "max-content",
    });
  });
});
