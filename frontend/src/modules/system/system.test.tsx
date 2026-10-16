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
    expect(screen.getByRole("link", { name: "Yönetim panelinde kullanıcılar" })).toHaveAttribute(
      "href",
      "/admin/core/user/",
    );
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
