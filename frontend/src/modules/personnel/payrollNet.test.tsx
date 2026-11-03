// Brütten nete ön bordro ekranları (3. adım): bordro tablosu ve ay hazırlığı, döküm, ek ödeme ve
// kesintiler (tek, toplu, geçen aydan), devirler, başlangıç ayından önceki ay.
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as authApi from "../../api/auth";
import * as payrollApi from "../../api/payroll";
import type { PayrollLine, PayrollRow } from "../../api/payroll";
import * as workflowApi from "../../api/workflow";
import { httpError, page, userWith } from "../../test/fixtures";
import { AYSE, CAN, carry, ECE, item, line, month, opening } from "../../test/payrollFixtures";
import { renderApp } from "../../test/render";

vi.mock("../../api/auth");
vi.mock("../../api/workflow");
vi.mock("../../api/payroll", async (importOriginal) => ({
  // Sorgu anahtarları, kalem listeleri ve hata ayrıştırma gerçek kalır.
  ...(await importOriginal<typeof payrollApi>()),
  getPayrollMonth: vi.fn(),
  listParameterSets: vi.fn(),
  getParameterDefaults: vi.fn(),
  listPayrollItems: vi.fn(),
  addPayrollItem: vi.fn(),
  addPayrollItems: vi.fn(),
  updatePayrollItem: vi.fn(),
  removePayrollItem: vi.fn(),
  saveOpenings: vi.fn(),
  removeOpening: vi.fn(),
}));

// Ayşe: Ekim devri girildi (Eylül sonu kümülatif). Ece: Ekim devri eksik.
const AYSE_NET: PayrollRow = {
  ...AYSE,
  opening: opening(),
  openings: [opening()],
  carry_months: [carry()],
};
const ECE_NEEDS: PayrollRow = {
  ...ECE,
  warnings: ["opening_missing"],
  opening_needed: true,
};
const AYSE_NEEDS: PayrollRow = { ...AYSE, warnings: ["opening_missing"], opening_needed: true };
const DENIZ: PayrollRow = {
  ...AYSE,
  employee: { ...AYSE.employee, id: 4, employee_no: "S-4", full_name: "Deniz Su" },
  warnings: ["opening_missing"],
  opening_needed: true,
};
// Başlangıç ayından önce brütten nete alanlar boştur.
const NET_NULLS: Partial<PayrollLine> = {
  tax_base: null,
  cumulative_tax_base_before: null,
  cumulative_tax_base_after: null,
  income_tax_computed: null,
  income_tax_exemption: null,
  income_tax: null,
  exemption_base_before: null,
  exemption_base_added: null,
  stamp_tax_computed: null,
  stamp_tax_exemption: null,
  stamp_tax: null,
  net_pay: null,
  bes_deduction: null,
  deductions_total: null,
  payable: null,
};

const tr = (element: HTMLElement) => element.closest("tr") as HTMLElement;

// Gelecek ay testleri saati sabitler (yalnızca Date; zamanlayıcılar gerçek kalır): bugün 15.11.2026.
function freezeToday() {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-11-15T12:00:00+03:00"));
}

afterEach(() => {
  vi.useRealTimers();
});

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(authApi.fetchCsrf).mockResolvedValue();
  vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("yonetim"));
  vi.mocked(workflowApi.fetchTasks).mockResolvedValue(page([]));
  vi.mocked(workflowApi.fetchNotifications).mockResolvedValue(page([]));
  vi.mocked(workflowApi.fetchUnreadCount).mockResolvedValue(0);
  vi.mocked(payrollApi.getPayrollMonth).mockResolvedValue(
    month({ rows: [AYSE_NET, CAN, ECE_NEEDS] }),
  );
  vi.mocked(payrollApi.listParameterSets).mockResolvedValue([]);
  vi.mocked(payrollApi.listPayrollItems).mockResolvedValue(page([]));
});

describe("bordro: brütten nete", () => {
  it("bordro tablosu, toplamlar, ay hazırlığı ve mali müşavirdekilerin satırı", async () => {
    const user = userEvent.setup();
    renderApp("/personel/bordro?ay=2026-10");
    const table = await screen.findByTestId("payroll-net");
    const ayse = tr(within(table).getByText("Ayşe Demir"));
    expect(within(ayse).getByText("1.526,17")).toBeInTheDocument();
    // Net ücret ve ödenecek (kesinti yok).
    expect(within(ayse).getAllByText("36.632,98")).toHaveLength(2);
    const totals = tr(within(table).getByText("Toplam (ERP)"));
    expect(within(totals).getAllByText("63.000,00")).toHaveLength(2);
    // Mali müşavirdeki kişi tabloda değil, alt satırda.
    expect(within(table).queryByText("Can Kaya")).not.toBeInTheDocument();
    expect(
      screen.getByText(/Bordrosu mali müşavirde olan 1 kişi: brüt 0,00 TL · işverene maliyet/),
    ).toBeInTheDocument();
    const ece = tr(within(table).getByText("Ece Ak"));
    expect(within(ece).getByText("Devir eksik")).toBeInTheDocument();
    // Ay hazırlığı: puantaj, parametreler, devir, mali müşavir rakamı.
    expect(screen.getByText("Ay hazırlığı")).toBeInTheDocument();
    expect(screen.getByText(/Ayın puantajı onaylanmadı/)).toBeInTheDocument();
    expect(screen.getByText(/1 kişinin Ekim 2026 devri girilmedi/)).toBeInTheDocument();
    expect(screen.getByText(/olan 1 kişinin bu ay rakamları girilmedi/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Bordro listesi (PDF)" })).toHaveAttribute(
      "href",
      "/api/v1/personnel/payroll/2026/10/register.pdf",
    );
    await user.click(screen.getByRole("switch", { name: "Yalnızca uyarılı kişiler" }));
    expect(within(table).queryByText("Ayşe Demir")).not.toBeInTheDocument();
    expect(within(table).getByText("Ece Ak")).toBeInTheDocument();
  });

  it("döküm: hesap ve kümülatifin kuruluşu; önceki / sonraki kişi ve ok tuşları", async () => {
    const user = userEvent.setup();
    renderApp("/personel/bordro?ay=2026-10");
    await user.click(await screen.findByRole("button", { name: "Döküm: Ayşe Demir" }));
    const drawer = await screen.findByRole("dialog", { name: "Ayşe Demir · Ekim 2026" });
    expect(tr(within(drawer).getByText("Kesilen gelir vergisi"))).toHaveTextContent("1.526,17");
    expect(tr(within(drawer).getByText("Ödenecek (ele geçen)"))).toHaveTextContent("36.632,98");
    expect(tr(within(drawer).getByText("Devir (Ekim 2026 öncesi)"))).toHaveTextContent(
      "382.500,00",
    );
    expect(within(drawer).getByRole("button", { name: "Önceki kişi" })).toBeDisabled();
    // Sıra tablodaki gibi: mali müşavirdeki kişi atlanır.
    await user.click(within(drawer).getByRole("button", { name: "Sonraki kişi" }));
    expect(await screen.findByRole("dialog", { name: "Ece Ak · Ekim 2026" })).toBeInTheDocument();
    fireEvent.keyDown(document.body, { key: "ArrowLeft" });
    expect(
      await screen.findByRole("dialog", { name: "Ayşe Demir · Ekim 2026" }),
    ).toBeInTheDocument();
  });

  it("dökümde kalem düzeltilir ve gerekçeyle kaldırılır", async () => {
    const user = userEvent.setup();
    const premium = item();
    const garnishment = item({
      id: 12,
      kind: "DEDUCTION",
      category: "GARNISHMENT",
      category_label: "İcra / nafaka",
      description: "2026/1234 E.",
      amount: "1000.00",
    });
    vi.mocked(payrollApi.getPayrollMonth).mockResolvedValue(
      month({ rows: [{ ...AYSE_NET, items: [premium, garnishment] }, CAN, ECE_NEEDS] }),
    );
    vi.mocked(payrollApi.updatePayrollItem).mockResolvedValue({ ...premium, amount: "5500.00" });
    vi.mocked(payrollApi.removePayrollItem).mockResolvedValue({ ...garnishment, is_active: false });
    renderApp("/personel/bordro?ay=2026-10");
    await user.click(await screen.findByRole("button", { name: "Döküm: Ayşe Demir" }));
    const drawer = await screen.findByRole("dialog", { name: "Ayşe Demir · Ekim 2026" });
    // Hesapta ek ödeme kazançlarda, kesinti netten kesintilerde (açıklamasıyla).
    expect(tr(within(drawer).getByText("Prim"))).toHaveTextContent("5.000,00");
    expect(tr(within(drawer).getByText("İcra / nafaka (2026/1234 E.)"))).toHaveTextContent(
      "−1.000,00",
    );
    await user.click(within(drawer).getByRole("tab", { name: "Ek ödeme ve kesinti (2)" }));
    await user.click(within(drawer).getByRole("button", { name: "Düzelt: Prim · 5.000,00" }));
    const edit = await screen.findByRole("dialog", { name: "Ayşe Demir · kalemi düzelt" });
    expect(
      within(edit).getByText(/Tür \(ek ödeme ya da kesinti\) değiştirilemez/),
    ).toBeInTheDocument();
    const amount = within(edit).getByLabelText(/Tutar \(TL\)/);
    expect(amount).toHaveValue("5.000,00");
    await user.clear(amount);
    await user.type(amount, "5.500");
    await user.click(within(edit).getByRole("button", { name: "Kaydet" }));
    await waitFor(() =>
      expect(payrollApi.updatePayrollItem).toHaveBeenCalledWith(11, {
        category: "PREMIUM",
        description: "",
        amount: "5500",
      }),
    );
    await waitFor(() =>
      expect(
        screen.queryByRole("dialog", { name: "Ayşe Demir · kalemi düzelt" }),
      ).not.toBeInTheDocument(),
    );
    await user.click(
      within(drawer).getByRole("button", {
        name: "Kaldır: İcra / nafaka (2026/1234 E.) · 1.000,00",
      }),
    );
    const reason = await screen.findByRole("dialog", { name: "Kalemi kaldır" });
    const confirm = within(reason).getByRole("button", { name: "Kaldır" });
    expect(confirm).toBeDisabled();
    await user.type(within(reason).getByLabelText(/Kaldırma nedeni/), "Yanlış kişi");
    await user.click(confirm);
    await waitFor(() =>
      expect(payrollApi.removePayrollItem).toHaveBeenCalledWith(12, "Yanlış kişi"),
    );
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Kalemi kaldır" })).not.toBeInTheDocument(),
    );
    expect(screen.getByRole("dialog", { name: "Ayşe Demir · Ekim 2026" })).toBeInTheDocument();
  });

  it("görünüm adreste tutulur; ay değişince korunur", async () => {
    const user = userEvent.setup();
    const { router } = renderApp("/personel/bordro?ay=2026-10");
    await screen.findByTestId("payroll-net");
    await user.click(screen.getByRole("radio", { name: "Ek ödeme ve kesintiler" }));
    expect(
      await screen.findByText("Bu ay girilmiş ek ödeme ya da kesinti yok."),
    ).toBeInTheDocument();
    expect(router.state.location.search).toBe("?ay=2026-10&gorunum=kalemler");
    await user.click(screen.getByRole("button", { name: "Önceki ay" }));
    await waitFor(() => expect(payrollApi.getPayrollMonth).toHaveBeenCalledWith(2026, 9));
    expect(router.state.location.search).toBe("?ay=2026-09&gorunum=kalemler");
  });

  it("başlangıç ayından önce yalnızca işveren maliyeti hesaplanır", async () => {
    vi.mocked(payrollApi.getPayrollMonth).mockResolvedValue(
      month({
        month: 9,
        period_label: "Eylül 2026",
        net: false,
        net_available: false,
        rows: [{ ...AYSE, line: line(NET_NULLS), entry_month: null }],
      }),
    );
    renderApp("/personel/bordro?ay=2026-09&gorunum=kalemler");
    expect(
      await screen.findByText(/Brütten nete bordro Ekim 2026 ayından başlar/),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "İşveren maliyeti" })).toBeInTheDocument();
    expect(screen.getByText("Ayşe Demir")).toBeInTheDocument();
    expect(screen.queryByRole("radio", { name: "Bordro" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Bordro listesi (PDF)" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Devirler" })).not.toBeInTheDocument();
    expect(screen.queryByText(/Devirler tamam|devri girilmedi/)).not.toBeInTheDocument();
    expect(screen.queryByTestId("payroll-items")).not.toBeInTheDocument();
  });
});

