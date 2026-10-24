import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as authApi from "../../api/auth";
import * as opsApi from "../../api/ops";
import type { BackupRun, SystemStatus } from "../../api/ops";
import * as usersApi from "../../api/users";
import type { UserRecord } from "../../api/users";
import * as workflowApi from "../../api/workflow";
import { page, userWith } from "../../test/fixtures";
import { renderApp } from "../../test/render";
import { formatBytes } from "./format";

vi.mock("../../api/auth");
vi.mock("../../api/ops");
vi.mock("../../api/users");
vi.mock("../../api/workflow");

function run(extra: Partial<BackupRun> = {}): BackupRun {
  return {
    id: 1,
    kind: "backup",
    kind_display: "Gece yedeği",
    run_id: "20261016-020000",
    source_run_id: "",
    started_at: "2026-10-16T02:00:00+03:00",
    finished_at: "2026-10-16T02:04:00+03:00",
    status: "ok",
    status_display: "Başarılı",
    message: "",
    database_bytes: 157286400,
    media_bytes: 1048576,
    media_files: 12,
    tables: 140,
    rows: 125000,
    offsite: "ok",
    offsite_display: "Kopyalandı",
    offsite_message: "",
    mismatches: [],
    ...extra,
  };
}

const STATUS: SystemStatus = {
  checks: [
    {
      check: "backup",
      label: "Gece yedeği",
      status: "ok",
      title: "Son yedek 16.10.2026 02:04",
      detail: "",
      since: null,
    },
    {
      check: "restore_test",
      label: "Geri yükleme testi",
      status: "error",
      title: "Son test başarısız",
      detail: "2 tabloda satır sayısı farklı",
      since: "2026-10-12T04:00:00+03:00",
    },
    {
      check: "celery",
      label: "Arka plan servisleri",
      status: "unknown",
      title: "Henüz bilgi yok",
      detail: "",
      since: null,
    },
  ],
  disks: [
    { path: "/backups", total_bytes: 100 * 1024 ** 3, free_bytes: 15 * 1024 ** 3, used_pct: 85 },
  ],
  load_15: 0.75,
  cpu_count: 4,
  queue_length: 3,
  runs: [
    run(),
    run({
      id: 2,
      kind: "restore_test",
      kind_display: "Geri yükleme testi",
      status: "failed",
      status_display: "Başarısız",
      message: "Satır sayıları tutmadı",
      offsite: "disabled",
      offsite_display: "Kapalı",
      mismatches: [{ table: "inventory_lot", expected: 120, actual: 119 }],
    }),
  ],
};

function userRecord(extra: Partial<UserRecord> = {}): UserRecord {
  return {
    id: 5,
    username: "ayse",
    full_name: "Ayşe Yılmaz",
    email: "ayse@example.com",
    phone: "",
    roles: ["depo", "sevkiyat"],
    is_active: true,
    is_superuser: false,
    must_change_password: false,
    last_login: "2026-10-15T08:00:00Z",
    date_joined: "2026-01-01T08:00:00Z",
    is_locked: true,
    otp_enabled: false,
    ...extra,
  };
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(authApi.fetchCsrf).mockResolvedValue();
  vi.mocked(workflowApi.fetchTasks).mockResolvedValue(page([]));
  vi.mocked(workflowApi.fetchNotifications).mockResolvedValue(page([]));
  vi.mocked(workflowApi.fetchUnreadCount).mockResolvedValue(0);
  vi.mocked(opsApi.fetchSystemStatus).mockResolvedValue(STATUS);
  vi.mocked(usersApi.listUsers).mockResolvedValue(
    page([
      userRecord(),
      userRecord({
        id: 6,
        username: "mehmet",
        full_name: "Mehmet Kaya",
        is_locked: false,
        otp_enabled: true,
        roles: ["yonetim"],
      }),
    ]),
  );
});

describe("Sistem menüsü", () => {
  it("admin menüde Sistem bağlantısını görür", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("admin"));
    renderApp("/");
    expect(await screen.findByRole("link", { name: "Sistem" })).toHaveAttribute("href", "/sistem");
  });

  it("yönetim rolü Sistem ekranını açamaz", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("yonetim"));
    renderApp("/sistem");
    expect(await screen.findByText("Yetkiniz yok")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Sistem" })).not.toBeInTheDocument();
    expect(opsApi.fetchSystemStatus).not.toHaveBeenCalled();
  });
});

