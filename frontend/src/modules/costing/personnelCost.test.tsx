import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as authApi from "../../api/auth";
import * as costingApi from "../../api/costing";
import type {
  CostEmployee,
  PersonnelCostReport,
  PersonnelCostRow,
  StageCost,
} from "../../api/costing";
import * as workflowApi from "../../api/workflow";
import { page, userWith } from "../../test/fixtures";
import { renderApp } from "../../test/render";
import { monthLabel, nextMonthStart, parseMoney, shiftMonth } from "./personnelCostFormat";

vi.mock("../../api/auth");
vi.mock("../../api/workflow");
vi.mock("../../api/costing", async (importOriginal) => ({
  // Sabitler (personnelCostKeys, Excel adresleri) gerçek kalır.
  ...(await importOriginal<typeof costingApi>()),
  getPersonnelCost: vi.fn(),
  addLaborRateFromPersonnelCost: vi.fn(),
  listCostCenters: vi.fn(),
  setCostCenter: vi.fn(),
  getPersonnelCostSettings: vi.fn(),
  updatePersonnelCostSettings: vi.fn(),
}));

const AYSE: CostEmployee = {
  id: 1,
  employee_no: "P-001",
  full_name: "Ayşe Demir",
  department: "Üretim",
  hire_date: "2020-01-01",
  termination_date: null,
  is_active: true,
};
const CAN: CostEmployee = {
  ...AYSE,
  id: 2,
  employee_no: "P-002",
  full_name: "Can Kaya",
  hire_date: "2026-03-01",
};
const ECE: CostEmployee = {
  ...AYSE,
  id: 3,
  employee_no: "P-003",
  full_name: "Ece Ak",
  department: "Dolum",
  termination_date: "2026-10-15",
  is_active: false,
};

function costRow(employee: CostEmployee, extra: Partial<PersonnelCostRow>): PersonnelCostRow {
  return {
    employee,
    stage: "PRODUCTION",
    gross_monthly: "45000.00",
    employed_days: 30,
    unpaid_days: 0,
    paid_days: 30,
    overtime_hours: "0.00",
    gross_salary: "45000.00",
    overtime_pay: "0.00",
    gross_total: "45000.00",
    employer_share: "7987.50",
    total_cost: "52987.50",
    missing_wage: false,
    ...extra,
  };
}

function stage(extra: Partial<StageCost>): StageCost {
  return {
    stage: "PRODUCTION",
    cost: "52987.50",
    employee_count: 1,
    kg: "980.0000",
    unconverted: 0,
    current_rate: "1.2000",
    suggested_rate: "54.0689",
    missing_wage_count: 0,
    ...extra,
  };
}

function report(extra: Partial<PersonnelCostReport> = {}): PersonnelCostReport {
  return {
    year: 2026,
    month: 9,
    period_label: "Eylül 2026",
    attendance_status: "APPROVED",
    attendance_number: "PT-2026-00009",
    attendance_approved: true,
    employer_rate: "17.75",
    missing_wage_count: 1,
    gross_salary: "69166.67",
    overtime_pay: "2000.00",
    employer_share: "12632.08",
    total_cost: "83798.75",
    stages: [
      stage({}),
      stage({
        stage: "FILLING",
        cost: "30811.25",
        kg: "780.0000",
        unconverted: 2,
        current_rate: null,
        suggested_rate: "39.5016",
        missing_wage_count: 1,
      }),
      stage({
        stage: "",
        cost: "0.00",
        employee_count: 0,
        kg: null,
        current_rate: null,
        suggested_rate: null,
      }),
    ],
    rows: [
      costRow(AYSE, {}),
      costRow(CAN, {
        stage: "FILLING",
        gross_monthly: "25000.00",
        unpaid_days: 1,
        paid_days: 29,
        overtime_hours: "12.25",
        gross_salary: "24166.67",
        overtime_pay: "2000.00",
        gross_total: "26166.67",
        employer_share: "4644.58",
        total_cost: "30811.25",
        missing_wage: true,
      }),
    ],
    ...extra,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(authApi.fetchCsrf).mockResolvedValue();
  vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("yonetim"));
  vi.mocked(workflowApi.fetchTasks).mockResolvedValue(page([]));
  vi.mocked(workflowApi.fetchNotifications).mockResolvedValue(page([]));
  vi.mocked(workflowApi.fetchUnreadCount).mockResolvedValue(0);
  vi.mocked(costingApi.getPersonnelCost).mockResolvedValue(report());
  vi.mocked(costingApi.listCostCenters).mockResolvedValue([
    { department: "Dolum", stage: "" },
    { department: "Üretim", stage: "PRODUCTION" },
  ]);
  vi.mocked(costingApi.getPersonnelCostSettings).mockResolvedValue({
    employer_rate: "17.75",
    updated_at: "",
  });
});

