import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as accessApi from "../api/access";
import * as authApi from "../api/auth";
import * as workflowApi from "../api/workflow";
import { userWith } from "../test/fixtures";
import { renderApp } from "../test/render";
import { makeNotification, page } from "../test/workflowFixtures";

vi.mock("../api/access");
vi.mock("../api/auth");
vi.mock("../api/workflow");

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(authApi.fetchCsrf).mockResolvedValue();
  vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("depo"));
  vi.mocked(workflowApi.fetchTasks).mockResolvedValue(page([]));
  vi.mocked(workflowApi.fetchNotifications).mockResolvedValue(page([]));
  vi.mocked(workflowApi.fetchUnreadCount).mockResolvedValue(0);
  vi.mocked(workflowApi.markNotificationsRead).mockResolvedValue(1);
  vi.mocked(accessApi.fetchMyAccess).mockResolvedValue({
    roles: ["depo"],
    is_admin: false,
    entries: [
      { key: "inventory.stock", level: "view", source: "everyone", roles: [], implied: false },
      { key: "production.prep", level: "view", source: "role", roles: ["depo"], implied: false },
      { key: "sales.orders", level: "change", source: "granted", roles: [], implied: false },
      { key: "sales.orders", level: "view", source: "granted", roles: [], implied: true },
    ],
    revoked: [
      { key: "quality.open_records", level: "read", roles: [] },
      { key: "production.prep", level: "change", roles: ["depo"] },
    ],
  });
});

describe("Yetkilerim", () => {
  it("herkes açar; kaynaklar ve kendisi için kapalı açık kayıtlar görünür", async () => {
    renderApp("/yetkilerim");
    expect(await screen.findByRole("heading", { name: "Yetkilerim" })).toBeInTheDocument();
    expect(screen.getByText(/salt okunurdur/)).toBeInTheDocument();
    const production = await screen.findByRole("region", { name: "Üretim" });
    expect(within(production).getByText("Görür · Rolünüzden (Depo)")).toBeInTheDocument();
    expect(within(production).getByText("Değiştirir · Sizin için kaldırıldı")).toBeInTheDocument();
    const sales = screen.getByRole("region", { name: "Sevkiyat" });
    expect(within(sales).getAllByText(/Size özel verildi/)).toHaveLength(2);
    expect(screen.getByText("Görür · Herkese açık")).toBeInTheDocument();
    // Kalite'de başka yetkisi yok ama kapatılan açık kayıtlar görünür.
    const quality = screen.getByRole("region", { name: "Kalite kontrol" });
    expect(
      within(quality).getByText("Sizin için kapalı: Kalite kontrol kayıtları"),
    ).toBeInTheDocument();
    // Not, değiştiren ve tarih yok.
    expect(screen.queryByText(/Admin/)).not.toBeInTheDocument();
  });

  it("admin için açıklama gösterir", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("admin"));
    vi.mocked(accessApi.fetchMyAccess).mockResolvedValue({
      roles: ["admin"],
      is_admin: true,
      entries: [],
      revoked: [],
    });
    renderApp("/yetkilerim");
    expect(
      await screen.findByText(
        "Sistem yöneticisi olarak her ekranı görür ve her işlemi yaparsınız.",
      ),
    ).toBeInTheDocument();
  });

  it("rolsüz kullanıcıya rolü olmadığını yazar", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith());
    vi.mocked(accessApi.fetchMyAccess).mockResolvedValue({
      roles: [],
      is_admin: false,
      entries: [],
      revoked: [],
    });
    renderApp("/yetkilerim");
    expect(await screen.findByText(/Rolünüz yok/)).toBeInTheDocument();
  });

  it("Yetkiniz yok sayfasında Yetkilerimi gör düğmesi Yetkilerim'e gider", async () => {
    renderApp("/sistem");
    expect(await screen.findByText("Yetkiniz yok")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Ana sayfaya dön" })).toHaveAttribute("href", "/");
    expect(screen.getByRole("link", { name: "Yetkilerimi gör" })).toHaveAttribute(
      "href",
      "/yetkilerim",
    );
  });

  it("kullanıcı menüsünde Yetkilerim bağlantısı var", async () => {
    const user = userEvent.setup();
    renderApp("/");
    await user.click(await screen.findByText("Deneme Kullanıcı"));
    expect(await screen.findByRole("menuitem", { name: "Yetkilerim" })).toHaveAttribute(
      "href",
      "/yetkilerim",
    );
  });

  it("Yetkileriniz güncellendi bildirimi Yetkilerim'e götürür", async () => {
    const user = userEvent.setup();
    vi.mocked(workflowApi.fetchNotifications).mockResolvedValue(
      page([
        makeNotification({
          title: "Yetkileriniz güncellendi",
          body: "Rolleriniz ya da yetkileriniz değişti.",
          event_name: "access.updated",
          related: null,
        }),
      ]),
    );
    const { router } = renderApp("/bildirimler");
    await user.click(await screen.findByText("Yetkileriniz güncellendi"));
    await waitFor(() => expect(router.state.location.pathname).toBe("/yetkilerim"));
    expect(workflowApi.markNotificationsRead).toHaveBeenCalledWith([1]);
  });
});