describe("Sistem durumu", () => {
  it("kontrolleri, diski, yükü ve son yedek / test kayıtlarını gösterir", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("admin"));
    renderApp("/sistem");
    expect(await screen.findByText("Son test başarısız")).toBeInTheDocument();
    expect(screen.getByText("Normal")).toBeInTheDocument();
    expect(screen.getByText("Sorun")).toBeInTheDocument();
    expect(screen.getByText("Bilinmiyor")).toBeInTheDocument();
    expect(screen.getByText("2 tabloda satır sayısı farklı")).toBeInTheDocument();
    expect(screen.getByText(/Gece yedeği her gece 02:00'de alınır/)).toBeInTheDocument();
    expect(screen.getByText("%85")).toBeInTheDocument();
    expect(screen.getByText("Boş: 15 GB / 100 GB")).toBeInTheDocument();
    expect(screen.getByText("0,75")).toBeInTheDocument();
    expect(screen.getByText("4 işlemci")).toBeInTheDocument();

    const table = screen.getByRole("table");
    expect(within(table).getAllByText("16.10.2026 02:00")).toHaveLength(2);
    expect(within(table).getByText("Başarılı")).toBeInTheDocument();
    expect(within(table).getByText("Başarısız")).toBeInTheDocument();
    expect(within(table).getAllByText("125.000")).toHaveLength(2);
    expect(within(table).getAllByText("Veritabanı 150 MB · Ekler 1 MB (12 dosya)")).toHaveLength(2);
    expect(within(table).getByText("Satır sayıları tutmadı")).toBeInTheDocument();
    expect(within(table).getByText("inventory_lot: beklenen 120, bulunan 119")).toBeInTheDocument();
  });

  it("baytları okunur biçimde yazar", () => {
    expect(formatBytes(0)).toBe("0 B");
    expect(formatBytes(1536)).toBe("1,5 KB");
    expect(formatBytes(5 * 1024 ** 3)).toBe("5 GB");
  });
});

