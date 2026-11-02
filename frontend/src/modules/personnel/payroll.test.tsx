import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as authApi from "../../api/auth";
import * as payrollApi from "../../api/payroll";
import type {
  ParameterSet,
  PayrollLine,
  PayrollMonth,
  PayrollRow,
  PayrollValues,
} from "../../api/payroll";
import * as workflowApi from "../../api/workflow";
import { httpError, page, userWith } from "../../test/fixtures";
import { renderApp } from "../../test/render";

vi.mock("../../api/auth");
vi.mock("../../api/workflow");
vi.mock("../../api/payroll", async (importOriginal) => ({
  // Sorgu anahtarları ve dosya adresleri gerçek kalır.
  ...(await importOriginal<typeof payrollApi>()),
  getPayrollMonth: vi.fn(),
  setExternalFigure: vi.fn(),
  listParameterSets: vi.fn(),
  getParameterDefaults: vi.fn(),
  saveParameterSet: vi.fn(),
  removeParameterSet: vi.fn(),
}));

const VALUES: PayrollValues = {
  minimum_wage: "33030.00",
  daily_floor: "1101.00",
  daily_ceiling: "9909.00",
  ceiling_multiplier: "9.00",
  employee_sgk_rate: "14.00",
  employee_unemployment_rate: "1.00",
  employer_sgk_rate: "21.75",
  employer_unemployment_rate: "2.00",
  incentive_points: "5.00",
  employer_rate: "18.75",
  stamp_tax_per_mille: "7.590",
  tax_brackets: ["190000.00", "400000.00", "1500000.00", "5300000.00"],
  tax_rates: ["15.00", "20.00", "27.00", "35.00", "40.00"],
  exemption_base: "28075.50",
  bes_rate: "3.00",
};

function line(extra: Partial<PayrollLine> = {}): PayrollLine {
  return {
    employed_days: 31,
    paid_days: 30,
    unpaid_days: 0,
    sick_days: 0,
    unpaid_leave_days: 0,
    absent_days: 0,
    sgk_days: 30,
    monthly_wage: "45000.00",
    missing_wage: false,
    salary: "45000.00",
    overtime_worked_hours: "0.00",
    overtime_worked_pay: "0.00",
    overtime_rest_hours: "0.00",
    overtime_rest_pay: "0.00",
    holiday_days: 0,
    holiday_half_days: 0,
    holiday_hours: "0.00",
    holiday_extra_hours: "0.00",
    holiday_pay: "0.00",
    extras: [],
    extras_total: "0.00",
    gross_total: "45000.00",
    sgk_base: "45000.00",
    floor_applied: false,
    ceiling_applied: false,
    employee_sgk: "6300.00",
    employee_unemployment: "450.00",
    tax_base: "38250.00",
    cumulative_tax_base_before: "0.00",
    cumulative_tax_base_after: "38250.00",
    income_tax_computed: "5737.50",
    income_tax_exemption: "4211.33",
    income_tax: "1526.17",
    exemption_base_before: "0.00",
    exemption_base_added: "28075.50",
    stamp_tax_computed: "341.55",
    stamp_tax_exemption: "250.70",
    stamp_tax: "90.85",
    net_pay: "36632.98",
    bes_deduction: "0.00",
    deductions: [],
    deductions_total: "0.00",
    payable: "36632.98",
    employer_sgk_gross: "9787.50",
    incentive: "2250.00",
    employer_sgk: "7537.50",
    employer_unemployment: "900.00",
    floor_gap: "0.00",
    employer_cost: "53437.50",
    ...extra,
  };
}

const AYSE: PayrollRow = {
  employee: {
    id: 1,
    employee_no: "S-1",
    full_name: "Ayşe Demir",
    department: "Dolum",
    title: "Operatör",
    hire_date: "2024-01-01",
    termination_date: null,
    is_active: true,
    payroll_external: false,
    bes_enrolled: false,
  },
  external: false,
  figure: null,
  warnings: [],
  line: line(),
  gross_total: "45000.00",
  employer_cost: "53437.50",
};
const CAN: PayrollRow = {
  ...AYSE,
  employee: {
    ...AYSE.employee,
    id: 2,
    employee_no: "S-2",
    full_name: "Can Kaya",
    payroll_external: true,
  },
  external: true,
  warnings: ["external_missing"],
  line: line(),
  gross_total: "0.00",
  employer_cost: "0.00",
};
const ECE: PayrollRow = {
  ...AYSE,
  employee: { ...AYSE.employee, id: 3, employee_no: "S-3", full_name: "Ece Ak" },
  warnings: ["below_minimum_wage"],
  line: line({ floor_applied: true, gross_total: "30000.00", floor_gap: "454.50" }),
  gross_total: "30000.00",
  employer_cost: "36647.63",
};

