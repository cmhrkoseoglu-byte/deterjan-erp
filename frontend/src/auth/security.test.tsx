import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { act } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as authApi from "../api/auth";
import { api } from "../api/client";
import { resetIdleTracking } from "../api/idle";
import * as workflowApi from "../api/workflow";
import { groupSecret, svgDataUrl } from "../modules/security/otp";
import { httpError, page, userWith } from "../test/fixtures";
import { renderApp } from "../test/render";

vi.mock("../api/auth");
vi.mock("../api/workflow");

const SECURITY: authApi.SecurityStatus = {
  otp_enabled: false,
  otp_required: true,
  recovery_codes_remaining: 0,
  field_device: false,
  idle_timeout_seconds: 3600,
  password_help: ["Şifreniz en az 10 karakter olmalı."],
};

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(authApi.fetchCsrf).mockResolvedValue();
  vi.mocked(workflowApi.fetchTasks).mockResolvedValue(page([]));
  vi.mocked(workflowApi.fetchNotifications).mockResolvedValue(page([]));
  vi.mocked(workflowApi.fetchUnreadCount).mockResolvedValue(0);
  vi.mocked(authApi.fetchSecurity).mockResolvedValue(SECURITY);
});

async function enterPassword(user: ReturnType<typeof userEvent.setup>) {
  await user.type(await screen.findByLabelText("Kullanıcı adı"), "ayse");
  await user.type(screen.getByLabelText("Şifre"), "gizli");
  await user.click(screen.getByRole("button", { name: "Giriş yap" }));
}

describe("iki aşamalı giriş", () => {
  beforeEach(() => {
    vi.mocked(authApi.fetchMe).mockRejectedValue(httpError(401));
  });

  it("otp_required gelince kod adımına geçer ve kodla yeniden gönderir", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.login)
      .mockRejectedValueOnce(
        httpError(400, { code: "otp_required", detail: "Doğrulayıcı uygulamadaki kodu girin." }),
      )
      .mockResolvedValueOnce(userWith("depo"));
    const { router } = renderApp("/login?next=%2Fbildirimler");

    await enterPassword(user);
    const code = await screen.findByLabelText("Doğrulama kodu");
    expect(code).toHaveAttribute("inputmode", "numeric");
    expect(code).toHaveAttribute("autocomplete", "one-time-code");
    expect(screen.getByText(/kurtarma kodlarından birini girin/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    await user.type(code, "123456");
    await user.click(screen.getByRole("button", { name: "Doğrula" }));

    await waitFor(() => expect(router.state.location.pathname).toBe("/bildirimler"));
    expect(authApi.login).toHaveBeenLastCalledWith({
      username: "ayse",
      password: "gizli",
      otp_code: "123456",
    });
  });

  it("invalid_otp hatayı gösterir ve kod adımında kalır", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.login)
      .mockRejectedValueOnce(httpError(400, { code: "otp_required", detail: "Kodu girin." }))
      .mockRejectedValueOnce(
        httpError(400, { code: "invalid_otp", detail: "Doğrulama kodu hatalı." }),
      );
    renderApp("/login");

    await enterPassword(user);
    await user.type(await screen.findByLabelText("Doğrulama kodu"), "000000");
    await user.click(screen.getByRole("button", { name: "Doğrula" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Doğrulama kodu hatalı.");
    expect(screen.getByLabelText("Doğrulama kodu")).toBeInTheDocument();
    expect(screen.queryByLabelText("Kullanıcı adı")).not.toBeInTheDocument();
  });

  it("kilitli hesapta sunucunun mesajını gösterir", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.login).mockRejectedValue(
      httpError(400, {
        code: "account_locked",
        detail: "Çok fazla hatalı deneme. Hesabınız 15 dakika kilitlendi.",
      }),
    );
    renderApp("/login");
    await enterPassword(user);
    expect(await screen.findByRole("alert")).toHaveTextContent("Hesabınız 15 dakika kilitlendi.");
    expect(screen.queryByLabelText("Doğrulama kodu")).not.toBeInTheDocument();
  });
});

