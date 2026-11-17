import { notifications } from "@mantine/notifications";
import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as accessApi from "../../../api/access";
import type { AccessSaveResult, UserAccess } from "../../../api/access";
import * as authApi from "../../../api/auth";
import * as usersApi from "../../../api/users";
import * as workflowApi from "../../../api/workflow";
import { ACCESS_CATALOG_HASH } from "../../../auth/access.gen";
import { accessFor, httpError, page, userWith } from "../../../test/fixtures";
import { renderApp } from "../../../test/render";

vi.mock("../../../api/access");
vi.mock("../../../api/auth");
vi.mock("../../../api/users");
vi.mock("../../../api/workflow");

const PATH = "/sistem/kullanicilar/5/yetkiler";

function matrix(extra: Partial<UserAccess> = {}): UserAccess {
  return {
    user: {
      id: 5,
      username: "ayse",
      full_name: "Ayşe Yılmaz",
      is_active: true,
      is_superuser: false,
      otp_enabled: false,
    },
    roles: ["depo"],
    is_admin: false,
    is_self: false,
    version: "v1",
    catalog_hash: ACCESS_CATALOG_HASH,
    default: accessFor(["depo"]),
    effective: accessFor(["depo"]),
    overrides: [
      {
        id: 12,
        key: "quality.specs",
        level: "view",
        effect: "grant",
        note: "Spesifikasyonlara bakacak",
        created_at: "2026-11-18T09:12:00+03:00",
        created_by_name: "Admin",
        known: true,
        ineffective: false,
      },
    ],
    open_records_effects: {
      production: ["Lot sayfasındaki üretim bağlantıları düz metin olur."],
    },
    ...extra,
  };
}

function result(extra: Partial<AccessSaveResult> = {}): AccessSaveResult {
  return {
    dry_run: true,
    changed: true,
    saved: false,
    roles: { before: ["depo"], after: ["depo"] },
    overrides: { created: [], ended: [] },
    access: {
      before: accessFor(["depo"]),
      after: accessFor(["depo"]),
      granted: [],
      removed: [],
    },
    warnings: [],
    matrix: null,
    ...extra,
  };
}

function cell(name: string | RegExp) {
  return screen.getByRole("button", { name });
}

async function expand(label: string) {
  const region = await screen.findByRole("region", { name: label });
  await userEvent.click(within(region).getAllByRole("button")[0]);
  return region;
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(authApi.fetchCsrf).mockResolvedValue();
  vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("admin"));
  vi.mocked(workflowApi.fetchTasks).mockResolvedValue(page([]));
  vi.mocked(workflowApi.fetchNotifications).mockResolvedValue(page([]));
  vi.mocked(workflowApi.fetchUnreadCount).mockResolvedValue(0);
  vi.mocked(usersApi.listUsers).mockResolvedValue(page([]));
  vi.mocked(accessApi.fetchUserAccess).mockResolvedValue(matrix());
  vi.mocked(accessApi.fetchUserAccessHistory).mockResolvedValue(page([]));
});

afterEach(() => {
  window.matchMedia = originalMatchMedia;
});

const originalMatchMedia = window.matchMedia;

