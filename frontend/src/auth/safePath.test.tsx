import { screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as authApi from "../api/auth";
import * as workflowApi from "../api/workflow";
import { page, userWith } from "../test/fixtures";
import { renderApp } from "../test/render";
import { safeAppPath } from "./safePath";

vi.mock("../api/auth");
vi.mock("../api/workflow");

beforeEach(() => {
  vi.mocked(authApi.fetchCsrf).mockResolvedValue();
  vi.mocked(workflowApi.fetchTasks).mockResolvedValue(page([]));
  vi.mocked(workflowApi.fetchNotifications).mockResolvedValue(page([]));
  vi.mocked(workflowApi.fetchUnreadCount).mockResolvedValue(0);
});

// Başka siteye ya da uygulama dışına çözülebilecek adresler.
const UNSAFE = [
  "//kotu.example/giris",
  "/\\kotu.example",
  "/\\\\kotu.example",
  "/\t/kotu.example",
  "/\n/kotu.example",
  "https://kotu.example",
  "javascript:alert(1)",
  "depo",
  "",
];

describe("uygulama içi yol denetimi", () => {
  it.each(UNSAFE)("reddeder: %j", (value) => {
    expect(safeAppPath(value)).toBeNull();
  });

  it("uygulama içi yolu sorgu ve çapasıyla korur", () => {
    expect(safeAppPath("/depo")).toBe("/depo");
    expect(safeAppPath("/raporlar/panolar?kod=yonetim#bugun")).toBe(
      "/raporlar/panolar?kod=yonetim#bugun",
    );
    expect(safeAppPath(null)).toBeNull();
  });
});

describe("girişten sonra dönüş adresi", () => {
  it.each(["//kotu.example/giris", "/\\kotu.example", "https://kotu.example"])(
    "uygulama dışı %j yerine ana sayfaya döner",
    async (next) => {
      vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("depo"));
      const { router } = renderApp(`/login?next=${encodeURIComponent(next)}`);
      await waitFor(() => expect(router.state.location.pathname).toBe("/"));
      expect(await screen.findByRole("heading", { name: "Görevlerim" })).toBeInTheDocument();
    },
  );

  it("uygulama içi adrese döner", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("depo"));
    const { router } = renderApp(`/login?next=${encodeURIComponent("/depo?sekme=lot")}`);
    await waitFor(() => expect(router.state.location.pathname).toBe("/depo"));
    expect(router.state.location.search).toBe("?sekme=lot");
  });
});