function month(extra: Partial<PayrollMonth> = {}): PayrollMonth {
  return {
    year: 2026,
    month: 10,
    period_label: "Ekim 2026",
    attendance_status: "OPEN",
    attendance_number: "",
    attendance_approved: false,
    attendance_finished: true,
    parameters: {
      origin: "legal_default",
      year: 2026,
      record: null,
      valid_from: null,
      values: VALUES,
    },
    rows: [AYSE, CAN, ECE],
    totals: {
      employee_count: 3,
      external_count: 1,
      gross_total: "75000.00",
      employer_cost: "90085.13",
      salary: "75000.00",
      overtime_worked_pay: "0.00",
      overtime_rest_pay: "0.00",
      holiday_pay: "0.00",
      extras_total: "0.00",
      sgk_base: "78030.00",
      employee_sgk: "10500.00",
      employee_unemployment: "750.00",
      income_tax: "1526.17",
      stamp_tax: "90.85",
      net_pay: "63000.00",
      bes_deduction: "0.00",
      deductions_total: "0.00",
      payable: "63000.00",
      employer_sgk_gross: "16971.53",
      incentive: "3901.50",
      employer_sgk: "13070.03",
      employer_unemployment: "1560.60",
      floor_gap: "454.50",
    },
    ...extra,
  };
}

function savedSet(extra: Partial<ParameterSet> = {}): ParameterSet {
  return {
    id: 4,
    valid_from: "2026-01-01",
    minimum_wage: "33030.00",
    ceiling_multiplier: "9.00",
    employee_sgk_rate: "14.00",
    employee_unemployment_rate: "1.00",
    employer_sgk_rate: "21.75",
    employer_unemployment_rate: "2.00",
    incentive_points: "5.00",
    stamp_tax_per_mille: "7.590",
    tax_bracket_1: "190000.00",
    tax_bracket_2: "400000.00",
    tax_bracket_3: "1500000.00",
    tax_bracket_4: "5300000.00",
    tax_rate_1: "15.00",
    tax_rate_2: "20.00",
    tax_rate_3: "27.00",
    tax_rate_4: "35.00",
    tax_rate_5: "40.00",
    bes_rate: "3.00",
    source: "RG",
    note: "",
    year: 2026,
    derived: VALUES,
    is_active: true,
    created_at: "2026-11-01T10:00:00+03:00",
    updated_at: "2026-11-01T10:00:00+03:00",
    updated_by_name: "Yönetim",
    ...extra,
  };
}

function savedMonth(): PayrollMonth {
  return month({
    parameters: {
      origin: "saved",
      year: 2026,
      record: 4,
      valid_from: "2026-01-01",
      values: VALUES,
    },
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(authApi.fetchCsrf).mockResolvedValue();
  vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("yonetim"));
  vi.mocked(workflowApi.fetchTasks).mockResolvedValue(page([]));
  vi.mocked(workflowApi.fetchNotifications).mockResolvedValue(page([]));
  vi.mocked(workflowApi.fetchUnreadCount).mockResolvedValue(0);
  vi.mocked(payrollApi.getPayrollMonth).mockResolvedValue(month());
  vi.mocked(payrollApi.listParameterSets).mockResolvedValue([]);
  vi.mocked(payrollApi.getParameterDefaults).mockResolvedValue({
    year: 2026,
    known: true,
    values_year: 2026,
    legal_source: "RG 26.12.2025",
    values: VALUES,
  });
});

