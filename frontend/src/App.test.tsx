import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AxiosError, AxiosHeaders } from "axios";
import { act } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as authApi from "./api/auth";
import * as workflowApi from "./api/workflow";
import { api } from "./api/client";
import type { CurrentUser } from "./api/types";
import { renderApp } from "./test/render";

vi.mock("./api/auth");
vi.mock("./api/workflow");

const depoUser: CurrentUser = {
  id: 7,
  username: "depo1",
  full_name: "Ayşe Yılmaz",
  email: "",
  roles: ["depo"],
  is_superuser: false,
  otp_enabled: false,
  password_change_required: false,
  otp_setup_required: false,
  field_device: false,
  idle_timeout_seconds: 3600,
};

function httpError(status: number, data: unknown = {}) {
  const config = { headers: new AxiosHeaders() };
  return new AxiosError("hata", String(status), config, null, {
    status,
    statusText: "",
    headers: {},
    config,
    data,
  });
}

describe("uygulama akışı", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(authApi.fetchCsrf).mockResolvedValue();
    const empty = { count: 0, next: null, previous: null, results: [] };
    vi.mocked(workflowApi.fetchTasks).mockResolvedValue(empty);
    vi.mocked(workflowApi.fetchNotifications).mockResolvedValue(empty);
    vi.mocked(workflowApi.fetchUnreadCount).mockResolvedValue(0);
  });

  it("oturum yoksa giriş ekranına yönlendirir", async () => {
    vi.mocked(authApi.fetchMe).mockRejectedValue(httpError(401));
    const { router } = renderApp("/depo");
    expect(await screen.findByRole("button", { name: "Giriş yap" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/login");
    expect(router.state.location.search).toBe("?next=%2Fdepo");
  });

  it("giriş yapınca istenen sayfaya döner ve role göre menü gösterir", async () => {
    vi.mocked(authApi.fetchMe).mockRejectedValue(httpError(401));
    vi.mocked(authApi.login).mockResolvedValue(depoUser);
    const { router } = renderApp("/login?next=%2Fdepo");

    await userEvent.type(await screen.findByLabelText("Kullanıcı adı"), "depo1");
    await userEvent.type(screen.getByLabelText("Şifre"), "gizli");
    await userEvent.click(screen.getByRole("button", { name: "Giriş yap" }));

    await waitFor(() => expect(router.state.location.pathname).toBe("/depo"));
    expect(authApi.login).toHaveBeenCalledWith({ username: "depo1", password: "gizli" });
    expect(screen.getByRole("link", { name: "Depo ve stok" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Kalite kontrol" })).not.toBeInTheDocument();
  });

  it("hatalı girişte backend mesajını gösterir", async () => {
    vi.mocked(authApi.fetchMe).mockRejectedValue(httpError(401));
    vi.mocked(authApi.login).mockRejectedValue(
      httpError(400, { code: "invalid_credentials", detail: "Kullanıcı adı veya şifre hatalı." }),
    );
    renderApp("/login");

    await userEvent.type(await screen.findByLabelText("Kullanıcı adı"), "x");
    await userEvent.type(screen.getByLabelText("Şifre"), "y");
    await userEvent.click(screen.getByRole("button", { name: "Giriş yap" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Kullanıcı adı veya şifre hatalı.");
  });

  it("boş formu göndermez", async () => {
    vi.mocked(authApi.fetchMe).mockRejectedValue(httpError(401));
    renderApp("/login");
    await userEvent.click(await screen.findByRole("button", { name: "Giriş yap" }));
    expect(screen.getByText("Kullanıcı adı gerekli")).toBeInTheDocument();
    expect(authApi.login).not.toHaveBeenCalled();
  });

  it("rolü olmayan modül adresinde 'Yetkiniz yok' gösterir", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(depoUser);
    renderApp("/kalite");
    expect(await screen.findByText("Yetkiniz yok")).toBeInTheDocument();
  });

  it("bilinmeyen adreste 'Sayfa bulunamadı' gösterir", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(depoUser);
    renderApp("/olmayan-sayfa");
    expect(await screen.findByText("Sayfa bulunamadı")).toBeInTheDocument();
  });

  it("bir istek 401 dönerse oturumu kapatıp giriş ekranına yönlendirir", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(depoUser);
    const { router } = renderApp("/depo");
    await screen.findByRole("link", { name: "Depo ve stok" });

    await act(async () => {
      await api
        .get("/herhangi/", { adapter: () => Promise.reject(httpError(401)) })
        .catch(() => undefined);
    });

    await waitFor(() => expect(router.state.location.pathname).toBe("/login"));
  });

  it("açılışta CSRF çerezini alır", async () => {
    vi.mocked(authApi.fetchMe).mockRejectedValue(httpError(401));
    renderApp("/login");
    await screen.findByRole("button", { name: "Giriş yap" });
    expect(authApi.fetchCsrf).toHaveBeenCalledTimes(1);
  });

  it("çıkış yapınca giriş ekranına döner", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(depoUser);
    vi.mocked(authApi.logout).mockResolvedValue();
    const { router } = renderApp("/");

    await userEvent.click(await screen.findByText("Ayşe Yılmaz"));
    await userEvent.click(await screen.findByText("Çıkış yap"));

    await waitFor(() => expect(router.state.location.pathname).toBe("/login"));
    expect(authApi.logout).toHaveBeenCalled();
  });
});