describe("Kullanıcılar", () => {
  it("kilitli kullanıcının kilidini onayla açar", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("admin"));
    vi.mocked(usersApi.unlockUser).mockResolvedValue(userRecord({ is_locked: false }));
    renderApp("/sistem/kullanicilar");

    expect(await screen.findByText("Ayşe Yılmaz")).toBeInTheDocument();
    expect(screen.getByText("Kilitli")).toBeInTheDocument();
    expect(screen.getAllByText("Depo").length).toBeGreaterThan(0);
    expect(screen.getByText("2FA açık")).toBeInTheDocument();
    // Kullanıcılar artık bu ekrandan açılır; yönetim paneli bağlantısı yok (bulutta dışarıya kapalı).
    expect(screen.getByText(/sistem geçici şifre üretir/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Yönetim panelinde/ })).not.toBeInTheDocument();
    // Kilit açma yalnızca kilitli kullanıcıda, 2FA sıfırlama yalnızca 2FA'sı olanda.
    expect(screen.getAllByRole("button", { name: "Kilidi aç" })).toHaveLength(1);
    expect(screen.getAllByRole("button", { name: "2FA sıfırla" })).toHaveLength(1);

    await user.click(screen.getByRole("button", { name: "Kilidi aç" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/hesap kilidi açılsın mı/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Kilidi aç" }));

    await waitFor(() => expect(usersApi.unlockUser).toHaveBeenCalledWith(5));
    await waitFor(() => expect(usersApi.listUsers).toHaveBeenCalledTimes(2));
  });

  it("2FA sıfırlama açıklamasıyla sorulur ve uç noktayı çağırır", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("admin"));
    vi.mocked(usersApi.resetUserOtp).mockResolvedValue(userRecord({ id: 6, otp_enabled: false }));
    renderApp("/sistem/kullanicilar");
    await user.click(await screen.findByRole("button", { name: "2FA sıfırla" }));
    const dialog = await screen.findByRole("dialog");
    expect(
      within(dialog).getByText(/Telefonunu kaybeden kullanıcı bir sonraki girişte yeniden kurar/),
    ).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "2FA sıfırla" }));
    await waitFor(() => expect(usersApi.resetUserOtp).toHaveBeenCalledWith(6));
  });

  it("arama kutusu listeyi süzer", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("admin"));
    renderApp("/sistem/kullanicilar");
    await screen.findByText("Ayşe Yılmaz");
    await user.type(screen.getByLabelText("Ara (kullanıcı adı, ad, e-posta)"), "meh");
    await waitFor(() => expect(usersApi.listUsers).toHaveBeenLastCalledWith("meh"));
  });

  it("yeni kullanıcı açar; geçici şifre bir kez gösterilir", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("admin"));
    vi.mocked(usersApi.createUser).mockResolvedValue({
      user: userRecord({
        id: 9,
        username: "ahmet.yilmaz",
        full_name: "Ahmet Yılmaz",
        roles: ["depo"],
        is_locked: false,
        must_change_password: true,
        last_login: null,
      }),
      temporary_password: "Kp7m-x3Rt-9wQa",
    });
    renderApp("/sistem/kullanicilar");

    await user.click(await screen.findByRole("button", { name: "Yeni kullanıcı" }));
    const dialog = await screen.findByRole("dialog", { name: "Yeni kullanıcı" });
    await user.type(within(dialog).getByLabelText(/Ad soyad/), "Ahmet Yılmaz");
    // Kullanıcı adı ad soyaddan önerilir; Türkçe harfler sadeleşir.
    expect(within(dialog).getByLabelText(/Kullanıcı adı/)).toHaveValue("ahmet.yilmaz");
    await user.type(within(dialog).getByLabelText("Telefon"), "0532 000 00 00");
    expect(within(dialog).getByText(/Rol seçmediniz/)).toBeInTheDocument();
    await user.click(within(dialog).getByLabelText("Depo"));
    expect(within(dialog).queryByText(/Rol seçmediniz/)).not.toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Hesabı aç" }));

    await waitFor(() =>
      expect(usersApi.createUser).toHaveBeenCalledWith({
        username: "ahmet.yilmaz",
        full_name: "Ahmet Yılmaz",
        phone: "0532 000 00 00",
        email: "",
        roles: ["depo"],
      }),
    );
    const shown = await screen.findByRole("dialog", { name: "Geçici şifre" });
    expect(within(shown).getByTestId("temporary-password")).toHaveTextContent("Kp7m-x3Rt-9wQa");
    expect(within(shown).getByText(/kullanıcı adı: ahmet.yilmaz/)).toBeInTheDocument();
    expect(within(shown).getByText(/bir daha gösterilmez/)).toBeInTheDocument();
    expect(within(shown).getByRole("button", { name: "Kopyala" })).toBeInTheDocument();
    await user.click(within(shown).getByRole("button", { name: "Şifreyi ilettim, kapat" }));
    await waitFor(() => expect(screen.queryByTestId("temporary-password")).not.toBeInTheDocument());
    await waitFor(() => expect(usersApi.listUsers).toHaveBeenCalledTimes(2));
  });

  it("kurala uymayan kullanıcı adıyla ve ad soyadsız hesap açmaz", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("admin"));
    renderApp("/sistem/kullanicilar");

    await user.click(await screen.findByRole("button", { name: "Yeni kullanıcı" }));
    const dialog = await screen.findByRole("dialog", { name: "Yeni kullanıcı" });
    const username = within(dialog).getByLabelText(/Kullanıcı adı/);
    await user.type(username, "Şule");
    // Büyük harf küçülür, Türkçe harf kalır ve kurala uymaz.
    expect(username).toHaveValue("Şule");
    await user.click(within(dialog).getByRole("button", { name: "Hesabı aç" }));

    expect(await within(dialog).findByText(/Kullanıcı adı kurala uymuyor/)).toBeInTheDocument();
    expect(within(dialog).getByText("Gerekli")).toBeInTheDocument();
    expect(usersApi.createUser).not.toHaveBeenCalled();
  });

  it("düzenle: bilgileri ve rolleri kaydeder, kullanıcı adı değişmez", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("admin"));
    vi.mocked(usersApi.updateUser).mockResolvedValue(userRecord({ roles: ["depo"] }));
    renderApp("/sistem/kullanicilar");

    await screen.findByText("Ayşe Yılmaz");
    await user.click(screen.getAllByRole("button", { name: "Düzenle" })[0]);
    const dialog = await screen.findByRole("dialog", { name: "Ayşe Yılmaz: bilgileri düzenle" });
    expect(within(dialog).getByText("ayse")).toBeInTheDocument();
    expect(
      within(dialog).queryByRole("textbox", { name: /Kullanıcı adı/ }),
    ).not.toBeInTheDocument();
    expect(within(dialog).getByLabelText("Sevkiyat")).toBeChecked();
    await user.click(within(dialog).getByLabelText("Sevkiyat"));
    await user.click(within(dialog).getByRole("button", { name: "Kaydet" }));

    await waitFor(() =>
      expect(usersApi.updateUser).toHaveBeenCalledWith(5, {
        full_name: "Ayşe Yılmaz",
        phone: "",
        email: "ayse@example.com",
        roles: ["depo"],
      }),
    );
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: /bilgileri düzenle/ })).not.toBeInTheDocument(),
    );
  });

  it("şifre sıfırlama onaylanınca yeni geçici şifre gösterilir", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("admin"));
    vi.mocked(usersApi.resetUserPassword).mockResolvedValue({
      user: userRecord({ must_change_password: true }),
      temporary_password: "Ab2c-De3f-Gh4j",
    });
    renderApp("/sistem/kullanicilar");

    await user.click(await screen.findByRole("button", { name: "Ayşe Yılmaz: diğer işlemler" }));
    await user.click(await screen.findByRole("menuitem", { name: "Şifre sıfırla" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/açık oturumu kapanır/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Şifre sıfırla" }));

    await waitFor(() => expect(usersApi.resetUserPassword).toHaveBeenCalledWith(5));
    expect(await screen.findByTestId("temporary-password")).toHaveTextContent("Ab2c-De3f-Gh4j");
  });

  it("pasife alma onayla çağrılır; kendi hesabında işlem menüsü yoktur", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue({ ...userWith("admin"), id: 6 });
    vi.mocked(usersApi.setUserActive).mockResolvedValue(userRecord({ is_active: false }));
    renderApp("/sistem/kullanicilar");

    await screen.findByText("Ayşe Yılmaz");
    expect(screen.getByText("Siz")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Mehmet Kaya: diğer işlemler" }),
    ).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Ayşe Yılmaz: diğer işlemler" }));
    await user.click(await screen.findByRole("menuitem", { name: "Pasife al" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/Kayıtları ve geçmişi silinmez/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Pasife al" }));

    await waitFor(() => expect(usersApi.setUserActive).toHaveBeenCalledWith(5, false));
  });

  it("pasif kullanıcı etkinleştirilir; geçici şifreli kullanıcıda rozet görünür", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("admin"));
    vi.mocked(usersApi.listUsers).mockResolvedValue(
      page([
        userRecord({ is_active: false, is_locked: false }),
        userRecord({
          id: 7,
          username: "yeni",
          full_name: "Yeni Çalışan",
          is_locked: false,
          must_change_password: true,
        }),
      ]),
    );
    vi.mocked(usersApi.setUserActive).mockResolvedValue(userRecord());
    renderApp("/sistem/kullanicilar");

    expect(await screen.findByText("Geçici şifre")).toBeInTheDocument();
    expect(screen.getByText("Pasif")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Ayşe Yılmaz: diğer işlemler" }));
    expect(screen.queryByRole("menuitem", { name: "Şifre sıfırla" })).not.toBeInTheDocument();
    await user.click(await screen.findByRole("menuitem", { name: "Etkinleştir" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Etkinleştir" }));

    await waitFor(() => expect(usersApi.setUserActive).toHaveBeenCalledWith(5, true));
  });
});

describe("Bu cihaz", () => {
  it("tarayıcıyı saha tableti olarak işaretler ve me'yi yeniler", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe)
      .mockResolvedValueOnce(userWith("admin"))
      .mockResolvedValue({ ...userWith("admin"), field_device: true, idle_timeout_seconds: 600 });
    vi.mocked(authApi.setFieldDevice).mockResolvedValue({ enabled: true });
    renderApp("/sistem/bu-cihaz");

    expect(
      await screen.findByText("Bu tarayıcı saha tableti olarak işaretli değil."),
    ).toBeInTheDocument();
    expect(screen.getByText(/oturum 10 dakika işlem yapılmayınca kapanır/)).toBeInTheDocument();
    await user.click(screen.getByLabelText("Bu tarayıcı saha tableti"));

    await waitFor(() => expect(authApi.setFieldDevice).toHaveBeenCalledWith(true));
    expect(
      await screen.findByText("Bu tarayıcı saha tableti olarak işaretli."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Bu tarayıcıda şu anki hareketsizlik süresi: 10 dakika"),
    ).toBeInTheDocument();
  });
});
