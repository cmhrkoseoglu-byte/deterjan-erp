import { cleanup, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as authApi from "../api/auth";
import { api } from "../api/client";
import type { Role } from "../api/types";
import * as workflowApi from "../api/workflow";
import { httpError, page, userWith } from "../test/fixtures";
import { renderApp } from "../test/render";

vi.mock("../api/auth");
vi.mock("../api/workflow");

beforeEach(() => {
  vi.mocked(authApi.fetchCsrf).mockResolvedValue();
  vi.mocked(workflowApi.fetchTasks).mockResolvedValue(page([]));
  vi.mocked(workflowApi.fetchNotifications).mockResolvedValue(page([]));
  vi.mocked(workflowApi.fetchUnreadCount).mockResolvedValue(0);
});

afterEach(() => {
  vi.restoreAllMocks();
  window.localStorage.clear();
  document.documentElement.removeAttribute("data-mantine-color-scheme");
});

describe("üst çubuk", () => {
  it.each<[Role[], string, string]>([
    [["yonetim"], "yonetim", "Yönetim merkezi"],
    [["depo", "sevkiyat"], "depo", "Depo paneli"],
    [["laboratuvar"], "laboratuvar", "Laboratuvar paneli"],
    [["admin"], "admin", "Sistem yönetimi"],
  ])("rengi ve panel adı role göre: %j", async (roles, barRole, panel) => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith(...roles));
    renderApp("/gorevlerim");
    expect(await screen.findByText(panel)).toBeInTheDocument();
    expect(screen.getByRole("banner")).toHaveAttribute("data-role", barRole);
    // Sol üstte Inncos logosu: işaret ve INNCOS yazısı (süs; bağlantının adı "Inncos ERP").
    const brand = screen.getByRole("link", { name: "Inncos ERP" });
    expect(brand.querySelectorAll("svg[aria-hidden='true']")).toHaveLength(2);
  });

  it("gece / gündüz düğmesi temayı değiştirir ve seçimi saklar", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("depo"));
    renderApp("/gorevlerim");
    await user.click(await screen.findByRole("button", { name: "Gece temasına geç" }));
    await waitFor(() =>
      expect(document.documentElement).toHaveAttribute("data-mantine-color-scheme", "dark"),
    );
    expect(window.localStorage.getItem("mantine-color-scheme-value")).toBe("dark");
    await user.click(screen.getByRole("button", { name: "Gündüz temasına geç" }));
    await waitFor(() =>
      expect(document.documentElement).toHaveAttribute("data-mantine-color-scheme", "light"),
    );
  });

  it("arama kutusu sonuç sayfasını açar", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("depo"));
    vi.spyOn(api, "get").mockResolvedValue({ data: page([]) } as never);
    const { router } = renderApp("/gorevlerim");
    const box = await screen.findByRole("searchbox", { name: "Lot ya da belge no ara" });
    await user.type(box, "H-261016{Enter}");
    await waitFor(() => expect(router.state.location.pathname).toBe("/ara"));
    expect(router.state.location.search).toBe("?q=H-261016");
    expect(await screen.findByText("Sonuç bulunamadı.")).toBeInTheDocument();
  });
});

describe("arama", () => {
  it("yalnızca rolün okuyabildiği listelerde arar ve sonuçları kayda bağlar", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("dolum"));
    const get = vi.spyOn(api, "get").mockImplementation((async (url: string) => {
      if (url === "/inventory/lots/") {
        return {
          data: {
            ...page([
              {
                id: 5,
                lot_no: "H-261016-001",
                material_code: "LAS",
                material_name: "LAS %96",
                supplier_lot_no: "TED-9",
                status_display: "Serbest",
              },
            ]),
            count: 8,
          },
        };
      }
      return { data: page([]) };
    }) as never);
    renderApp("/ara?q=H-2610");

    const link = await screen.findByRole("link", { name: "H-261016-001" });
    expect(link).toHaveAttribute("href", "/depo/lotlar/5");
    expect(screen.getByText("LAS — LAS %96 · TED-9")).toBeInTheDocument();
    expect(screen.getByText("Lotlar")).toBeInTheDocument();
    expect(screen.getByText("ve 7 kayıt daha")).toBeInTheDocument();
    const urls = get.mock.calls.map(([url]) => url).sort();
    // Dolum: lot, dolum emri ve partisi. Satış, satın alma, kalite, üretim listeleri aranmaz.
    expect(urls).toEqual(["/filling/orders/", "/filling/runs/", "/inventory/lots/"]);
    expect(get).toHaveBeenCalledWith("/inventory/lots/", {
      params: { search: "H-2610", page_size: 5 },
    });
  });

  it("iki karakterden kısa aramada istek atmaz", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("yonetim"));
    const get = vi.spyOn(api, "get");
    renderApp("/ara?q=H");
    expect(await screen.findByText("Aramak için en az 2 karakter yazın.")).toBeInTheDocument();
    expect(get).not.toHaveBeenCalled();
  });
});