describe("hareketsizlik", () => {
  it("istemci süresi dolunca oturumu kapatıp giriş ekranında nedenini gösterir", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    try {
      vi.mocked(authApi.fetchMe).mockResolvedValue({
        ...userWith("depo"),
        idle_timeout_seconds: 60,
      });
      vi.mocked(authApi.logout).mockResolvedValue();
      const { router } = renderApp("/bildirimler");
      await screen.findByRole("link", { name: "Depo ve stok" });
      // Kullanıcı 10 dakikadır dokunmadı (sunucu yanıt vermese de yerelde kapatılır).
      resetIdleTracking(Date.now() - 600_000);
      await act(async () => {
        vi.advanceTimersByTime(15_000);
      });
      await waitFor(() => expect(router.state.location.pathname).toBe("/login"));
      expect(await screen.findByText(/oturumunuz kapandı/)).toBeInTheDocument();
      expect(authApi.logout).toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
      resetIdleTracking();
    }
  });

  it("giriş ekranı oturumun neden kapandığını söyler", async () => {
    vi.mocked(authApi.fetchMe).mockRejectedValue(httpError(401));
    renderApp("/login?next=%2Fdepo&reason=expired");
    expect(
      await screen.findByText(/Uzun süre işlem yapılmadığı için oturumunuz kapandı/),
    ).toBeInTheDocument();
  });

  it("bir istek 401 session_expired dönerse giriş ekranına nedeniyle yönlendirir", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("depo"));
    const { router } = renderApp("/bildirimler");
    await screen.findByRole("link", { name: "Depo ve stok" });

    await act(async () => {
      await api
        .get("/herhangi/", {
          adapter: () =>
            Promise.reject(httpError(401, { code: "session_expired", detail: "Oturum kapandı." })),
        })
        .catch(() => undefined);
    });

    await waitFor(() => expect(router.state.location.pathname).toBe("/login"));
    expect(new URLSearchParams(router.state.location.search).get("reason")).toBe("expired");
    expect(await screen.findByText(/oturumunuz kapandı/)).toBeInTheDocument();
  });

  it("açılışta oturum hareketsizlikten kapanmışsa da nedeni gösterir", async () => {
    vi.mocked(authApi.fetchMe).mockRejectedValue(
      httpError(401, { code: "session_expired", detail: "Oturum kapandı." }),
    );
    const { router } = renderApp("/depo");
    await waitFor(() => expect(router.state.location.pathname).toBe("/login"));
    expect(await screen.findByText(/oturumunuz kapandı/)).toBeInTheDocument();
  });
});

describe("zorunlu iki aşamalı doğrulama", () => {
  it("kurulum gerekiyorsa her sayfa Güvenlik sayfasına yönlendirir", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue({
      ...userWith("yonetim"),
      otp_setup_required: true,
    });
    const { router } = renderApp("/depo");
    await waitFor(() => expect(router.state.location.pathname).toBe("/guvenlik"));
    expect(await screen.findByText("İki aşamalı doğrulama zorunlu")).toBeInTheDocument();
  });

  it("bir API 403 otp_setup_required dönerse me yenilenir ve Güvenlik sayfasına gidilir", async () => {
    vi.mocked(authApi.fetchMe)
      .mockResolvedValueOnce(userWith("yonetim"))
      .mockResolvedValue({ ...userWith("yonetim"), otp_setup_required: true });
    const { router } = renderApp("/bildirimler");
    await screen.findByRole("link", { name: "Depo ve stok" });

    await act(async () => {
      await api
        .get("/herhangi/", {
          adapter: () =>
            Promise.reject(httpError(403, { code: "otp_setup_required", detail: "Kurun." })),
        })
        .catch(() => undefined);
    });

    await waitFor(() => expect(router.state.location.pathname).toBe("/guvenlik"));
  });
});