// Sayfa büyüktür (17 modül, 85 bölüm); jsdom'da tıklamalar yavaş.
describe("Yetkiler sayfası", { timeout: 20000 }, () => {
  it("admin olmayan Yetkiler sayfasını açamaz", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("yonetim"));
    renderApp(PATH);
    expect(await screen.findByText("Yetkiniz yok")).toBeInTheDocument();
    expect(accessApi.fetchUserAccess).not.toHaveBeenCalled();
  });

  it("matris rolden gelen, eklenen ve kaldırılan hücreleri simge ve yazıyla gösterir", async () => {
    vi.mocked(accessApi.fetchUserAccess).mockResolvedValue(
      matrix({
        overrides: [
          ...matrix().overrides,
          {
            id: 13,
            key: "production.prep",
            level: "change",
            effect: "revoke",
            note: "Hazırlamayı Ali yapacak",
            created_at: "2026-11-18T09:12:00+03:00",
            created_by_name: "Admin",
            known: true,
            ineffective: false,
          },
        ],
      }),
    );
    renderApp(PATH);

    expect(
      await screen.findByRole("heading", { name: "Ayşe Yılmaz · Yetkiler" }),
    ).toBeInTheDocument();
    expect(screen.getByText("2FA yok")).toBeInTheDocument();
    // Kişiye özel ayarı olan modüller açık başlar.
    expect(cell("Malzeme hazırlama: Görür — Rolden (Depo)")).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(cell("Malzeme hazırlama: Değiştirir — Kaldırıldı")).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(cell("Spesifikasyonlar ve test tanımları: Görür — Eklendi")).toBeInTheDocument();
    expect(
      within(screen.getByTestId("section-production.prep")).getByText("—"),
    ).toBeInTheDocument();
    // Kapalı modül: Satın alma.
    const purchasing = screen.getByRole("region", { name: "Satın alma" });
    expect(within(purchasing).queryByTestId("section-purchasing.orders")).not.toBeInTheDocument();
    expect(within(purchasing).getByText("Menüde")).toBeInTheDocument();
    // Hassas veriler ve KVKK notu.
    const sensitive = screen.getByRole("region", { name: "Hassas veriler" });
    expect(
      within(sensitive).getByRole("button", { name: "Fiyatları görür: Görür — Verilmedi" }),
    ).toBeInTheDocument();
    expect(
      within(sensitive).getByText(/yalnız yönetim rolündeki kullanıcılara verilebilir/),
    ).toBeInTheDocument();
  });

  it("hücreye tıklamak tersine çevirir, ikinci tıklama rol varsayılanına döndürür", async () => {
    const user = userEvent.setup();
    renderApp(PATH);
    await expand("Üretim");

    await user.click(cell("Üretim emirleri: Değiştirir — Verilmedi"));
    expect(cell("Üretim emirleri: Değiştirir — Eklendi (kaydedilmedi)")).toBeInTheDocument();
    expect(screen.getByText("1 değişiklik kaydedilmedi")).toBeInTheDocument();
    await user.click(cell("Üretim emirleri: Değiştirir — Eklendi (kaydedilmedi)"));
    expect(cell("Üretim emirleri: Değiştirir — Verilmedi")).toBeInTheDocument();
    expect(screen.queryByText(/değişiklik kaydedilmedi/)).not.toBeInTheDocument();
  });

  it("Görür kapanınca Değiştirir düşer; Değiştirir açılınca eksik ön koşul verilir ve yazılır", async () => {
    const user = userEvent.setup();
    renderApp(PATH);
    await expand("Üretim");

    await user.click(cell("Malzeme hazırlama: Görür — Rolden (Depo)"));
    expect(cell("Malzeme hazırlama: Görür — Kaldırıldı (kaydedilmedi)")).toBeInTheDocument();
    expect(
      cell("Malzeme hazırlama: Değiştirir — Rolden (Depo) · Görür kaldırıldığı için geçersiz"),
    ).toHaveAttribute("aria-pressed", "false");

    await expand("Satın alma");
    await user.click(cell("Satın alma siparişleri: Değiştirir — Verilmedi"));
    expect(
      screen.getByText(
        "Satın alma › Satın alma siparişleri: Değiştirir için Fiyatları görür de verildi.",
      ),
    ).toBeInTheDocument();
    expect(cell("Fiyatları görür: Görür — Eklendi (kaydedilmedi)")).toBeInTheDocument();
  });

  it("açık kayıtlar satırı yalnız kapatılır; kapatınca okumaya devam edilen bölümler yazar", async () => {
    const user = userEvent.setup();
    renderApp(PATH);
    await expand("Üretim");

    await user.click(cell("Üretim: Açık kayıtlar — Herkes okur"));
    expect(cell("Üretim: Açık kayıtlar — Bu kişi için kapalı (kaydedilmedi)")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Kayıtları şu bölümlerden okumaya devam eder: Üretim emirleri, Malzeme hazırlama ve Şarj ve tartım.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Etkilenebilecek başka ekranlar: Lot sayfasındaki üretim bağlantıları düz metin olur.",
      ),
    ).toBeInTheDocument();
  });

  it("modüldeki bütün yetkileri kaldır açık kayıtlar satırını değiştirmez", async () => {
    const user = userEvent.setup();
    renderApp(PATH);
    await expand("Üretim");

    await user.click(screen.getByRole("button", { name: "Üretim: toplu işlemler" }));
    await user.click(
      await screen.findByRole("menuitem", { name: "Modüldeki bütün yetkileri kaldır" }),
    );
    expect(cell("Malzeme hazırlama: Görür — Kaldırıldı (kaydedilmedi)")).toBeInTheDocument();
    expect(cell("Üretim emirleri: Görür — Kaldırıldı (kaydedilmedi)")).toBeInTheDocument();
    expect(cell("Üretim: Açık kayıtlar — Herkes okur")).toBeInTheDocument();
    expect(screen.getByText("3 değişiklik kaydedilmedi")).toBeInTheDocument();
  });

  it("bölüm ara ve yalnız kişiye özel ayarlar süzgeci satırları daraltır", async () => {
    const user = userEvent.setup();
    renderApp(PATH);
    await screen.findByRole("region", { name: "Satın alma" });

    await user.type(screen.getByRole("textbox", { name: "Bölüm ara" }), "hazırlama");
    expect(screen.getByRole("region", { name: "Üretim" })).toBeInTheDocument();
    expect(screen.getByTestId("section-production.prep")).toBeInTheDocument();
    expect(screen.queryByTestId("section-production.orders")).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Satın alma" })).not.toBeInTheDocument();

    await user.clear(screen.getByRole("textbox", { name: "Bölüm ara" }));
    await user.click(screen.getByLabelText("Yalnız kişiye özel ayarlar"));
    expect(screen.getByTestId("section-quality.specs")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Üretim" })).not.toBeInTheDocument();
  });

  it("Kaydet önce ön izlemeyi gösterir; not yazılmadan kaydetmez; rol değişikliği aynı kayıtla gider", async () => {
    const user = userEvent.setup();
    const show = vi.spyOn(notifications, "show").mockReturnValue("bildirim");
    const after = { ...accessFor(["depo", "planlama"]) };
    vi.mocked(accessApi.saveUserAccess)
      .mockResolvedValueOnce(
        result({
          roles: { before: ["depo"], after: ["depo", "planlama"] },
          access: {
            before: accessFor(["depo"]),
            after,
            granted: [{ key: "production.orders", level: "change" }],
            removed: [{ key: "quality.specs", level: "view" }],
          },
          overrides: {
            created: [],
            ended: [
              { id: 12, key: "quality.specs", level: "view", effect: "grant", reason: "reset" },
            ],
          },
          warnings: [
            {
              code: "coverage_gap",
              text: "Sevkiyat rolünde “Satış › Sevkiyatlar: Değiştirir” yetkisi olan etkin kimse yok.",
            },
          ],
        }),
      )
      .mockResolvedValueOnce(
        result({
          dry_run: false,
          saved: true,
          matrix: matrix({ roles: ["depo", "planlama"], overrides: [], version: "v2" }),
        }),
      );
    renderApp(PATH);
    await screen.findByRole("region", { name: "Kalite kontrol" });

    await user.click(screen.getByLabelText("Planlama"));
    await user.click(cell("Spesifikasyonlar ve test tanımları: Görür — Eklendi"));
    expect(screen.getByText("2 değişiklik kaydedilmedi")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Kaydet…" }));

    const dialog = await screen.findByRole("dialog", { name: "Değişikliklerin özeti" });
    expect(accessApi.saveUserAccess).toHaveBeenCalledWith(5, {
      version: "v1",
      dry_run: true,
      roles: ["depo", "planlama"],
      overrides: [],
    });
    expect(await within(dialog).findByText("Depo → Depo, Planlama")).toBeInTheDocument();
    expect(within(dialog).getByText("Üretim › Üretim emirleri (Değiştirir)")).toBeInTheDocument();
    expect(
      within(dialog).getByText(
        "Rol varsayılanına döndü: Kalite kontrol › Spesifikasyonlar ve test tanımları (Görür)",
      ),
    ).toBeInTheDocument();
    expect(within(dialog).getByText("Menüye eklenecek modüller")).toBeInTheDocument();
    expect(within(dialog).getByTestId("access-warnings")).toHaveTextContent(
      "Sevkiyat rolünde “Satış › Sevkiyatlar: Değiştirir” yetkisi olan etkin kimse yok.",
    );

    await user.click(within(dialog).getByRole("button", { name: "Kaydet" }));
    expect(await within(dialog).findByText("Değişikliğin gerekçesini yazın.")).toBeInTheDocument();
    expect(accessApi.saveUserAccess).toHaveBeenCalledTimes(1);

    vi.mocked(accessApi.fetchUserAccess).mockResolvedValue(
      matrix({ roles: ["depo", "planlama"], overrides: [], version: "v2" }),
    );
    await user.type(within(dialog).getByLabelText(/Değişiklik notu/), "Planlamaya geçti");
    await user.click(within(dialog).getByRole("button", { name: "Kaydet" }));
    await waitFor(() =>
      expect(accessApi.saveUserAccess).toHaveBeenLastCalledWith(5, {
        version: "v1",
        note: "Planlamaya geçti",
        roles: ["depo", "planlama"],
        overrides: [],
      }),
    );
    await waitFor(() =>
      expect(
        screen.queryByRole("dialog", { name: "Değişikliklerin özeti" }),
      ).not.toBeInTheDocument(),
    );
    expect(show).toHaveBeenCalledWith(
      expect.objectContaining({
        color: "green",
        message: "Ayşe Yılmaz kullanıcısının yetkileri kaydedildi.",
      }),
    );
    expect(screen.queryByText(/değişiklik kaydedilmedi/)).not.toBeInTheDocument();
    expect(screen.getByLabelText("Planlama")).toBeChecked();
    show.mockRestore();
  });

  it("access_changed hatasında sayfayı yenile önerilir, taslak korunur", async () => {
    const user = userEvent.setup();
    vi.mocked(accessApi.saveUserAccess).mockRejectedValue(
      httpError(400, {
        code: "access_changed",
        detail: "Bu kişinin yetkileri siz düzenlerken değişti. Sayfayı yenileyip yeniden deneyin.",
      }),
    );
    renderApp(PATH);
    await expand("Üretim");
    await user.click(cell("Üretim emirleri: Değiştirir — Verilmedi"));
    await user.click(screen.getByRole("button", { name: "Kaydet…" }));

    const dialog = await screen.findByRole("dialog", { name: "Değişikliklerin özeti" });
    expect(await within(dialog).findByText(/siz düzenlerken değişti/)).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Kaydet" })).toBeDisabled();
    await user.click(within(dialog).getByRole("button", { name: "Vazgeç" }));
    expect(screen.getByText("1 değişiklik kaydedilmedi")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Kaydet…" }));
    const again = await screen.findByRole("dialog", { name: "Değişikliklerin özeti" });
    vi.mocked(accessApi.fetchUserAccess).mockResolvedValue(matrix({ version: "v2" }));
    await user.click(await within(again).findByRole("button", { name: "Sayfayı yenile" }));
    await waitFor(() =>
      expect(screen.queryByText(/değişiklik kaydedilmedi/)).not.toBeInTheDocument(),
    );
  });

  it("kaydedilmemiş değişiklikle sayfadan çıkarken sorulur; sekme geçişi sormaz", async () => {
    const user = userEvent.setup();
    const { router } = renderApp(PATH);
    await expand("Üretim");
    await user.click(cell("Üretim emirleri: Değiştirir — Verilmedi"));

    await user.click(screen.getByRole("tab", { name: "Geçmiş" }));
    expect(
      await screen.findByText("Henüz kişiye özel yetki ya da rol değişikliği yok."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(router.state.location.search).toBe("?sekme=gecmis");

    await user.click(screen.getByRole("link", { name: "← Kullanıcılar" }));
    const dialog = await screen.findByRole("dialog", { name: "Kaydedilmemiş değişiklikler" });
    await user.click(within(dialog).getByRole("button", { name: "Sayfada kal" }));
    expect(router.state.location.pathname).toBe(PATH);

    await user.click(screen.getByRole("link", { name: "← Kullanıcılar" }));
    const asked = await screen.findByRole("dialog", { name: "Kaydedilmemiş değişiklikler" });
    await user.click(within(asked).getByRole("button", { name: "Değişiklikleri at ve çık" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/sistem/kullanicilar"));
  });

  it("admin olan kişide matris yerine açıklama çıkar; kendi sayfasında admin rolü kaldırılamaz", async () => {
    vi.mocked(accessApi.fetchUserAccess).mockResolvedValue(
      matrix({
        roles: ["admin"],
        is_admin: true,
        is_self: true,
        overrides: [],
        default: accessFor(["admin"]),
        effective: accessFor(["admin"]),
      }),
    );
    renderApp(PATH);
    expect(
      await screen.findByText(
        "Sistem yöneticisi her ekranı görür ve her işlemi yapar; kişiye özel yetki uygulanmaz.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Üretim" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Sistem yöneticisi")).toBeDisabled();
    expect(
      screen.getByText("Kendi sistem yöneticisi rolünüzü kaldıramazsınız."),
    ).toBeInTheDocument();
  });

  it("admin rolü verilince kayıtlı ayarlar olduğu gibi gönderilir ve biteceği yazılır", async () => {
    const user = userEvent.setup();
    vi.mocked(accessApi.saveUserAccess).mockResolvedValue(result());
    renderApp(PATH);
    await user.click(await screen.findByLabelText("Sistem yöneticisi"));
    expect(
      screen.getByText(
        "Kaydedince kişiye özel 1 ayarı biter; sistem yöneticisi her yetkiye sahiptir.",
      ),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Kaydet…" }));
    await waitFor(() =>
      expect(accessApi.saveUserAccess).toHaveBeenCalledWith(5, {
        version: "v1",
        dry_run: true,
        roles: ["admin", "depo"],
        overrides: [{ key: "quality.specs", level: "view", effect: "grant" }],
      }),
    );
  });

  it("telefonda bölümler kart, düzeyler üç düğme olur", async () => {
    window.matchMedia = ((query: string) => ({
      ...originalMatchMedia(query),
      matches: true,
    })) as typeof window.matchMedia;
    renderApp(PATH);
    const region = await screen.findByRole("region", { name: "Kalite kontrol" });
    const card = within(region).getByTestId("section-quality.specs");
    const buttons = within(card).getAllByRole("button");
    expect(buttons.map((button) => button.getAttribute("aria-label"))).toEqual([
      "Spesifikasyonlar ve test tanımları: Görür — Eklendi",
      "Spesifikasyonlar ve test tanımları: Değiştirir — Verilmedi",
      "Spesifikasyonlar ve test tanımları: Onaylar — Verilmedi",
    ]);
    expect(within(region).queryByRole("checkbox")).not.toBeInTheDocument();
  });

  it("rol değişince sunucunun etkisiz işaretlediği kayıtlı ayar temizlenmez", async () => {
    const user = userEvent.setup();
    vi.mocked(accessApi.fetchUserAccess).mockResolvedValue(
      matrix({
        roles: ["depo", "planlama"],
        default: accessFor(["depo", "planlama"]),
        effective: accessFor(["depo", "planlama"]),
        overrides: [
          {
            ...matrix().overrides[0],
            key: "production.orders",
            level: "approve",
            ineffective: true,
          },
        ],
      }),
    );
    renderApp(PATH);
    const clean = await screen.findByRole("button", { name: "Etkisiz ayarları temizle" });
    expect(clean).toBeEnabled();
    await user.click(screen.getByLabelText("Planlama"));
    // Planlama kalkınca ekleme yeniden geçerlidir; temizlenecek ayar yok.
    expect(clean).toBeDisabled();
    expect(cell(/^Üretim emirleri: Onaylar — Eklendi/)).toHaveAttribute("aria-pressed", "true");
  });

  it("taslağın verdiği ön koşul kapatılınca ona bağlı yeni ekleme de kalkar", async () => {
    const user = userEvent.setup();
    renderApp(PATH);
    await expand("Satın alma");

    await user.click(cell("Limit üstü sipariş onayı: Onaylar — Verilmedi"));
    expect(screen.getByText("2 değişiklik kaydedilmedi")).toBeInTheDocument();
    await user.click(cell("Fiyatları görür: Görür — Eklendi (kaydedilmedi)"));
    expect(
      screen.getByText(
        "Satın alma › Limit üstü sipariş onayı: Onaylar eklemesi de kaldırıldı (Fiyatları görür gerekir).",
      ),
    ).toBeInTheDocument();
    // Sunucunun reddedeceği ekleme taslakta kalmaz: taslak kayıtlıyla aynıdır.
    expect(cell("Limit üstü sipariş onayı: Onaylar — Verilmedi")).toBeInTheDocument();
    expect(screen.queryByText(/değişiklik kaydedilmedi/)).not.toBeInTheDocument();
  });

  it("yönetim rolü kalkınca yalnız kayıtlı KVKK eklemelerinin biteceği yazılır", async () => {
    const user = userEvent.setup();
    vi.mocked(accessApi.fetchUserAccess).mockResolvedValue(
      matrix({ roles: ["depo", "yonetim"], default: accessFor(["depo", "yonetim"]) }),
    );
    renderApp(PATH);
    await user.click(await screen.findByLabelText("Yönetim"));
    expect(screen.queryByText(/eklemeleri biter \(KVKK\)/)).not.toBeInTheDocument();
    cleanup();

    vi.mocked(accessApi.fetchUserAccess).mockResolvedValue(
      matrix({
        roles: ["depo", "yonetim"],
        default: accessFor(["depo", "yonetim"]),
        overrides: [{ ...matrix().overrides[0], key: "personnel.wages", level: "change" }],
      }),
    );
    renderApp(PATH);
    await user.click(await screen.findByLabelText("Yönetim"));
    expect(screen.getByText(/eklemeleri biter \(KVKK\)/)).toBeInTheDocument();
  });

  it("Geçmiş sekmesi tarih, değiştiren, gerekçe ve satırları gösterir", async () => {
    vi.mocked(accessApi.fetchUserAccessHistory).mockResolvedValue(
      page([
        {
          id: 345,
          timestamp: "2026-11-18T09:12:00+03:00",
          actor_name: "Admin",
          note: "Planlamaya geçti",
          roles: { before: ["depo"], after: ["depo", "planlama"] },
          lines: [
            { kind: "granted", key: "production.orders", level: "approve" },
            { kind: "revoked", key: "production.prep", level: "change" },
            {
              kind: "ended",
              key: "quality.specs",
              level: "view",
              effect: "grant",
              reason: "reset",
              reason_label: "Rol varsayılanına döndü",
            },
          ],
        },
      ]),
    );
    renderApp(`${PATH}?sekme=gecmis`);
    const entry = await screen.findByTestId("history-entry");
    expect(within(entry).getByText("18.11.2026 09:12")).toBeInTheDocument();
    expect(within(entry).getByText("· Admin")).toBeInTheDocument();
    expect(within(entry).getByText("“Planlamaya geçti”")).toBeInTheDocument();
    expect(within(entry).getByText("Roller: Depo → Depo, Planlama")).toBeInTheDocument();
    expect(
      within(entry).getByText("Eklendi: Üretim › Üretim emirleri (Onaylar)"),
    ).toBeInTheDocument();
    expect(
      within(entry).getByText("Kaldırıldı: Üretim › Malzeme hazırlama (Değiştirir)"),
    ).toBeInTheDocument();
    expect(
      within(entry).getByText(
        "Rol varsayılanına döndü: Kalite kontrol › Spesifikasyonlar ve test tanımları (Görür)",
      ),
    ).toBeInTheDocument();
    expect(accessApi.fetchUserAccessHistory).toHaveBeenCalledWith(5, 1);
  });
});