describe("bordro: işveren maliyeti", () => {
  it("ayın işveren maliyeti tablosunu, toplamları, uyarıları ve çıktıları gösterir", async () => {
    const user = userEvent.setup();
    renderApp("/personel/bordro?ay=2026-10");
    const ayse = (await screen.findByText("Ayşe Demir")).closest("tr")!;
    expect(payrollApi.getPayrollMonth).toHaveBeenCalledWith(2026, 10);
    expect(screen.getByRole("tab", { name: "Bordro" })).toHaveAttribute("aria-selected", "true");
    expect(within(ayse).getByText("9.787,50")).toBeInTheDocument();
    expect(within(ayse).getByText("−2.250,00")).toBeInTheDocument();
    expect(within(ayse).getByText("53.437,50")).toBeInTheDocument();
    expect(within(ayse).getByText("%118,75")).toBeInTheDocument();
    expect(screen.getByText("SGK işveren (%21,75)")).toBeInTheDocument();
    expect(screen.getByText("Teşvik (5 puan)")).toBeInTheDocument();
    // Uyarılar: parametreler kaydedilmedi, puantaj açık, mali müşavir rakamı yok, asgari ücret altı.
    expect(screen.getByText("Parametreler kaydedilmedi")).toBeInTheDocument();
    expect(
      screen.getByText(
        /Bu ay için geçerli kayıtlı parametre seti yok; hesap 2026 yasal değerleriyle/,
      ),
    ).toBeInTheDocument();
    expect(screen.getByText(/Ayın puantajı onaylanmadı/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Puantajı aç" })).toHaveAttribute(
      "href",
      "/personel/puantaj?ay=2026-10",
    );
    expect(screen.getByText(/olan 1 kişinin bu ay rakamları girilmedi/)).toBeInTheDocument();
    const ece = screen.getByText("Ece Ak").closest("tr")!;
    expect(within(ece).getByText("Asgari ücretin altında")).toBeInTheDocument();
    expect(within(ece).getByText("Alt sınır")).toBeInTheDocument();
    const can = screen.getByText("Can Kaya").closest("tr")!;
    expect(within(can).getByText("Bordrosu mali müşavirde")).toBeInTheDocument();
    expect(within(can).getAllByText("—")).toHaveLength(6);
    // Genel toplam ve özet.
    const total = screen.getByText("Genel toplam").closest("tr")!;
    expect(within(total).getByText("90.085,13")).toBeInTheDocument();
    expect(screen.getByText("90.085,13 TL")).toBeInTheDocument();
    expect(screen.getByText("%18,75")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "İşveren maliyeti (PDF)" })).toHaveAttribute(
      "href",
      "/api/v1/personnel/payroll/2026/10/employer-cost.pdf",
    );
    expect(screen.getByRole("link", { name: "Excel" })).toHaveAttribute(
      "href",
      "/api/v1/personnel/payroll/2026/10/xlsx/",
    );
    await user.click(screen.getByRole("button", { name: "Önceki ay" }));
    await waitFor(() => expect(payrollApi.getPayrollMonth).toHaveBeenCalledWith(2026, 9));
  });

  it("bordrosu mali müşavirde olan kişinin rakamları girilir", async () => {
    const user = userEvent.setup();
    vi.mocked(payrollApi.setExternalFigure).mockResolvedValue({
      id: 1,
      employee: 2,
      year: 2026,
      month: 10,
      gross_total: "41000.00",
      employer_cost: "50000.00",
      note: "",
      updated_at: "",
      updated_by_name: null,
    });
    renderApp("/personel/bordro?ay=2026-10");
    await user.click(await screen.findByRole("button", { name: "Rakamları gir: Can Kaya" }));
    const dialog = await screen.findByRole("dialog");
    const gross = within(dialog).getByLabelText(/Brüt toplam/);
    const cost = within(dialog).getByLabelText(/İşverene maliyet/);
    await user.type(gross, "41.000");
    await user.type(cost, "40.000");
    expect(within(dialog).getByText(/brüt toplamdan az olamaz/)).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Kaydet" })).toBeDisabled();
    await user.clear(cost);
    await user.type(cost, "50.000");
    await user.click(within(dialog).getByRole("button", { name: "Kaydet" }));
    await waitFor(() =>
      expect(payrollApi.setExternalFigure).toHaveBeenCalledWith(2026, 10, {
        employee: 2,
        gross_total: "41000",
        employer_cost: "50000",
        note: "",
      }),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await waitFor(() => expect(payrollApi.getPayrollMonth).toHaveBeenCalledTimes(2));
  });

  it("mali müşavir rakamları sıfır olabilir; notta nedenin yazılmaması hatırlatılır", async () => {
    const user = userEvent.setup();
    vi.mocked(payrollApi.setExternalFigure).mockResolvedValue({
      id: 1,
      employee: 2,
      year: 2026,
      month: 10,
      gross_total: "0.00",
      employer_cost: "0.00",
      note: "",
      updated_at: "",
      updated_by_name: null,
    });
    renderApp("/personel/bordro?ay=2026-10");
    await user.click(await screen.findByRole("button", { name: "Rakamları gir: Can Kaya" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/Özel durumun nedenini/)).toBeInTheDocument();
    await user.type(within(dialog).getByLabelText(/Brüt toplam/), "0");
    await user.type(within(dialog).getByLabelText(/İşverene maliyet/), "0");
    const save = within(dialog).getByRole("button", { name: "Kaydet" });
    expect(save).toBeEnabled();
    await user.click(save);
    await waitFor(() =>
      expect(payrollApi.setExternalFigure).toHaveBeenCalledWith(2026, 10, {
        employee: 2,
        gross_total: "0",
        employer_cost: "0",
        note: "",
      }),
    );
  });

  it("kayıtlı sıfır brütlü rakam düzeltilmek üzere geçerli açılır", async () => {
    const user = userEvent.setup();
    const figure = {
      id: 1,
      employee: 2,
      year: 2026,
      month: 10,
      gross_total: "0.00",
      employer_cost: "1500.00",
      note: "",
      updated_at: "",
      updated_by_name: null,
    };
    vi.mocked(payrollApi.getPayrollMonth).mockResolvedValue(
      month({
        rows: [
          AYSE,
          { ...CAN, figure, warnings: [], gross_total: "0.00", employer_cost: "1500.00" },
          ECE,
        ],
      }),
    );
    renderApp("/personel/bordro?ay=2026-10");
    await user.click(await screen.findByRole("button", { name: "Rakamları düzelt: Can Kaya" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByLabelText(/Brüt toplam/)).toHaveValue("0,00");
    expect(within(dialog).queryByText(/Geçerli bir tutar girin/)).not.toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Kaydet" })).toBeEnabled();
  });

  it("yönetim dışındaki rol bordroyu açamaz", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("dolum"));
    renderApp("/personel/bordro");
    expect(await screen.findByText("Yetkiniz yok")).toBeInTheDocument();
    expect(payrollApi.getPayrollMonth).not.toHaveBeenCalled();
  });
});

describe("bordro parametreleri", () => {
  it("yeni set yasal değerlerle dolu gelir; teşvik seçilir ve kaydedilir", async () => {
    const user = userEvent.setup();
    vi.mocked(payrollApi.saveParameterSet).mockResolvedValue(savedSet());
    renderApp("/personel/bordro?ay=2026-10");
    await user.click(await screen.findByRole("button", { name: "Parametreler" }));
    const dialog = await screen.findByRole("dialog");
    const wage = await within(dialog).findByLabelText("Asgari ücret (aylık brüt, TL)");
    expect(wage).toHaveValue("33030");
    expect(within(dialog).getByLabelText("SGK işveren payı (%)")).toHaveValue("21,75");
    expect(within(dialog).getByLabelText("Damga vergisi (binde)")).toHaveValue("7,59");
    expect(within(dialog).getByText(/etkin işveren oranı %18,75/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole("textbox", { name: "SGK işveren teşviki" }));
    await user.click(await screen.findByRole("option", { name: /2 puan/ }));
    expect(within(dialog).getByText(/etkin işveren oranı %21,75/)).toBeInTheDocument();
    await user.clear(wage);
    await user.type(wage, "abc");
    expect(
      within(dialog).getByText("Geçerli bir tutar girin (en çok 2 ondalık)."),
    ).toBeInTheDocument();
    const save = within(dialog).getByRole("button", {
      name: "Mali müşavirle kontrol ettim, kaydet",
    });
    expect(save).toBeDisabled();
    await user.clear(wage);
    await user.type(wage, "33.030");
    await user.click(save);
    await waitFor(() => expect(payrollApi.saveParameterSet).toHaveBeenCalled());
    const [id, payload] = vi.mocked(payrollApi.saveParameterSet).mock.calls[0];
    expect(id).toBeNull();
    expect(payload).toMatchObject({
      valid_from: "2026-01",
      minimum_wage: "33030",
      employer_sgk_rate: "21.75",
      incentive_points: "2",
      stamp_tax_per_mille: "7.59",
      tax_bracket_1: "190000",
      tax_rate_5: "40",
      source: "RG 26.12.2025",
    });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("kayıtlı set düzenlenir: form setle dolu gelir, değişiklik aynı sete gider", async () => {
    const user = userEvent.setup();
    vi.mocked(payrollApi.getPayrollMonth).mockResolvedValue(savedMonth());
    vi.mocked(payrollApi.listParameterSets).mockResolvedValue([savedSet()]);
    vi.mocked(payrollApi.saveParameterSet).mockResolvedValue(
      savedSet({ incentive_points: "2.00" }),
    );
    renderApp("/personel/bordro?ay=2026-10");
    expect(await screen.findByText("Parametreler kayıtlı · 01.2026")).toBeInTheDocument();
    expect(screen.queryByText(/kayıtlı parametre seti yok/)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Parametreler" }));
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText(/Son değişiklik: Yönetim/)).toBeInTheDocument();
    expect(within(dialog).getByLabelText("Asgari ücret (aylık brüt, TL)")).toHaveValue("33030");
    expect(within(dialog).getByLabelText("Kaynak")).toHaveValue("RG");
    await user.click(within(dialog).getByRole("textbox", { name: "SGK işveren teşviki" }));
    await user.click(await screen.findByRole("option", { name: /2 puan/ }));
    await user.click(
      within(dialog).getByRole("button", { name: "Mali müşavirle kontrol ettim, kaydet" }),
    );
    await waitFor(() =>
      expect(payrollApi.saveParameterSet).toHaveBeenCalledWith(
        4,
        expect.objectContaining({ valid_from: "2026-01", incentive_points: "2", source: "RG" }),
      ),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("kayıtlı set gerekçeyle kaldırılır", async () => {
    const user = userEvent.setup();
    vi.mocked(payrollApi.getPayrollMonth).mockResolvedValue(savedMonth());
    vi.mocked(payrollApi.listParameterSets).mockResolvedValue([savedSet()]);
    vi.mocked(payrollApi.removeParameterSet).mockResolvedValue(savedSet({ is_active: false }));
    renderApp("/personel/bordro?ay=2026-10");
    await user.click(await screen.findByRole("button", { name: "Parametreler" }));
    const dialog = await screen.findByRole("dialog");
    await within(dialog).findByText(/Son değişiklik: Yönetim/);
    await user.click(within(dialog).getByRole("button", { name: "Seti kaldır" }));
    const remove = within(dialog).getByRole("button", { name: "Seti kaldır" });
    expect(remove).toBeDisabled();
    expect(within(dialog).getByText(/Başka yılın kayıtlı seti kullanılmaz/)).toBeInTheDocument();
    await user.type(within(dialog).getByLabelText(/Kaldırma nedeni/), "Yanlış açıldı");
    await user.click(remove);
    await waitFor(() =>
      expect(payrollApi.removeParameterSet).toHaveBeenCalledWith(4, "Yanlış açıldı"),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("yasal değeri olmayan yılda pencere kırmızı uyarıyla açılır, düğme en yakın yılı söyler", async () => {
    const user = userEvent.setup();
    vi.mocked(payrollApi.getPayrollMonth).mockResolvedValue(
      month({
        year: 2027,
        month: 1,
        period_label: "Ocak 2027",
        parameters: {
          origin: "fallback",
          year: 2026,
          record: null,
          valid_from: null,
          values: VALUES,
        },
      }),
    );
    vi.mocked(payrollApi.getParameterDefaults).mockImplementation(async (year) => ({
      year,
      known: year === 2026,
      values_year: 2026,
      legal_source: year === 2026 ? "RG 26.12.2025" : "",
      values: VALUES,
    }));
    renderApp("/personel/bordro?ay=2027-01");
    expect(await screen.findByText("Parametreler yok (tahmin)")).toBeInTheDocument();
    expect(
      screen.getByText(/2027 yılı için bordro parametreleri yok; 2026 değerleriyle tahmin edildi/),
    ).toBeInTheDocument();
    expect(screen.queryByText("Parametreler kaydedilmedi")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Parametreleri gir" }));
    const dialog = await screen.findByRole("dialog");
    expect(
      await within(dialog).findByText(/2027 yılının yasal değerleri sistemde yok; 2026 değerleri/),
    ).toBeInTheDocument();
    expect(
      await within(dialog).findByRole("button", {
        name: "En yakın yılın (2026) değerleriyle doldur",
      }),
    ).toBeInTheDocument();
    expect(
      within(dialog).queryByRole("button", { name: "2027 yasal değerleriyle doldur" }),
    ).not.toBeInTheDocument();
    // Uyarı kırmızıdır (bilinen yılın uyarısı sarı).
    const notice = within(dialog).getByText(
      /2027 yılının yasal değerleri sistemde yok; 2026 değerleri/,
    );
    expect(notice.closest(".mantine-Alert-root")?.getAttribute("style") ?? "").toContain(
      "--mantine-color-red-light",
    );
  });

  it("oranlar Türkçe ondalıkla okunur; fazla ondalık ve sunucu hataları alanın altında görünür", async () => {
    const user = userEvent.setup();
    vi.mocked(payrollApi.saveParameterSet).mockRejectedValue(
      httpError(400, {
        code: "validation_error",
        detail: "Gönderilen bilgiler geçersiz.",
        errors: { stamp_tax_per_mille: ["Damga vergisi oranı geçersiz."] },
      }),
    );
    renderApp("/personel/bordro?ay=2026-10");
    await user.click(await screen.findByRole("button", { name: "Parametreler" }));
    const dialog = await screen.findByRole("dialog");
    const stamp = await within(dialog).findByLabelText("Damga vergisi (binde)");
    // Noktalı oran ondalıktır (binlik sayılmaz): 7.590 = binde 7,59.
    await user.clear(stamp);
    await user.type(stamp, "7.590");
    const employer = within(dialog).getByLabelText("SGK işveren payı (%)");
    await user.clear(employer);
    await user.type(employer, "21,750");
    expect(within(dialog).getByText(/0 ile 100 arasında, en çok 2 ondalık/)).toBeInTheDocument();
    const save = within(dialog).getByRole("button", {
      name: "Mali müşavirle kontrol ettim, kaydet",
    });
    expect(save).toBeDisabled();
    await user.clear(employer);
    await user.type(employer, "21,75");
    await user.click(save);
    expect(await within(dialog).findByText("Damga vergisi oranı geçersiz.")).toBeInTheDocument();
    expect(stamp).toHaveAccessibleDescription(/Damga vergisi oranı geçersiz/);
    expect(within(dialog).queryByText("Gönderilen bilgiler geçersiz.")).not.toBeInTheDocument();
    expect(vi.mocked(payrollApi.saveParameterSet).mock.calls[0][1]).toMatchObject({
      stamp_tax_per_mille: "7.590",
      employer_sgk_rate: "21.75",
    });
    // Alan değişince sunucunun hatası kalkar; genel "geçersiz" uyarısı da çıkmaz.
    await user.type(stamp, "0");
    expect(within(dialog).queryByText("Damga vergisi oranı geçersiz.")).not.toBeInTheDocument();
    expect(within(dialog).queryByText("Gönderilen bilgiler geçersiz.")).not.toBeInTheDocument();
  });

  it("kayıt sürerken pencere kapanmaz; yanıt gelince kapanır", async () => {
    const user = userEvent.setup();
    let finish: (set: ParameterSet) => void = () => {};
    vi.mocked(payrollApi.saveParameterSet).mockReturnValue(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    renderApp("/personel/bordro?ay=2026-10");
    await user.click(await screen.findByRole("button", { name: "Parametreler" }));
    const dialog = await screen.findByRole("dialog");
    await within(dialog).findByLabelText("Asgari ücret (aylık brüt, TL)");
    await user.click(
      within(dialog).getByRole("button", { name: "Mali müşavirle kontrol ettim, kaydet" }),
    );
    await waitFor(() => expect(payrollApi.saveParameterSet).toHaveBeenCalled());
    await user.keyboard("{Escape}");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(document.querySelector(".mantine-Modal-close")).toBeNull();
    expect(within(dialog).getByRole("textbox", { name: "Set" })).toBeDisabled();
    finish(savedSet());
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });
});