describe("bordro: ek ödeme ve kesintiler", () => {
  it("ayın kalemleri, işte olmayanlara girilenler ve kaldırılanlar listelenir", async () => {
    const user = userEvent.setup();
    const orphan = item({
      id: 13,
      employee: 9,
      employee_name: "Deniz Su",
      kind: "DEDUCTION",
      category: "ADVANCE",
      category_label: "Avans",
      amount: "2000.00",
    });
    vi.mocked(payrollApi.getPayrollMonth).mockResolvedValue(
      month({
        rows: [{ ...AYSE_NET, items: [item()] }, CAN, ECE_NEEDS],
        orphan_items: [orphan],
      }),
    );
    vi.mocked(payrollApi.listPayrollItems).mockResolvedValue(
      page([
        item({
          id: 15,
          is_active: false,
          amount: "750.00",
          removed_by_name: "Yönetim",
          removed_at: "2026-11-01T11:00:00+03:00",
          removal_reason: "Yanlış ay",
        }),
      ]),
    );
    renderApp("/personel/bordro?ay=2026-10&gorunum=kalemler");
    const table = await screen.findByTestId("payroll-items");
    const deniz = tr(within(table).getByText("Deniz Su"));
    expect(deniz).toHaveTextContent("bu ay işte değil");
    expect(deniz).toHaveTextContent("−2.000,00");
    expect(screen.getByText(/işte olmayan kişilere girilmiş 1 kalem var/)).toBeInTheDocument();
    // Toplamlar yalnızca bordroya girenlerden.
    expect(screen.getByText("Prim 5.000,00")).toBeInTheDocument();
    expect(screen.queryByText("Avans 2.000,00")).not.toBeInTheDocument();
    expect(payrollApi.listPayrollItems).not.toHaveBeenCalled();
    // Düzeltmede kişi değişmez; listede olmayan kişinin adı da görünür.
    await user.click(
      within(table).getByRole("button", { name: "Düzelt: Deniz Su Avans · 2.000,00" }),
    );
    const edit = await screen.findByRole("dialog", { name: "Deniz Su · kalemi düzelt" });
    expect(within(edit).getByLabelText("Kişi")).toHaveValue("Deniz Su");
    await user.click(within(edit).getByRole("button", { name: "Vazgeç" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await user.click(screen.getByRole("switch", { name: "Kaldırılanları göster" }));
    await waitFor(() =>
      expect(payrollApi.listPayrollItems).toHaveBeenCalledWith({
        year: 2026,
        month: 10,
        is_active: false,
        page_size: 500,
      }),
    );
    const removed = tr(await within(table).findByText(/Kaldırıldı: Yönetim · .* · Yanlış ay/));
    expect(removed).toHaveTextContent("750,00");
    expect(within(removed).queryByRole("button")).not.toBeInTheDocument();
  });

  it("kalem eklenir: Diğer ek ödemede açıklama zorunlu", async () => {
    const user = userEvent.setup();
    vi.mocked(payrollApi.addPayrollItem).mockResolvedValue(
      item({ id: 14, category: "OTHER_EXTRA", description: "Bayram harçlığı", amount: "1500.00" }),
    );
    renderApp("/personel/bordro?ay=2026-10&gorunum=kalemler");
    await user.click(await screen.findByRole("button", { name: "Kalem ekle" }));
    const dialog = await screen.findByRole("dialog", { name: "Ek ödeme ya da kesinti" });
    // Yalnızca bu ay ERP'de hesaplananlar seçilebilir.
    await user.click(within(dialog).getByRole("textbox", { name: /Kişi/ }));
    expect(screen.queryByRole("option", { name: /Can Kaya/ })).not.toBeInTheDocument();
    await user.click(await screen.findByRole("option", { name: "Ayşe Demir (S-1)" }));
    await user.click(within(dialog).getByRole("textbox", { name: /Kalem/ }));
    await user.click(await screen.findByRole("option", { name: "Diğer ek ödeme" }));
    expect(
      within(dialog).getByText("Diğer kalemde açıklama yazın (pusulada görünür)."),
    ).toBeInTheDocument();
    await user.type(within(dialog).getByLabelText(/Tutar \(TL\)/), "1.500");
    const save = within(dialog).getByRole("button", { name: "Kaydet" });
    expect(save).toBeDisabled();
    await user.type(within(dialog).getByLabelText(/Açıklama/), "Bayram harçlığı");
    await user.click(save);
    await waitFor(() =>
      expect(payrollApi.addPayrollItem).toHaveBeenCalledWith(2026, 10, {
        category: "OTHER_EXTRA",
        description: "Bayram harçlığı",
        amount: "1500",
        employee: 1,
      }),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("toplu ekleme: biri reddedilirse hiçbiri kaydedilmez, hata kişinin adıyla görünür", async () => {
    const user = userEvent.setup();
    vi.mocked(payrollApi.addPayrollItems).mockRejectedValue(
      httpError(400, {
        code: "batch_rejected",
        detail: "1 satır kaydedilemedi; hiçbir satır kaydedilmedi.",
        rows: [{ index: 1, employee: 3, code: "not_employed", detail: "Ekim 2026'da işte değil." }],
      }),
    );
    renderApp("/personel/bordro?ay=2026-10&gorunum=kalemler");
    await user.click(await screen.findByRole("button", { name: "Toplu ekle" }));
    const dialog = await screen.findByRole("dialog", { name: "Toplu ekle" });
    await user.click(within(dialog).getByRole("textbox", { name: /Kalem/ }));
    await user.click(await screen.findByRole("option", { name: "Prim" }));
    await user.type(within(dialog).getByLabelText(/Tutar \(TL\)/), "1.000");
    await user.click(within(dialog).getByRole("button", { name: "Hepsini seç" }));
    await user.click(within(dialog).getByRole("button", { name: "Kaydet" }));
    await waitFor(() =>
      expect(payrollApi.addPayrollItems).toHaveBeenCalledWith(2026, 10, [
        { employee: 1, category: "PREMIUM", description: "", amount: "1000" },
        { employee: 3, category: "PREMIUM", description: "", amount: "1000" },
      ]),
    );
    expect(await within(dialog).findByText("Ece Ak: Ekim 2026'da işte değil.")).toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "Toplu ekle" })).toBeInTheDocument();
  });

  it("geçen aydan kopyalama: kalemler işaretli gelir, bu ay hesaplanmayanlar seçilemez", async () => {
    const user = userEvent.setup();
    vi.mocked(payrollApi.listPayrollItems).mockImplementation(async (params) =>
      params.month === 9
        ? page([
            item({ id: 21, month: 9 }),
            item({
              id: 22,
              month: 9,
              employee: 2,
              employee_name: "Can Kaya",
              kind: "DEDUCTION",
              category: "ADVANCE",
              category_label: "Avans",
              amount: "2000.00",
            }),
          ])
        : page([]),
    );
    vi.mocked(payrollApi.addPayrollItems).mockResolvedValue([item({ id: 23 })]);
    renderApp("/personel/bordro?ay=2026-10&gorunum=kalemler");
    await user.click(await screen.findByRole("button", { name: "Geçen aydan kopyala" }));
    const dialog = await screen.findByRole("dialog", { name: "Eylül 2026 kalemlerini kopyala" });
    await waitFor(() =>
      expect(payrollApi.listPayrollItems).toHaveBeenCalledWith({
        year: 2026,
        month: 9,
        is_active: true,
        page_size: 500,
      }),
    );
    expect(
      await within(dialog).findByRole("checkbox", { name: "Ayşe Demir Prim · 5.000,00" }),
    ).toBeChecked();
    const can = within(dialog).getByRole("checkbox", { name: "Can Kaya Avans · 2.000,00" });
    expect(can).not.toBeChecked();
    expect(can).toBeDisabled();
    expect(within(dialog).getByText(/bu ay hesaplanmıyor/)).toBeInTheDocument();
    const add = within(dialog).getByRole("button", { name: "1 kalemi ekle" });
    await waitFor(() => expect(add).toBeEnabled());
    await user.click(add);
    await waitFor(() =>
      expect(payrollApi.addPayrollItems).toHaveBeenCalledWith(2026, 10, [
        { employee: 1, category: "PREMIUM", description: "", amount: "5000.00" },
      ]),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });
});

describe("bordro: devirler", () => {
  it("giriş ayı devri eksik kişiler listelenir; Excel'den yapıştırılır, tek kayıtla gönderilir", async () => {
    const user = userEvent.setup();
    vi.mocked(payrollApi.getPayrollMonth).mockResolvedValue(
      month({
        rows: [{ ...AYSE, warnings: ["opening_missing"], opening_needed: true }, CAN, ECE_NEEDS],
      }),
    );
    vi.mocked(payrollApi.saveOpenings).mockResolvedValue([
      opening(),
      opening({ id: 6, employee: 3, employee_name: "Ece Ak" }),
    ]);
    renderApp("/personel/bordro?ay=2026-10");
    expect(await screen.findByText(/2 kişinin Ekim 2026 devri girilmedi/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Devir gir: Ekim 2026" }));
    const dialog = await screen.findByRole("dialog", {
      name: "Ekim 2026 devri — Eylül 2026 sonu kümülatif",
    });
    expect(within(dialog).getByText("0/2 girildi")).toBeInTheDocument();
    const label = "Kümülatif GV matrahı (Eylül 2026 dahil)";
    const ayse = within(dialog).getByLabelText(`${label}: Ayşe Demir`);
    const ece = within(dialog).getByLabelText(`${label}: Ece Ak`);
    // Sütun yapıştırma satır satır aşağı doldurur.
    fireEvent.paste(ayse, { clipboardData: { getData: () => "382.500,00\r\n1.000\r\n" } });
    expect(ayse).toHaveValue("382.500,00");
    expect(ece).toHaveValue("1.000");
    expect(
      within(dialog).getByText(
        "Kümülatif matrah asgari ücret istisna matrahından az: kontrol edin.",
      ),
    ).toBeInTheDocument();
    await user.clear(ece);
    await user.type(ece, "290.000");
    expect(within(dialog).queryByText(/istisna matrahından az/)).not.toBeInTheDocument();
    expect(within(dialog).getByLabelText("İstisna ay: Ece Ak")).toHaveValue("9");
    // Eşitleme değil (önceki ay ERP'de hesaplanmadı): onay istenmez.
    expect(within(dialog).queryByRole("checkbox")).not.toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Kaydet" }));
    await waitFor(() =>
      expect(payrollApi.saveOpenings).toHaveBeenCalledWith(2026, 10, [
        {
          employee: 1,
          tax_base: "382500.00",
          exemption_months: 9,
          note: "",
          confirm_override: false,
        },
        { employee: 3, tax_base: "290000", exemption_months: 9, note: "", confirm_override: false },
      ]),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("girilmiş devir değişmedikçe yeniden gönderilmez", async () => {
    const user = userEvent.setup();
    vi.mocked(payrollApi.saveOpenings).mockResolvedValue([
      opening({ id: 6, employee: 3, employee_name: "Ece Ak" }),
    ]);
    renderApp("/personel/bordro?ay=2026-10");
    await user.click(await screen.findByRole("button", { name: "Devirler" }));
    const dialog = await screen.findByRole("dialog", { name: /Ekim 2026 devri/ });
    const label = "Kümülatif GV matrahı (Eylül 2026 dahil)";
    expect(within(dialog).getByLabelText(`${label}: Ayşe Demir`)).toHaveValue("382.500,00");
    expect(within(dialog).getByText("1/2 girildi")).toBeInTheDocument();
    const save = within(dialog).getByRole("button", { name: "Kaydet" });
    expect(save).toBeDisabled();
    await user.type(within(dialog).getByLabelText(`${label}: Ece Ak`), "290.000");
    await user.click(save);
    await waitFor(() =>
      expect(payrollApi.saveOpenings).toHaveBeenCalledWith(2026, 10, [
        { employee: 3, tax_base: "290000", exemption_months: 9, note: "", confirm_override: false },
      ]),
    );
  });

  it("dökümden eşitleme devri: onay istenir; satır hatası satırın altında görünür", async () => {
    const user = userEvent.setup();
    vi.mocked(payrollApi.getPayrollMonth).mockResolvedValue(
      month({
        month: 11,
        period_label: "Kasım 2026",
        rows: [
          {
            ...AYSE,
            opening: opening(),
            openings: [opening()],
            carry_months: [
              carry(),
              carry({ kind: "erp", tax_base: "38250.00", exemption_base: "28075.50" }),
            ],
          },
          ECE,
        ],
      }),
    );
    vi.mocked(payrollApi.saveOpenings).mockRejectedValue(
      httpError(400, {
        code: "batch_rejected",
        detail: "1 satır kaydedilemedi; hiçbir satır kaydedilmedi.",
        rows: [
          {
            index: 0,
            employee: 1,
            code: "invalid_tax_base",
            detail: "Kümülatif gelir vergisi matrahı sıfır ya da daha büyük olmalı.",
          },
        ],
      }),
    );
    renderApp("/personel/bordro?ay=2026-11");
    await user.click(await screen.findByRole("button", { name: "Döküm: Ayşe Demir" }));
    const drawer = await screen.findByRole("dialog", { name: "Ayşe Demir · Kasım 2026" });
    expect(tr(within(drawer).getByText("ERP hesabı"))).toHaveTextContent("38.250,00");
    await user.click(within(drawer).getByRole("tab", { name: "Devir" }));
    expect(within(drawer).getByText("Kullanılan devir: Ekim 2026 öncesi")).toBeInTheDocument();
    await user.click(
      within(drawer).getByRole("button", { name: "Bu aydan devir gir (mali müşavirle eşitleme)" }),
    );
    const dialog = await screen.findByRole("dialog", {
      name: "Kasım 2026 devri — Ekim 2026 sonu kümülatif",
    });
    // Yalnızca dökümdeki kişi; istisna ayı önerisi işe girişten bu yana.
    expect(within(dialog).queryByText("Ece Ak")).not.toBeInTheDocument();
    expect(within(dialog).getByLabelText("İstisna ay: Ayşe Demir")).toHaveValue("10");
    const taxBase = within(dialog).getByLabelText(
      "Kümülatif GV matrahı (Ekim 2026 dahil): Ayşe Demir",
    );
    await user.type(taxBase, "430.000");
    const save = within(dialog).getByRole("button", { name: "Kaydet" });
    expect(save).toBeDisabled();
    await user.click(
      within(dialog).getByRole("checkbox", { name: /yerine geçer\. Onaylıyorum\./ }),
    );
    await user.click(save);
    await waitFor(() =>
      expect(payrollApi.saveOpenings).toHaveBeenCalledWith(2026, 11, [
        { employee: 1, tax_base: "430000", exemption_months: 10, note: "", confirm_override: true },
      ]),
    );
    await waitFor(() =>
      expect(taxBase).toHaveAccessibleDescription(/sıfır ya da daha büyük olmalı/),
    );
    expect(
      screen.getByRole("dialog", { name: "Kasım 2026 devri — Ekim 2026 sonu kümülatif" }),
    ).toBeInTheDocument();
  });

  it("dökümden devir gerekçeyle kaldırılır", async () => {
    const user = userEvent.setup();
    vi.mocked(payrollApi.removeOpening).mockResolvedValue(opening({ is_active: false }));
    renderApp("/personel/bordro?ay=2026-10");
    await user.click(await screen.findByRole("button", { name: "Döküm: Ayşe Demir" }));
    const drawer = await screen.findByRole("dialog", { name: "Ayşe Demir · Ekim 2026" });
    await user.click(within(drawer).getByRole("tab", { name: "Devir" }));
    expect(tr(within(drawer).getByText("İstisna ay"))).toHaveTextContent("9");
    // Giriş ayında eşitleme düğmesi yok (devir zaten bu ayın).
    expect(
      within(drawer).queryByRole("button", { name: /Bu aydan devir gir/ }),
    ).not.toBeInTheDocument();
    await user.click(within(drawer).getByRole("button", { name: "Devri kaldır" }));
    const reason = await screen.findByRole("dialog", { name: "Devri kaldır" });
    await user.type(within(reason).getByLabelText(/Kaldırma nedeni/), "Yanlış ay");
    await user.click(within(reason).getByRole("button", { name: "Devri kaldır" }));
    await waitFor(() => expect(payrollApi.removeOpening).toHaveBeenCalledWith(5, "Yanlış ay"));
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Devri kaldır" })).not.toBeInTheDocument(),
    );
  });
});

describe("bordro: döküm, süzgeç ve ay değişimi", () => {
  it("döküm üstünde pencere açıkken Esc ve ok tuşları yalnızca o pencereyi etkiler", async () => {
    const user = userEvent.setup();
    renderApp("/personel/bordro?ay=2026-10");
    await user.click(await screen.findByRole("button", { name: "Döküm: Ayşe Demir" }));
    const drawer = await screen.findByRole("dialog", { name: "Ayşe Demir · Ekim 2026" });
    await user.click(within(drawer).getByRole("tab", { name: "Ek ödeme ve kesinti" }));
    await user.click(within(drawer).getByRole("button", { name: "Kalem ekle" }));
    await screen.findByRole("dialog", { name: "Ek ödeme ya da kesinti" });
    fireEvent.keyDown(document.body, { key: "ArrowRight" });
    expect(screen.queryByRole("dialog", { name: "Ece Ak · Ekim 2026" })).not.toBeInTheDocument();
    await user.keyboard("{Escape}");
    await waitFor(() =>
      expect(
        screen.queryByRole("dialog", { name: "Ek ödeme ya da kesinti" }),
      ).not.toBeInTheDocument(),
    );
    expect(screen.getByRole("dialog", { name: "Ayşe Demir · Ekim 2026" })).toBeInTheDocument();
    // Pencere kapanınca ok tuşları yine kişiler arasında gezdirir.
    fireEvent.keyDown(document.body, { key: "ArrowRight" });
    expect(await screen.findByRole("dialog", { name: "Ece Ak · Ekim 2026" })).toBeInTheDocument();
  });

  it("'Yalnızca uyarılı kişiler' adreste tutulur; döküm yalnızca tablodakileri gezer", async () => {
    const user = userEvent.setup();
    const { router } = renderApp("/personel/bordro?ay=2026-10");
    await screen.findByTestId("payroll-net");
    await user.click(screen.getByRole("switch", { name: "Yalnızca uyarılı kişiler" }));
    expect(router.state.location.search).toBe("?ay=2026-10&uyarili=1");
    await user.click(screen.getByRole("button", { name: "Döküm: Ece Ak" }));
    const drawer = await screen.findByRole("dialog", { name: "Ece Ak · Ekim 2026" });
    expect(within(drawer).getByRole("button", { name: "Önceki kişi" })).toBeDisabled();
    expect(within(drawer).getByRole("button", { name: "Sonraki kişi" })).toBeDisabled();
  });

  it("ay değişince açık döküm kapanır; o aya dönünce kendiliğinden açılmaz", async () => {
    const user = userEvent.setup();
    vi.mocked(payrollApi.getPayrollMonth).mockImplementation(async (year, value) =>
      month({
        year,
        month: value,
        period_label: value === 9 ? "Eylül 2026" : "Ekim 2026",
        rows: [AYSE_NET, CAN, ECE_NEEDS],
      }),
    );
    const { router } = renderApp("/personel/bordro?ay=2026-09");
    await screen.findByTestId("payroll-net");
    await user.click(screen.getByRole("button", { name: "Sonraki ay" }));
    await user.click(await screen.findByRole("button", { name: "Döküm: Ayşe Demir" }));
    expect(
      await screen.findByRole("dialog", { name: "Ayşe Demir · Ekim 2026" }),
    ).toBeInTheDocument();
    await act(() => router.navigate(-1));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await act(() => router.navigate(1));
    expect(await screen.findByRole("button", { name: "Döküm: Ayşe Demir" })).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("bu ay işe girene eşitleme devri önerilmez", async () => {
    const user = userEvent.setup();
    const newcomer: PayrollRow = {
      ...AYSE,
      employee: { ...AYSE.employee, hire_date: "2026-11-15" },
    };
    vi.mocked(payrollApi.getPayrollMonth).mockResolvedValue(
      month({ month: 11, period_label: "Kasım 2026", rows: [newcomer] }),
    );
    renderApp("/personel/bordro?ay=2026-11");
    await user.click(await screen.findByRole("button", { name: "Döküm: Ayşe Demir" }));
    const drawer = await screen.findByRole("dialog", { name: "Ayşe Demir · Kasım 2026" });
    await user.click(within(drawer).getByRole("tab", { name: "Devir" }));
    expect(within(drawer).getByText("Bu kişi için devir girilmedi.")).toBeInTheDocument();
    expect(
      within(drawer).queryByRole("button", { name: /Bu aydan devir gir/ }),
    ).not.toBeInTheDocument();
  });
});

describe("bordro: kalem kuralları", () => {
  it("bordrosu mali müşavirde olana girilmiş kalem toplamlara girmez, ayrıca uyarılır", async () => {
    vi.mocked(payrollApi.getPayrollMonth).mockResolvedValue(
      month({
        rows: [
          { ...AYSE_NET, items: [item()] },
          {
            ...CAN,
            items: [item({ id: 31, employee: 2, employee_name: "Can Kaya", amount: "3000.00" })],
          },
          ECE_NEEDS,
        ],
      }),
    );
    renderApp("/personel/bordro?ay=2026-10&gorunum=kalemler");
    const table = await screen.findByTestId("payroll-items");
    expect(tr(within(table).getByText("Can Kaya"))).toHaveTextContent("bordrosu mali müşavirde");
    expect(screen.getByText("Prim 5.000,00")).toBeInTheDocument();
    expect(
      screen.getByText(/Bordrosu mali müşavirde olan kişilere girilmiş 1 kalem var/),
    ).toBeInTheDocument();
    // Ay hazırlığında da.
    expect(
      screen.getByText(/girilmiş 1 kalem \(ERP bordrosunda hesaplanmaz\)/),
    ).toBeInTheDocument();
  });

  it("gelecek aya kalem girilemez", async () => {
    freezeToday();
    vi.mocked(payrollApi.getPayrollMonth).mockResolvedValue(
      month({ month: 12, period_label: "Aralık 2026" }),
    );
    renderApp("/personel/bordro?ay=2026-12&gorunum=kalemler");
    expect(await screen.findByText(/gelecek aya girilemez/)).toBeInTheDocument();
    for (const name of ["Kalem ekle", "Toplu ekle", "Geçen aydan kopyala"])
      expect(screen.getByRole("button", { name })).toBeDisabled();
  });

  it("nakit yemekte günlük SGK istisna sınırı girilmediyse uyarılır", async () => {
    const user = userEvent.setup();
    renderApp("/personel/bordro?ay=2026-10&gorunum=kalemler");
    await user.click(await screen.findByRole("button", { name: "Kalem ekle" }));
    const dialog = await screen.findByRole("dialog", { name: "Ek ödeme ya da kesinti" });
    await user.click(within(dialog).getByRole("textbox", { name: /Kalem/ }));
    await user.click(await screen.findByRole("option", { name: "Yemek (nakit)" }));
    expect(
      within(dialog).getByText(/günlük SGK istisna sınırı girilmedi \(0 TL\)/),
    ).toBeInTheDocument();
  });

  it("geçen aydan kopyalamada bu ayda zaten olan kalem işaretsiz gelir", async () => {
    const user = userEvent.setup();
    vi.mocked(payrollApi.listPayrollItems).mockImplementation(async (params) =>
      params.month === 9
        ? page([
            item({ id: 21, month: 9 }),
            item({
              id: 24,
              month: 9,
              category: "BONUS",
              category_label: "İkramiye",
              amount: "1000.00",
            }),
          ])
        : page([item({ id: 30 })]),
    );
    vi.mocked(payrollApi.addPayrollItems).mockResolvedValue([item({ id: 32 })]);
    renderApp("/personel/bordro?ay=2026-10&gorunum=kalemler");
    await user.click(await screen.findByRole("button", { name: "Geçen aydan kopyala" }));
    const dialog = await screen.findByRole("dialog", { name: "Eylül 2026 kalemlerini kopyala" });
    const premium = await within(dialog).findByRole("checkbox", {
      name: "Ayşe Demir Prim · 5.000,00",
    });
    await waitFor(() => expect(premium).not.toBeChecked());
    expect(within(dialog).getByText("bu ayda var")).toBeInTheDocument();
    expect(within(dialog).getByText(/Bu ayda zaten olan 1 kalem/)).toBeInTheDocument();
    expect(
      within(dialog).getByRole("checkbox", { name: "Ayşe Demir İkramiye · 1.000,00" }),
    ).toBeChecked();
    const add = within(dialog).getByRole("button", { name: "1 kalemi ekle" });
    await waitFor(() => expect(add).toBeEnabled());
    await user.click(add);
    await waitFor(() =>
      expect(payrollApi.addPayrollItems).toHaveBeenCalledWith(2026, 10, [
        { employee: 1, category: "BONUS", description: "", amount: "1000.00" },
      ]),
    );
  });
});

describe("bordro: devir yapıştırma, kaldırma ve onay", () => {
  const LABEL = "Kümülatif GV matrahı (Eylül 2026 dahil)";

  it("aradaki boş hücre kişiyi atlar; tutar ve ay sütunları ayrı okunur; okunamayan tutar kaydı durdurur", async () => {
    const user = userEvent.setup();
    vi.mocked(payrollApi.getPayrollMonth).mockResolvedValue(
      month({ rows: [AYSE_NEEDS, ECE_NEEDS, DENIZ] }),
    );
    vi.mocked(payrollApi.saveOpenings).mockResolvedValue([opening()]);
    renderApp("/personel/bordro?ay=2026-10");
    await user.click(await screen.findByRole("button", { name: "Devirler" }));
    const dialog = await screen.findByRole("dialog", { name: /Ekim 2026 devri/ });
    const box = (name: string) => within(dialog).getByLabelText(`${LABEL}: ${name}`);
    fireEvent.paste(box("Ayşe Demir"), {
      clipboardData: { getData: () => "400.000\r\n\r\n290.000\r\n" },
    });
    expect(box("Ayşe Demir")).toHaveValue("400.000");
    expect(box("Ece Ak")).toHaveValue("");
    expect(box("Deniz Su")).toHaveValue("290.000");
    expect(
      within(dialog).getByText("2 değer ekrandaki sırayla yerleştirildi; kişileri kontrol edin."),
    ).toBeInTheDocument();
    // Tutar ve istisna ay sütunları birlikte: ikinci hücre ay sayısıdır, tutara eklenmez.
    fireEvent.paste(box("Ece Ak"), { clipboardData: { getData: () => "382500\t8\r\n" } });
    expect(box("Ece Ak")).toHaveValue("382500");
    expect(within(dialog).getByLabelText("İstisna ay: Ece Ak")).toHaveValue("8");
    // Okunamayan tutar tek "Kaydet"i durdurur.
    await user.clear(box("Deniz Su"));
    await user.type(box("Deniz Su"), "290.000 X");
    expect(
      within(dialog).getByText("1 satırda tutar okunamadı: düzeltin ya da boşaltın."),
    ).toBeInTheDocument();
    const save = within(dialog).getByRole("button", { name: "Kaydet" });
    expect(save).toBeDisabled();
    await user.clear(box("Deniz Su"));
    await user.click(save);
    await waitFor(() =>
      expect(payrollApi.saveOpenings).toHaveBeenCalledWith(2026, 10, [
        { employee: 1, tax_base: "400000", exemption_months: 9, note: "", confirm_override: false },
        { employee: 3, tax_base: "382500", exemption_months: 8, note: "", confirm_override: false },
      ]),
    );
  });

  it("sicil no ile birlikte yapıştırılan satırlar sicille eşleşir; eşleşmeyenler söylenir", async () => {
    const user = userEvent.setup();
    vi.mocked(payrollApi.getPayrollMonth).mockResolvedValue(
      month({ rows: [AYSE_NEEDS, ECE_NEEDS, DENIZ] }),
    );
    renderApp("/personel/bordro?ay=2026-10");
    await user.click(await screen.findByRole("button", { name: "Devirler" }));
    const dialog = await screen.findByRole("dialog", { name: /Ekim 2026 devri/ });
    const box = (name: string) => within(dialog).getByLabelText(`${LABEL}: ${name}`);
    fireEvent.paste(box("Deniz Su"), {
      clipboardData: {
        getData: () => "S-3\tEce Ak\t290.000\t7\r\ns-1\t382.500,00\r\nS-9\t100\r\n",
      },
    });
    expect(box("Ece Ak")).toHaveValue("290.000");
    expect(within(dialog).getByLabelText("İstisna ay: Ece Ak")).toHaveValue("7");
    expect(box("Ayşe Demir")).toHaveValue("382.500,00");
    expect(box("Deniz Su")).toHaveValue("");
    expect(within(dialog).getByText(/yapıştırılmadı: S-9\./)).toBeInTheDocument();
    expect(within(dialog).getByText("2 değer sicil no ile eşleştirildi.")).toBeInTheDocument();
  });

  it("pencerede kaldırılan devir taslakta kalmaz; Esc yalnızca gerekçe penceresini kapatır; pencerenin ayı değişmez", async () => {
    const user = userEvent.setup();
    let removed = false;
    const november = opening({ month: 11, tax_base: "430000.00", exemption_months: 10 });
    const reanchored: PayrollRow = { ...AYSE, opening: november, openings: [november] };
    vi.mocked(payrollApi.getPayrollMonth).mockImplementation(async () =>
      month({
        month: 11,
        period_label: "Kasım 2026",
        rows: [removed ? AYSE_NEEDS : reanchored, ECE],
      }),
    );
    vi.mocked(payrollApi.removeOpening).mockImplementation(async () => {
      removed = true;
      return opening({ month: 11, is_active: false });
    });
    renderApp("/personel/bordro?ay=2026-11");
    await user.click(await screen.findByRole("button", { name: "Devirler" }));
    const title = "Kasım 2026 devri — Ekim 2026 sonu kümülatif";
    const dialog = await screen.findByRole("dialog", { name: title });
    await user.click(within(dialog).getByRole("switch", { name: /Herkes/ }));
    const label = "Kümülatif GV matrahı (Ekim 2026 dahil)";
    const box = (name: string) => within(dialog).getByLabelText(`${label}: ${name}`);
    expect(box("Ayşe Demir")).toHaveValue("430.000,00");
    await user.type(box("Ece Ak"), "300.000");
    // Esc gerekçe penceresini kapatır; devir penceresi ve taslak kalır.
    await user.click(within(dialog).getByRole("button", { name: "Devri kaldır: Ayşe Demir" }));
    await screen.findByRole("dialog", { name: "Devri kaldır" });
    await user.keyboard("{Escape}");
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Devri kaldır" })).not.toBeInTheDocument(),
    );
    expect(box("Ece Ak")).toHaveValue("300.000");
    // Kaldırılan devir yenilenen veriden boş açılır; Ayşe artık Ekim devrini beklese de pencere
    // Kasım'da kalır.
    await user.click(within(dialog).getByRole("button", { name: "Devri kaldır: Ayşe Demir" }));
    const reason = await screen.findByRole("dialog", { name: "Devri kaldır" });
    await user.type(within(reason).getByLabelText(/Kaldırma nedeni/), "Yanlış tutar");
    await user.click(within(reason).getByRole("button", { name: "Devri kaldır" }));
    await waitFor(() => expect(box("Ayşe Demir")).toHaveValue(""));
    expect(screen.getByRole("dialog", { name: title })).toBeInTheDocument();
    expect(box("Ece Ak")).toHaveValue("300.000");
  });

  it("sunucu eşitleme onayı isterse onay kutusu çıkar; onaylanınca yeniden gönderilir", async () => {
    const user = userEvent.setup();
    vi.mocked(payrollApi.getPayrollMonth).mockResolvedValue(
      month({ rows: [AYSE_NEEDS, CAN, ECE_NEEDS] }),
    );
    vi.mocked(payrollApi.saveOpenings)
      .mockRejectedValueOnce(
        httpError(400, {
          code: "batch_rejected",
          detail: "1 satır kaydedilemedi; hiçbir satır kaydedilmedi.",
          rows: [
            {
              index: 0,
              employee: 1,
              code: "opening_overrides_chain",
              detail: "Önceki ay ERP'de hesaplandı. Onaylayarak kaydedin.",
            },
          ],
        }),
      )
      .mockResolvedValueOnce([opening()]);
    renderApp("/personel/bordro?ay=2026-10");
    await user.click(await screen.findByRole("button", { name: "Devirler" }));
    const dialog = await screen.findByRole("dialog", { name: /Ekim 2026 devri/ });
    await user.type(within(dialog).getByLabelText(`${LABEL}: Ayşe Demir`), "382.500");
    expect(within(dialog).queryByRole("checkbox")).not.toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Kaydet" }));
    const confirm = await within(dialog).findByRole("checkbox", { name: /Onaylıyorum/ });
    const save = within(dialog).getByRole("button", { name: "Kaydet" });
    expect(save).toBeDisabled();
    await user.click(confirm);
    await user.click(save);
    await waitFor(() =>
      expect(payrollApi.saveOpenings).toHaveBeenLastCalledWith(2026, 10, [
        { employee: 1, tax_base: "382500", exemption_months: 9, note: "", confirm_override: true },
      ]),
    );
  });

  it("kaydedildikten sonra parametreleri değişen devir değiştirilmeden yeniden kaydedilebilir", async () => {
    const user = userEvent.setup();
    const stale: PayrollRow = {
      ...AYSE_NET,
      warnings: ["carry_incomplete"],
      carry_months: [carry({ flags: ["opening_stale"] })],
    };
    vi.mocked(payrollApi.getPayrollMonth).mockResolvedValue(month({ rows: [stale, CAN, ECE] }));
    vi.mocked(payrollApi.saveOpenings).mockResolvedValue([opening()]);
    renderApp("/personel/bordro?ay=2026-10");
    await user.click(await screen.findByRole("button", { name: "Döküm: Ayşe Demir" }));
    const drawer = await screen.findByRole("dialog", { name: "Ayşe Demir · Ekim 2026" });
    expect(
      within(drawer).getByText("parametreler değişti: devri yeniden kaydedin"),
    ).toBeInTheDocument();
    await user.click(within(drawer).getByRole("tab", { name: "Devir" }));
    await user.click(within(drawer).getByRole("button", { name: "Devri düzelt" }));
    const dialog = await screen.findByRole("dialog", {
      name: "Ekim 2026 devri — Eylül 2026 sonu kümülatif",
    });
    await user.click(within(dialog).getByRole("button", { name: "Kaydet" }));
    await waitFor(() =>
      expect(payrollApi.saveOpenings).toHaveBeenCalledWith(2026, 10, [
        {
          employee: 1,
          tax_base: "382500.00",
          exemption_months: 9,
          note: "",
          confirm_override: false,
        },
      ]),
    );
  });

  it("ay hazırlığı devri eksik kişileri giriş ayına göre ayırır; her satır kendi ayını açar", async () => {
    const user = userEvent.setup();
    vi.mocked(payrollApi.getPayrollMonth).mockResolvedValue(
      month({
        month: 11,
        period_label: "Kasım 2026",
        rows: [AYSE_NEEDS, { ...DENIZ, entry_month: 11 }],
      }),
    );
    renderApp("/personel/bordro?ay=2026-11");
    expect(await screen.findByText(/1 kişinin Ekim 2026 devri girilmedi/)).toBeInTheDocument();
    expect(screen.getByText(/1 kişinin Kasım 2026 devri girilmedi/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Devir gir: Kasım 2026" }));
    const dialog = await screen.findByRole("dialog", {
      name: "Kasım 2026 devri — Ekim 2026 sonu kümülatif",
    });
    expect(within(dialog).getByText("Deniz Su")).toBeInTheDocument();
    expect(within(dialog).queryByText("Ayşe Demir")).not.toBeInTheDocument();
  });
});

describe("bordro: devir yapıştırmanın kenar durumları ve gelecek ay", () => {
  const LABEL = "Kümülatif GV matrahı (Eylül 2026 dahil)";
  const open = async (rows: PayrollRow[]) => {
    const user = userEvent.setup();
    vi.mocked(payrollApi.getPayrollMonth).mockResolvedValue(month({ rows }));
    renderApp("/personel/bordro?ay=2026-10");
    await user.click(await screen.findByRole("button", { name: "Devirler" }));
    const dialog = await screen.findByRole("dialog", { name: /Ekim 2026 devri/ });
    const box = (name: string) => within(dialog).getByLabelText(`${LABEL}: ${name}`);
    return { user, dialog, box };
  };

  it("sicil no ve tutar yapıştırılıp hiçbir sicil eşleşmezse hiçbir kutu dolmaz", async () => {
    const { dialog, box } = await open([AYSE_NEEDS, ECE_NEEDS, DENIZ]);
    fireEvent.paste(box("Ayşe Demir"), {
      clipboardData: { getData: () => "12\t382.500,00\r\n15\t410.000,00\r\n" },
    });
    for (const name of ["Ayşe Demir", "Ece Ak", "Deniz Su"]) expect(box(name)).toHaveValue("");
    expect(within(dialog).getByText(/yapıştırılmadı: 12, 15\./)).toBeInTheDocument();
    expect(within(dialog).queryByText(/değer ekrandaki sırayla/)).not.toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Kaydet" })).toBeDisabled();
    // Tek satır da: sicil no tutar sanılmaz.
    fireEvent.paste(box("Ece Ak"), { clipboardData: { getData: () => "1001\t382.500,00" } });
    expect(box("Ece Ak")).toHaveValue("");
    expect(within(dialog).getByText(/yapıştırılmadı: 1001\./)).toBeInTheDocument();
  });

  it("sicil eşleşmesi baştaki sıfırları ve i / İ farkını önemsemez; başlık satırı atlanır", async () => {
    const ali: PayrollRow = {
      ...ECE_NEEDS,
      employee: { ...ECE_NEEDS.employee, employee_no: "PI-01", full_name: "Ali Işık" },
    };
    const { dialog, box } = await open([
      { ...AYSE_NEEDS, employee: { ...AYSE_NEEDS.employee, employee_no: "0012" } },
      ali,
      DENIZ,
    ]);
    fireEvent.paste(box("Deniz Su"), {
      clipboardData: {
        getData: () =>
          "Sicil no\tAd soyad\tMatrah\r\n12\tAyşe Demir\t382.500,00\r\npi-01\tAli Işık\t#YOK\r\nS-4\tDeniz Su\r\n",
      },
    });
    expect(box("Ayşe Demir")).toHaveValue("382.500,00");
    // Okunamayan tutar kutuya yazılır ve kaydı durdurur; tutarı olmayan satır söylenir.
    expect(box("Ali Işık")).toHaveValue("#YOK");
    expect(
      within(dialog).getByText("1 satırda tutar okunamadı: düzeltin ya da boşaltın."),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByText("Tutarı bulunamayan satırlar yapıştırılmadı: S-4."),
    ).toBeInTheDocument();
    expect(within(dialog).queryByText(/Sicil no'su bu listede olmayan/)).not.toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Kaydet" })).toBeDisabled();
  });

  it("tutarın başında TL olabilir", async () => {
    vi.mocked(payrollApi.saveOpenings).mockResolvedValue([opening()]);
    const { user, dialog, box } = await open([AYSE_NEEDS, ECE_NEEDS]);
    await user.type(box("Ayşe Demir"), "TL 400.000");
    await user.click(within(dialog).getByRole("button", { name: "Kaydet" }));
    await waitFor(() =>
      expect(payrollApi.saveOpenings).toHaveBeenCalledWith(2026, 10, [
        { employee: 1, tax_base: "400000", exemption_months: 9, note: "", confirm_override: false },
      ]),
    );
  });

  it("'Yalnızca girilmeyenler' yapıştırmayla değişen girilmiş devri gizlemez", async () => {
    const { user, dialog, box } = await open([AYSE_NET, CAN, ECE_NEEDS]);
    await user.click(within(dialog).getByRole("switch", { name: "Yalnızca girilmeyenler" }));
    expect(within(dialog).queryByLabelText(`${LABEL}: Ayşe Demir`)).not.toBeInTheDocument();
    fireEvent.paste(box("Ece Ak"), {
      clipboardData: { getData: () => "S-1\t400.000,00\r\nS-3\t290.000,00\r\n" },
    });
    expect(box("Ayşe Demir")).toHaveValue("400.000,00");
    expect(box("Ece Ak")).toHaveValue("290.000,00");
    // Düzenlenen satır, yazılan değer girilmiş devre eşitlense de görünür kalır.
    await user.clear(box("Ayşe Demir"));
    await user.type(box("Ayşe Demir"), "382.500,50");
    expect(box("Ayşe Demir")).toHaveValue("382.500,50");
  });

  it("tutar sütunu bir kez seçilir: boş tutar hücresinde ay sayısı tutar sayılmaz", async () => {
    vi.mocked(payrollApi.saveOpenings).mockResolvedValue([opening()]);
    const { user, dialog, box } = await open([AYSE_NEEDS, ECE_NEEDS, DENIZ]);
    fireEvent.paste(box("Ayşe Demir"), {
      clipboardData: {
        getData: () =>
          "S-1\tAyşe Demir\t382.500,00\t9\r\nS-3\tEce Ak\t\t9\r\nS-4\tDeniz Su\t290.000,00\t8",
      },
    });
    expect(box("Ece Ak")).toHaveValue("");
    expect(
      within(dialog).getByText("Tutarı bulunamayan satırlar yapıştırılmadı: S-3."),
    ).toBeInTheDocument();
    expect(within(dialog).getByText("2 değer sicil no ile eşleştirildi.")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Kaydet" }));
    await waitFor(() =>
      expect(payrollApi.saveOpenings).toHaveBeenCalledWith(2026, 10, [
        {
          employee: 1,
          tax_base: "382500.00",
          exemption_months: 9,
          note: "",
          confirm_override: false,
        },
        {
          employee: 4,
          tax_base: "290000.00",
          exemption_months: 8,
          note: "",
          confirm_override: false,
        },
      ]),
    );
  });

  it("tutar sütunundaki okunamayan değer kaydı durdurur; birden çok sayı sütunu varsa kutu dolmaz", async () => {
    const { dialog, box } = await open([AYSE_NEEDS, ECE_NEEDS, DENIZ]);
    fireEvent.paste(box("Ayşe Demir"), {
      clipboardData: {
        getData: () => "S-1\tAyşe Demir\t382.500,00\t9\r\nS-3\tEce Ak\tyok\t9\r\n",
      },
    });
    expect(box("Ece Ak")).toHaveValue("yok");
    expect(
      within(dialog).getByText("1 satırda tutar okunamadı: düzeltin ya da boşaltın."),
    ).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Kaydet" })).toBeDisabled();
    // TC kimlik no sütunuyla tutar sütunu belirlenemez: hiçbir kutu dolmaz.
    fireEvent.paste(box("Deniz Su"), {
      clipboardData: { getData: () => "S-4\t12345678901\tDeniz Su\t310.000,00\t9\r\n" },
    });
    expect(box("Deniz Su")).toHaveValue("");
    expect(within(dialog).getByText(/Tutar sütunu belirlenemedi/)).toBeInTheDocument();
  });

  it("aynı sicil no farklı değerle iki satırda geçerse o kişi doldurulmaz", async () => {
    const { dialog, box } = await open([AYSE_NEEDS, ECE_NEEDS, DENIZ]);
    fireEvent.paste(box("Ayşe Demir"), {
      clipboardData: {
        getData: () =>
          "S-1\t100.000,00\r\nS-3\t290.000\r\ns-1\t382.500,00\r\nS-4\t310.000\r\nS-4\t310.000\r\n",
      },
    });
    expect(box("Ayşe Demir")).toHaveValue("");
    expect(box("Ece Ak")).toHaveValue("290.000");
    expect(box("Deniz Su")).toHaveValue("310.000");
    expect(
      within(dialog).getByText(
        "Birden fazla satırda farklı değerle geçen sicil no'lar yapıştırılmadı: S-1.",
      ),
    ).toBeInTheDocument();
    expect(within(dialog).getByText("2 değer sicil no ile eşleştirildi.")).toBeInTheDocument();
  });

  it("önceki ayın penceresi kişinin o ayki devrini gösterir (sonraki ayda devri olsa da)", async () => {
    const user = userEvent.setup();
    const november = opening({ id: 6, month: 11, tax_base: "430000.00", exemption_months: 10 });
    const ayse: PayrollRow = {
      ...AYSE,
      opening: november,
      openings: [opening(), november],
      entry_month: 10,
    };
    vi.mocked(payrollApi.getPayrollMonth).mockResolvedValue(
      month({ month: 11, period_label: "Kasım 2026", rows: [ayse, DENIZ] }),
    );
    renderApp("/personel/bordro?ay=2026-11");
    await user.click(await screen.findByRole("button", { name: "Devirler" }));
    const dialog = await screen.findByRole("dialog", { name: /Ekim 2026 devri/ });
    await user.click(within(dialog).getByRole("switch", { name: /Herkes/ }));
    expect(within(dialog).getByLabelText(`${LABEL}: Ayşe Demir`)).toHaveValue("382.500,00");
    expect(within(dialog).getByText("1/2 girildi")).toBeInTheDocument();
    expect(
      within(dialog).getByRole("button", { name: "Devri kaldır: Ayşe Demir" }),
    ).toBeInTheDocument();
  });

  it("parametreleri değişen devir ay hazırlığındaki bağlantıyla yeniden kaydedilir (sonraki aydan)", async () => {
    const user = userEvent.setup();
    const stale: PayrollRow = {
      ...AYSE_NET,
      warnings: ["carry_incomplete"],
      carry_months: [
        carry({ flags: ["opening_stale"] }),
        carry({ kind: "erp", tax_base: "38250.00", exemption_base: "28075.50" }),
      ],
    };
    vi.mocked(payrollApi.getPayrollMonth).mockResolvedValue(
      month({ month: 11, period_label: "Kasım 2026", rows: [stale, CAN, ECE] }),
    );
    vi.mocked(payrollApi.saveOpenings).mockResolvedValue([opening()]);
    renderApp("/personel/bordro?ay=2026-11");
    expect(
      await screen.findByText(
        /1 kişinin Ekim 2026 devri kaydedildikten sonra parametreler değişti/,
      ),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Devri yeniden kaydet: Ekim 2026" }));
    const dialog = await screen.findByRole("dialog", {
      name: "Ekim 2026 devri — Eylül 2026 sonu kümülatif",
    });
    expect(
      within(dialog).getByText("parametreler değişti: devri yeniden kaydedin"),
    ).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Kaydet" }));
    await waitFor(() =>
      expect(payrollApi.saveOpenings).toHaveBeenCalledWith(2026, 10, [
        {
          employee: 1,
          tax_base: "382500.00",
          exemption_months: 9,
          note: "",
          confirm_override: false,
        },
      ]),
    );
  });

  it("gelecek aya devir girilmez: bağlantı yok, düğmeler kapalı, ipucu var", async () => {
    freezeToday();
    const user = userEvent.setup();
    vi.mocked(payrollApi.getPayrollMonth).mockResolvedValue(
      month({
        month: 12,
        period_label: "Aralık 2026",
        rows: [AYSE, { ...DENIZ, entry_month: 12 }],
      }),
    );
    renderApp("/personel/bordro?ay=2026-12");
    expect(await screen.findByText(/1 kişinin Aralık 2026 devri girilmedi/)).toBeInTheDocument();
    expect(screen.getByText("ay gelince girilir")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Devir gir: Aralık 2026" }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Devirler" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Döküm: Ayşe Demir" }));
    let drawer = await screen.findByRole("dialog", { name: "Ayşe Demir · Aralık 2026" });
    await user.click(within(drawer).getByRole("tab", { name: "Devir" }));
    expect(within(drawer).getByText(/gelecek aya girilemez/)).toBeInTheDocument();
    expect(
      within(drawer).queryByRole("button", { name: /Bu aydan devir gir/ }),
    ).not.toBeInTheDocument();
    // Giriş ayı gelecekte olan kişinin "Devir gir" düğmesi de kapalı.
    await user.click(within(drawer).getByRole("button", { name: "Sonraki kişi" }));
    drawer = await screen.findByRole("dialog", { name: "Deniz Su · Aralık 2026" });
    expect(within(drawer).getByRole("button", { name: "Devir gir" })).toBeDisabled();
    expect(payrollApi.saveOpenings).not.toHaveBeenCalled();
  });

  it("eşitleme devri parametreleri değişince ay hazırlığındaki bağlantıyla onaylanarak yeniden kaydedilir", async () => {
    const user = userEvent.setup();
    const november = opening({ id: 6, month: 11, tax_base: "430000.00", exemption_months: 10 });
    const ayse: PayrollRow = {
      ...AYSE,
      opening: november,
      openings: [opening(), november],
      entry_month: 10,
      warnings: ["carry_incomplete"],
      carry_months: [carry({ month: 11, tax_base: "430000.00", flags: ["opening_stale"] })],
    };
    vi.mocked(payrollApi.getPayrollMonth).mockResolvedValue(
      month({ month: 11, period_label: "Kasım 2026", rows: [ayse, ECE] }),
    );
    vi.mocked(payrollApi.saveOpenings).mockResolvedValue([november]);
    renderApp("/personel/bordro?ay=2026-11");
    await user.click(
      await screen.findByRole("button", { name: "Devri yeniden kaydet: Kasım 2026" }),
    );
    expect(screen.queryByText("Devirler tamam")).not.toBeInTheDocument();
    const dialog = await screen.findByRole("dialog", {
      name: "Kasım 2026 devri — Ekim 2026 sonu kümülatif",
    });
    expect(
      within(dialog).getByLabelText("Kümülatif GV matrahı (Ekim 2026 dahil): Ayşe Demir"),
    ).toHaveValue("430.000,00");
    await user.click(within(dialog).getByRole("checkbox", { name: /Onaylıyorum/ }));
    await user.click(within(dialog).getByRole("button", { name: "Kaydet" }));
    await waitFor(() =>
      expect(payrollApi.saveOpenings).toHaveBeenCalledWith(2026, 11, [
        {
          employee: 1,
          tax_base: "430000.00",
          exemption_months: 10,
          note: "",
          confirm_override: true,
        },
      ]),
    );
  });
});

describe("bordro: kopyalama ve kalem adları", () => {
  it("geçen aydan kopyalamada seçim bu ayın listesi okunana kadar kapalıdır", async () => {
    const user = userEvent.setup();
    type ItemsPage = Awaited<ReturnType<typeof payrollApi.listPayrollItems>>;
    let resolve: (value: ItemsPage) => void = () => {};
    vi.mocked(payrollApi.listPayrollItems).mockImplementation((params) =>
      params.month === 9
        ? Promise.resolve(page([item({ id: 21, month: 9 })]))
        : new Promise<ItemsPage>((done) => {
            resolve = done;
          }),
    );
    renderApp("/personel/bordro?ay=2026-10&gorunum=kalemler");
    await user.click(await screen.findByRole("button", { name: "Geçen aydan kopyala" }));
    const dialog = await screen.findByRole("dialog", { name: "Eylül 2026 kalemlerini kopyala" });
    const premium = await within(dialog).findByRole("checkbox", {
      name: "Ayşe Demir Prim · 5.000,00",
    });
    expect(premium).toBeDisabled();
    expect(within(dialog).getByRole("button", { name: "1 kalemi ekle" })).toBeDisabled();
    await act(async () => resolve(page([item({ id: 30 })])));
    await waitFor(() => expect(premium).toBeEnabled());
    expect(premium).not.toBeChecked();
    expect(within(dialog).getByText("bu ayda var")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "0 kalemi ekle" })).toBeDisabled();
  });

  it("yeniden açılan kopyalama penceresi iki listeyi de yeniden okumadan seçime açılmaz", async () => {
    const user = userEvent.setup();
    type ItemsPage = Awaited<ReturnType<typeof payrollApi.listPayrollItems>>;
    let resolve: (value: ItemsPage) => void = () => {};
    let deferred = false;
    vi.mocked(payrollApi.listPayrollItems).mockImplementation((params) => {
      if (params.month === 9) return Promise.resolve(page([item({ id: 21, month: 9 })]));
      if (!deferred) return Promise.resolve(page([]));
      return new Promise<ItemsPage>((done) => {
        resolve = done;
      });
    });
    renderApp("/personel/bordro?ay=2026-10&gorunum=kalemler");
    await user.click(await screen.findByRole("button", { name: "Geçen aydan kopyala" }));
    let dialog = await screen.findByRole("dialog", { name: "Eylül 2026 kalemlerini kopyala" });
    await waitFor(() =>
      expect(within(dialog).getByRole("button", { name: "1 kalemi ekle" })).toBeEnabled(),
    );
    await user.click(within(dialog).getByRole("button", { name: "Vazgeç" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    // Bu arada bu aya aynı Prim girildi; ikinci açılışta önbellekteki boş liste kullanılmaz.
    deferred = true;
    await user.click(screen.getByRole("button", { name: "Geçen aydan kopyala" }));
    dialog = await screen.findByRole("dialog", { name: "Eylül 2026 kalemlerini kopyala" });
    const premium = within(dialog).getByRole("checkbox", { name: "Ayşe Demir Prim · 5.000,00" });
    expect(premium).toBeDisabled();
    expect(within(dialog).getByRole("button", { name: "1 kalemi ekle" })).toBeDisabled();
    await act(async () => resolve(page([item({ id: 30 })])));
    await waitFor(() => expect(premium).toBeEnabled());
    expect(premium).not.toBeChecked();
    expect(within(dialog).getByText("bu ayda var")).toBeInTheDocument();
    expect(payrollApi.addPayrollItems).not.toHaveBeenCalled();
  });

  it("aynı kişinin aynı kalemleri tutarla ayırt edilir", async () => {
    const user = userEvent.setup();
    const small = item({
      id: 41,
      kind: "DEDUCTION",
      category: "ADVANCE",
      category_label: "Avans",
      amount: "1000.00",
    });
    const large = { ...small, id: 42, amount: "2000.00" };
    vi.mocked(payrollApi.getPayrollMonth).mockResolvedValue(
      month({ rows: [{ ...AYSE_NET, items: [small, large] }, CAN, ECE_NEEDS] }),
    );
    vi.mocked(payrollApi.removePayrollItem).mockResolvedValue({ ...large, is_active: false });
    renderApp("/personel/bordro?ay=2026-10&gorunum=kalemler");
    const table = await screen.findByTestId("payroll-items");
    expect(
      within(table).getByRole("button", { name: "Kaldır: Ayşe Demir Avans · 1.000,00" }),
    ).toBeInTheDocument();
    await user.click(
      within(table).getByRole("button", { name: "Kaldır: Ayşe Demir Avans · 2.000,00" }),
    );
    const reason = await screen.findByRole("dialog", { name: "Kalemi kaldır" });
    await user.type(within(reason).getByLabelText(/Kaldırma nedeni/), "Fazla girildi");
    await user.click(within(reason).getByRole("button", { name: "Kaldır" }));
    await waitFor(() =>
      expect(payrollApi.removePayrollItem).toHaveBeenCalledWith(42, "Fazla girildi"),
    );
  });
});