describe("personel maliyeti", () => {
  it("ayın özetini, aşamaları ve kişileri gösterir; ay değiştirilir", async () => {
    const user = userEvent.setup();
    renderApp("/maliyet/personel?ay=2026-09");
    expect(await screen.findByText("83.798,75 TL")).toBeInTheDocument();
    expect(costingApi.getPersonnelCost).toHaveBeenCalledWith(2026, 9);
    expect(screen.getByText("Eylül 2026")).toBeInTheDocument();
    expect(screen.getByText("Puantaj onaylı · PT-2026-00009")).toBeInTheDocument();
    expect(screen.getByText("İşveren payı (%17,75)")).toBeInTheDocument();
    expect(screen.getByText("54,0689")).toBeInTheDocument();
    expect(screen.getByLabelText(/2 malzemede yoğunluk girilmediği/)).toBeInTheDocument();
    const can = screen.getByText("Can Kaya").closest("tr")!;
    expect(within(can).getByText("Ücret eksik")).toBeInTheDocument();
    expect(within(can).getByText("30.811,25")).toBeInTheDocument();
    // Fazla mesai saati yuvarlanmaz (çeyrek saat).
    expect(within(can).getByText("12,25")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Ücretleri aç" })).toHaveAttribute(
      "href",
      "/personel/ucretler",
    );
    expect(screen.getByRole("link", { name: "Excel" })).toHaveAttribute(
      "href",
      "/api/v1/costing/personnel-costs/2026/9/xlsx/",
    );
    await user.click(screen.getByRole("button", { name: "Önceki ay" }));
    await waitFor(() => expect(costingApi.getPersonnelCost).toHaveBeenCalledWith(2026, 8));
    expect(screen.getByText("Ağustos 2026")).toBeInTheDocument();
  });

  it("onaylı ayın gerçekleşen işçiliği oran olarak eklenir ve pencere kapanır", async () => {
    const user = userEvent.setup();
    vi.mocked(costingApi.addLaborRateFromPersonnelCost).mockResolvedValue({
      id: 9,
      stage: "PRODUCTION",
      kind: "LABOR",
      rate_per_kg: "54.0689",
      valid_from: "2026-10-01",
      note: "",
      created_at: "",
      created_by_name: null,
    });
    renderApp("/maliyet/personel?ay=2026-09");
    await user.click(
      await screen.findByRole("button", { name: "Oran olarak ekle: Üretim (bulk)" }),
    );
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/980 kg/)).toBeInTheDocument();
    expect(within(dialog).queryByText(/ücreti eksik/)).not.toBeInTheDocument();
    expect(within(dialog).getByLabelText(/Geçerlilik başlangıcı/)).toHaveValue("2026-10-01");
    await user.click(within(dialog).getByRole("button", { name: "Oran olarak ekle" }));
    await waitFor(() =>
      expect(costingApi.addLaborRateFromPersonnelCost).toHaveBeenCalledWith(2026, 9, {
        stage: "PRODUCTION",
        valid_from: "2026-10-01",
      }),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    // Rapor yeniden okunur (geçerli oran değişti).
    await waitFor(() => expect(costingApi.getPersonnelCost).toHaveBeenCalledTimes(2));
  });

  it("eksik ücret ve kg'a çevrilemeyen üretim oran penceresinde uyarılır", async () => {
    const user = userEvent.setup();
    renderApp("/maliyet/personel?ay=2026-09");
    await user.click(
      await screen.findByRole("button", { name: "Oran olarak ekle: Dolum (mamul)" }),
    );
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/Bu aşamada 1 kişinin ücreti eksik/)).toBeInTheDocument();
    expect(within(dialog).getByText(/2 malzemenin üretimi kg'a çevrilemedi/)).toBeInTheDocument();
  });

  it("puantaj onaylanmadan oran eklenemez", async () => {
    vi.mocked(costingApi.getPersonnelCost).mockResolvedValue(
      report({ attendance_status: "OPEN", attendance_number: "", attendance_approved: false }),
    );
    renderApp("/maliyet/personel?ay=2026-09");
    expect(await screen.findByText(/Ayın puantajı onaylanmadı/)).toBeInTheDocument();
    expect(screen.getByText("Puantaj açık (taslak)")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Oran olarak ekle: Üretim (bulk)" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Oran olarak ekle: Dolum (mamul)" })).toBeDisabled();
  });

  it("üretimi kg'a çevrilemeyen aşamada neden söylenir", async () => {
    const user = userEvent.setup();
    const base = report();
    vi.mocked(costingApi.getPersonnelCost).mockResolvedValue({
      ...base,
      stages: [
        base.stages[0],
        { ...base.stages[1], kg: "0.0000", unconverted: 1, suggested_rate: null },
        base.stages[2],
      ],
    });
    renderApp("/maliyet/personel?ay=2026-09");
    const button = await screen.findByRole("button", { name: "Oran olarak ekle: Dolum (mamul)" });
    expect(button).toBeDisabled();
    // Neden dokunmatik ekranda da görünsün diye yazıyla durur; farede ipucu da açılır.
    const row = button.closest("tr")!;
    expect(within(row).getByText(/Üretim kg'a çevrilemedi/)).toBeInTheDocument();
    await user.hover(button.parentElement!);
    await waitFor(() => expect(screen.getAllByText(/Üretim kg'a çevrilemedi/)).toHaveLength(2));
  });

  it("ücreti eksik ayrılan kişi için ücretler ayrılanlarla açılır", async () => {
    vi.mocked(costingApi.getPersonnelCost).mockResolvedValue(
      report({
        rows: [
          costRow(ECE, {
            stage: "FILLING",
            gross_monthly: null,
            gross_salary: "0.00",
            employer_share: "0.00",
            total_cost: "0.00",
            missing_wage: true,
          }),
        ],
      }),
    );
    renderApp("/maliyet/personel?ay=2026-10");
    const row = (await screen.findByText("Ece Ak")).closest("tr")!;
    expect(within(row).getByText("Çıkış · 15.10.2026")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Ücretleri aç" })).toHaveAttribute(
      "href",
      "/personel/ucretler?ayrilanlar=1",
    );
  });

  it("birim eşleştirmesi (genel gider dahil) ve işveren payı kaydedilir", async () => {
    const user = userEvent.setup();
    vi.mocked(costingApi.setCostCenter).mockImplementation(async (center) => center);
    vi.mocked(costingApi.updatePersonnelCostSettings).mockResolvedValue({
      employer_rate: "20.50",
      updated_at: "",
    });
    // Ücretler Personel'e taşındı; ayarlar personel maliyeti sekmesinin altında.
    renderApp("/maliyet/personel?ay=2026-09");
    // Sayfa yüklendikten sonra: eski "Personel ücretleri" sekmesi yok.
    await screen.findByRole("tab", { name: "Personel maliyeti", selected: true });
    expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual([
      "Lot maliyetleri",
      "Raporlar",
      "Gider oranları",
      "Standart maliyetler",
      "Personel maliyeti",
    ]);
    await user.click(await screen.findByRole("textbox", { name: "Aşama: Dolum" }));
    await user.click(await screen.findByRole("option", { name: "Dolum (mamul)" }));
    await waitFor(() =>
      expect(costingApi.setCostCenter).toHaveBeenCalledWith({
        department: "Dolum",
        stage: "FILLING",
      }),
    );
    await user.click(screen.getByRole("textbox", { name: "Aşama: Üretim" }));
    await user.click(await screen.findByRole("option", { name: "Genel gider" }));
    await waitFor(() =>
      expect(costingApi.setCostCenter).toHaveBeenCalledWith({ department: "Üretim", stage: "" }),
    );
    const rate = await screen.findByLabelText("Oran (%)");
    await waitFor(() => expect(rate).toHaveValue("17,75"));
    const save = screen.getByRole("button", { name: "Kaydet" });
    expect(save).toBeDisabled();
    await user.clear(rate);
    await user.type(rate, "20,5");
    await user.click(save);
    await waitFor(() =>
      expect(costingApi.updatePersonnelCostSettings).toHaveBeenCalledWith("20.5"),
    );
  });

  it.each(["/maliyet/ucretler", "/maliyet/personel"])(
    "yönetim dışındaki rol %s sayfasını açamaz",
    async (path) => {
      vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("dolum"));
      renderApp(path);
      expect(await screen.findByText("Yetkiniz yok")).toBeInTheDocument();
      expect(costingApi.getPersonnelCost).not.toHaveBeenCalled();
      expect(costingApi.listCostCenters).not.toHaveBeenCalled();
    },
  );
});

describe("personel maliyeti biçimleri", () => {
  it("tutar girişi binlik ayracı ve ondalığı tanır", () => {
    expect(parseMoney("30.000")).toBe("30000");
    expect(parseMoney("30.000,50")).toBe("30000.50");
    expect(parseMoney("30000,5")).toBe("30000.5");
    expect(parseMoney("1.250.000")).toBe("1250000");
    expect(parseMoney(" 30 000 ")).toBe("30000");
    expect(parseMoney("1234.567")).toBeNull();
    expect(parseMoney("30,000")).toBeNull();
    expect(parseMoney("-30000")).toBeNull();
    expect(parseMoney("0")).toBeNull();
    expect(parseMoney("abc")).toBeNull();
  });

  it("ay kaydırma yıl sınırını geçer", () => {
    expect(shiftMonth(2026, 1, -1)).toBe("2025-12");
    expect(shiftMonth(2026, 12, 1)).toBe("2027-01");
    expect(nextMonthStart(2026, 12)).toBe("2027-01-01");
    expect(monthLabel(2026, 9)).toBe("Eylül 2026");
  });
});