describe("Güvenlik sayfası", () => {
  it("kullanıcı menüsünden açılır", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("depo"));
    const { router } = renderApp("/");
    await user.click(await screen.findByText("Deneme Kullanıcı"));
    await user.click(await screen.findByText("Güvenlik"));
    await waitFor(() => expect(router.state.location.pathname).toBe("/guvenlik"));
    expect(await screen.findByText("Hareketsizlik süresi: 60 dakika")).toBeInTheDocument();
  });

  it("2FA kurulumu QR kodu gösterir, kodu doğrular ve kurtarma kodlarını bir kez gösterir", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe)
      .mockResolvedValueOnce({ ...userWith("yonetim"), otp_setup_required: true })
      .mockResolvedValue({ ...userWith("yonetim"), otp_enabled: true });
    vi.mocked(authApi.startOtpSetup).mockResolvedValue({
      secret: "JBSWY3DPEHPK3PXP",
      uri: "otpauth://totp/ERP:ayse?secret=JBSWY3DPEHPK3PXP",
      qr_svg: '<svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>',
    });
    const codes = Array.from({ length: 10 }, (_, i) => `abc${i}-efgh`);
    vi.mocked(authApi.confirmOtpSetup)
      .mockRejectedValueOnce(
        httpError(400, { code: "invalid_otp", detail: "Doğrulama kodu hatalı." }),
      )
      .mockResolvedValueOnce({ recovery_codes: codes });
    renderApp("/guvenlik");

    await user.click(await screen.findByRole("button", { name: "Kur" }));
    const qr = await screen.findByAltText("Doğrulayıcı uygulama için QR kod");
    expect(qr.getAttribute("src")).toMatch(/^data:image\/svg\+xml;base64,/);
    expect(screen.getByTestId("otp-secret")).toHaveTextContent("JBSW Y3DP EHPK 3PXP");
    expect(
      screen.getByText(/Google Authenticator ya da Microsoft Authenticator/),
    ).toBeInTheDocument();

    await user.type(screen.getByLabelText("6 haneli kod"), "000000");
    await user.click(screen.getByRole("button", { name: "Doğrula ve aç" }));
    expect(await screen.findByText("Doğrulama kodu hatalı.")).toBeInTheDocument();

    await user.clear(screen.getByLabelText("6 haneli kod"));
    await user.type(screen.getByLabelText("6 haneli kod"), "123456");
    await user.click(screen.getByRole("button", { name: "Doğrula ve aç" }));

    expect(await screen.findByText("abc0-efgh")).toBeInTheDocument();
    expect(screen.getByText("abc9-efgh")).toBeInTheDocument();
    expect(
      screen.getByText("Bu kodları güvenli bir yere yazın; bir daha gösterilmez."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Kopyala" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Yazdır" })).toBeInTheDocument();
    expect(authApi.confirmOtpSetup).toHaveBeenLastCalledWith("123456");
    // Kurulumdan sonra `me` yenilenir (otp_setup_required kalkar).
    await waitFor(() => expect(authApi.fetchMe).toHaveBeenCalledTimes(2));
    expect(screen.queryByText("İki aşamalı doğrulama zorunlu")).not.toBeInTheDocument();
  });

  it("2FA zorunlu rolde kapatma düğmesi yerine açıklama gösterir", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue({ ...userWith("yonetim"), otp_enabled: true });
    vi.mocked(authApi.fetchSecurity).mockResolvedValue({
      ...SECURITY,
      otp_enabled: true,
      recovery_codes_remaining: 7,
    });
    renderApp("/guvenlik");
    expect(await screen.findByText("Kalan kurtarma kodu: 7")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Yeni kurtarma kodları" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Kapat" })).not.toBeInTheDocument();
    expect(screen.getByText(/zorunlu olduğundan/)).toBeInTheDocument();
  });

  it("şifre değiştirirken yeni şifreler aynı değilse göndermez", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("depo"));
    vi.mocked(authApi.fetchSecurity).mockResolvedValue({ ...SECURITY, otp_required: false });
    renderApp("/guvenlik");
    expect(await screen.findByText("Şifreniz en az 10 karakter olmalı.")).toBeInTheDocument();
    await user.type(screen.getByLabelText("Mevcut şifre"), "eski");
    await user.type(screen.getByLabelText("Yeni şifre"), "yeni-sifre-1234");
    await user.type(screen.getByLabelText("Yeni şifre (tekrar)"), "baska");
    await user.click(screen.getByRole("button", { name: "Şifreyi değiştir" }));
    expect(screen.getByText("Yeni şifreler aynı değil")).toBeInTheDocument();
    expect(authApi.changePassword).not.toHaveBeenCalled();

    await user.clear(screen.getByLabelText("Yeni şifre (tekrar)"));
    await user.type(screen.getByLabelText("Yeni şifre (tekrar)"), "yeni-sifre-1234");
    vi.mocked(authApi.changePassword).mockResolvedValue();
    await user.click(screen.getByRole("button", { name: "Şifreyi değiştir" }));
    await waitFor(() =>
      expect(authApi.changePassword).toHaveBeenCalledWith({
        old_password: "eski",
        new_password: "yeni-sifre-1234",
      }),
    );
  });
});

describe("yardımcılar", () => {
  it("anahtarı 4'erli gruplar ve SVG'yi data adresine çevirir", () => {
    expect(groupSecret("ABCDEFGHIJ")).toBe("ABCD EFGH IJ");
    expect(atob(svgDataUrl("<svg/>").split(",")[1])).toBe("<svg/>");
  });
});
