import { screen, waitFor } from "@testing-library/react";
import { act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as authApi from "../api/auth";
import { api } from "../api/client";
import * as workflowApi from "../api/workflow";
import { FakeWebSocket } from "../test/fakeWebSocket";
import { httpError, page, userWith, withoutAccess } from "../test/fixtures";
import { renderApp } from "../test/render";
import { DENIED_REFRESH_MS, FOCUS_REFRESH_MS } from "./AuthProvider";

vi.mock("../api/auth");
vi.mock("../api/workflow");

/**
 * Oturum tazeleme (plan §5.9, §6.5, §8 madde 11): yetki değişince menü ve sayfa korumaları
 * sayfa yenilenmeden yeni `me` ile çizilir.
 */

const depo = { ...userWith("depo"), id: 7, username: "depo1" };
// Yönetici depo kullanıcısından üretim ekranlarını kaldırdı.
const withoutProduction = withoutAccess(depo, {
  "production.orders": "v",
  "production.prep": "vc",
  "production.batches": "v",
});

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(authApi.fetchCsrf).mockResolvedValue();
  vi.mocked(workflowApi.fetchTasks).mockResolvedValue(page([]));
  vi.mocked(workflowApi.fetchNotifications).mockResolvedValue(page([]));
  vi.mocked(workflowApi.fetchUnreadCount).mockResolvedValue(0);
  // Sayfaların kendi istekleri yanıtsız bekler (ağa çıkmaz).
  api.defaults.adapter = () => new Promise(() => undefined);
});

const defaultAdapter = api.defaults.adapter;

afterEach(() => {
  vi.restoreAllMocks();
  api.defaults.adapter = defaultAdapter;
});

describe("Yetkiniz yok sayfası", () => {
  it("gereken yetkiyi modül › bölüm (düzey) olarak söyler", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(depo);
    renderApp("/uretim/emirler/yeni");
    expect(await screen.findByRole("heading", { name: "Yetkiniz yok" })).toBeInTheDocument();
    expect(
      screen.getByText(
        "Bu sayfayı görme yetkiniz yok. Gerekiyorsa sistem yöneticinizden yetki isteyin.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByTestId("required-access")).toHaveTextContent(
      "Gerekli yetki: Üretim › Üretim emirleri (Değiştirir)",
    );
    expect(screen.getByRole("link", { name: "Ana sayfaya dön" })).toHaveAttribute("href", "/");
  });

  it("yalnız rolü eksik olana sahip olduğu yetkiyi gerekli diye göstermez (/pano)", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("planlama"));
    renderApp("/pano");
    expect(await screen.findByRole("heading", { name: "Yetkiniz yok" })).toBeInTheDocument();
    expect(screen.queryByTestId("required-access")).toBeNull();
  });

  it("rolsüz kullanıcı İSG'yi açamaz, İndirmeler'i açar", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith());
    vi.spyOn(api, "get").mockResolvedValue({ data: page([]) } as never);
    const { router } = renderApp("/isg");
    expect(await screen.findByRole("heading", { name: "Yetkiniz yok" })).toBeInTheDocument();
    expect(screen.getByTestId("required-access")).toHaveTextContent(
      "Gerekli yetki: İSG ve çevre › bölümlerinden biri (Görür)",
    );
    expect(screen.queryByRole("link", { name: "İSG ve çevre" })).not.toBeInTheDocument();
    await act(() => router.navigate("/raporlar/indirmeler"));
    expect(await screen.findByRole("tab", { name: "İndirmeler" })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Panolar" })).not.toBeInTheDocument();
  });
});

describe("oturum tazeleme", () => {
  it("access.changed gelince menü güncellenir, izni kalkan açık sayfa Yetkiniz yok olur", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(depo);
    renderApp("/uretim");
    expect(await screen.findByRole("link", { name: "Üretim" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Yetkiniz yok" })).not.toBeInTheDocument();

    vi.mocked(authApi.fetchMe).mockResolvedValue(withoutProduction);
    const socket = FakeWebSocket.latest();
    act(() => socket.open());
    act(() => socket.receive({ type: "access.changed" }));

    expect(await screen.findByRole("heading", { name: "Yetkiniz yok" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Üretim" })).not.toBeInTheDocument();
    expect(authApi.fetchMe).toHaveBeenCalledTimes(2);
  });

  it("403 permission_denied gelince me bir kez yenilenir (aynı anda gelenler tek yenileme)", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(depo);
    renderApp("/gorevlerim");
    await screen.findByRole("link", { name: "Üretim" });
    expect(authApi.fetchMe).toHaveBeenCalledTimes(1);

    vi.mocked(authApi.fetchMe).mockResolvedValue(withoutProduction);
    const later = Date.now() + DENIED_REFRESH_MS + 1;
    vi.spyOn(Date, "now").mockReturnValue(later);
    const denied = httpError(403, {
      code: "permission_denied",
      detail: "Bu işlem için yetkiniz yok.",
      required: [{ key: "production.prep", level: "change" }],
    });
    api.defaults.adapter = () => Promise.reject(denied);
    await Promise.allSettled([api.get("/production/orders/"), api.get("/production/batches/")]);

    await waitFor(() => expect(authApi.fetchMe).toHaveBeenCalledTimes(2));
    await waitFor(() =>
      expect(screen.queryByRole("link", { name: "Üretim" })).not.toBeInTheDocument(),
    );
    // Yenilemeden hemen sonra gelen 403 yeniden sormaz.
    await Promise.allSettled([api.get("/production/orders/")]);
    expect(authApi.fetchMe).toHaveBeenCalledTimes(2);
  });

  it("pencereye dönünce me yenilenir (son yenilemeden yeterince sonra)", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(depo);
    renderApp("/gorevlerim");
    await screen.findByRole("link", { name: "Üretim" });

    // Hemen dönüş yenilemez.
    act(() => {
      window.dispatchEvent(new Event("focus"));
    });
    expect(authApi.fetchMe).toHaveBeenCalledTimes(1);

    vi.mocked(authApi.fetchMe).mockResolvedValue(withoutProduction);
    vi.spyOn(Date, "now").mockReturnValue(Date.now() + FOCUS_REFRESH_MS + 1);
    act(() => {
      window.dispatchEvent(new Event("focus"));
    });
    await waitFor(() => expect(authApi.fetchMe).toHaveBeenCalledTimes(2));
    await waitFor(() =>
      expect(screen.queryByRole("link", { name: "Üretim" })).not.toBeInTheDocument(),
    );
  });
});