describe("giriş ekranı", () => {
  it("PET ERP girişi gibi: ürün fotoğrafları süs, kart başlığı ve alanlar", async () => {
    vi.mocked(authApi.fetchMe).mockRejectedValue(httpError(401));
    renderApp("/login");
    expect(await screen.findByRole("heading", { name: "Hoş geldiniz" })).toBeInTheDocument();
    const photos = [...document.querySelectorAll<HTMLImageElement>('img[src^="/giris/"]')];
    expect(photos).toHaveLength(6);
    expect(photos.every((img) => img.closest('[aria-hidden="true"]'))).toBe(true);
    // Sol üstte Inncos logosu (işaret + INNCOS yazısı) ve "ERP"; süs, sayfa adı gizli başlıkta.
    const brand = screen.getByText("ERP").closest('[aria-hidden="true"]');
    expect(brand?.querySelectorAll("svg")).toHaveLength(2);
    expect(screen.getByLabelText("Kullanıcı adı")).toHaveAttribute(
      "placeholder",
      "ör. ahmet.yilmaz",
    );
    expect(screen.getByRole("button", { name: "Giriş yap" })).toBeInTheDocument();
    expect(screen.getByText("Üretim takip sistemi")).toBeInTheDocument();
  });

  it("şifre göster / gizle", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockRejectedValue(httpError(401));
    renderApp("/login");
    const password = await screen.findByLabelText("Şifre");
    expect(password).toHaveAttribute("type", "password");
    await user.click(screen.getByRole("button", { name: "Şifreyi göster" }));
    expect(password).toHaveAttribute("type", "text");
    expect(screen.getByRole("button", { name: "Şifreyi gizle" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("Beni hatırla yalnız kullanıcı adını saklar ve sonraki açılışta doldurur", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockRejectedValue(httpError(401));
    vi.mocked(authApi.login).mockResolvedValue(userWith("depo"));
    renderApp("/login");
    await user.type(await screen.findByLabelText("Kullanıcı adı"), "ayse");
    await user.type(screen.getByLabelText("Şifre"), "gizli-sifre");
    await user.click(screen.getByLabelText("Beni hatırla"));
    await user.click(screen.getByRole("button", { name: "Giriş yap" }));
    await waitFor(() => expect(authApi.login).toHaveBeenCalled());
    expect(window.localStorage.getItem("inncosKullaniciAdi")).toBe("ayse");
    const stored = Object.keys(window.localStorage).map((k) => window.localStorage.getItem(k));
    expect(stored.some((value) => value?.includes("gizli-sifre"))).toBe(false);

    cleanup();
    vi.mocked(authApi.fetchMe).mockRejectedValue(httpError(401));
    renderApp("/login");
    expect(await screen.findByLabelText("Kullanıcı adı")).toHaveValue("ayse");
    expect(screen.getByLabelText("Beni hatırla")).toBeChecked();
  });

  it("Beni hatırla işaretsizse saklanan kullanıcı adı silinir", async () => {
    const user = userEvent.setup();
    window.localStorage.setItem("inncosKullaniciAdi", "eski");
    vi.mocked(authApi.fetchMe).mockRejectedValue(httpError(401));
    vi.mocked(authApi.login).mockResolvedValue(userWith("depo"));
    renderApp("/login");
    await user.click(await screen.findByLabelText("Beni hatırla"));
    await user.type(screen.getByLabelText("Şifre"), "gizli");
    await user.click(screen.getByRole("button", { name: "Giriş yap" }));
    await waitFor(() => expect(authApi.login).toHaveBeenCalled());
    expect(window.localStorage.getItem("inncosKullaniciAdi")).toBeNull();
  });
});
