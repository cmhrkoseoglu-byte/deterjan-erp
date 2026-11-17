import { MantineProvider } from "@mantine/core";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { Link, createMemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { AppRouterProvider } from "../AppRouterProvider";
import { useUnsavedChangesPrompt } from "./useUnsavedChangesPrompt";

function Editor() {
  const [dirty, setDirty] = useState(false);
  const prompt = useUnsavedChangesPrompt(dirty);
  return (
    <>
      <button onClick={() => setDirty(true)}>Değiştir</button>
      <Link to="/duzen?sekme=gecmis">Sekme</Link>
      <Link to="/baska">Başka sayfa</Link>
      {prompt}
    </>
  );
}

function setup() {
  const router = createMemoryRouter(
    [
      { path: "/duzen", element: <Editor /> },
      { path: "/baska", element: <p>Başka sayfa açıldı</p> },
    ],
    { initialEntries: ["/duzen"] },
  );
  render(
    <MantineProvider>
      <AppRouterProvider router={router} />
    </MantineProvider>,
  );
  return router;
}

describe("kaydedilmemiş değişiklik uyarısı", () => {
  it("değişiklik yokken sormaz", async () => {
    const user = userEvent.setup();
    const router = setup();
    await user.click(screen.getByRole("link", { name: "Başka sayfa" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/baska"));
  });

  it("yol değişince sorar, adresin sorgu kısmı değişince sormaz; onaylanınca çıkar", async () => {
    const user = userEvent.setup();
    const router = setup();
    await user.click(screen.getByRole("button", { name: "Değiştir" }));

    await user.click(screen.getByRole("link", { name: "Sekme" }));
    expect(router.state.location.search).toBe("?sekme=gecmis");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    await user.click(screen.getByRole("link", { name: "Başka sayfa" }));
    const dialog = await screen.findByRole("dialog", { name: "Kaydedilmemiş değişiklikler" });
    await user.click(within(dialog).getByRole("button", { name: "Sayfada kal" }));
    expect(router.state.location.pathname).toBe("/duzen");

    await user.click(screen.getByRole("link", { name: "Başka sayfa" }));
    await user.click(
      within(await screen.findByRole("dialog")).getByRole("button", {
        name: "Değişiklikleri at ve çık",
      }),
    );
    expect(await screen.findByText("Başka sayfa açıldı")).toBeInTheDocument();
  });
});
