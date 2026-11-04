import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as authApi from "../../api/auth";
import * as costingApi from "../../api/costing";
import * as wagesApi from "../../api/wages";
import type { EmployeeWage, WageEmployee, WageSummaryRow } from "../../api/wages";
import * as workflowApi from "../../api/workflow";
import { page, userWith } from "../../test/fixtures";
import { renderApp } from "../../test/render";

vi.mock("../../api/auth");
vi.mock("../../api/workflow");
vi.mock("../../api/costing", async (importOriginal) => ({
  // Sabitler (personnelCostKeys) gerçek kalır.
  ...(await importOriginal<typeof costingApi>()),
  getPersonnelCost: vi.fn(),
}));
vi.mock("../../api/wages", async (importOriginal) => ({
  // Sorgu anahtarları gerçek kalır.
  ...(await importOriginal<typeof wagesApi>()),
  getWageSummary: vi.fn(),
  addWage: vi.fn(),
  removeWage: vi.fn(),
}));

const AYSE: WageEmployee = {
  id: 1,
  employee_no: "P-001",
  full_name: "Ayşe Demir",
  department: "Üretim",
  hire_date: "2020-01-01",
  termination_date: null,
  is_active: true,
};
const CAN: WageEmployee = {
  ...AYSE,
  id: 2,
  employee_no: "P-002",
  full_name: "Can Kaya",
  hire_date: "2026-03-01",
};
const ECE: WageEmployee = {
  ...AYSE,
  id: 3,
  employee_no: "P-003",
  full_name: "Ece Ak",
  department: "Dolum",
  termination_date: "2026-10-15",
  is_active: false,
};

function wage(extra: Partial<EmployeeWage> = {}): EmployeeWage {
  return {
    id: 5,
    employee: 1,
    employee_name: "Ayşe Demir",
    gross_monthly: "45000.00",
    valid_from: "2026-01-01",
    note: "",
    is_active: true,
    removal_reason: "",
    created_at: "2026-01-02T10:00:00+03:00",
    created_by_name: "Yönetim",
    ...extra,
  };
}

function summary(includeFormer = false): WageSummaryRow[] {
  const rows: WageSummaryRow[] = [
    {
      employee: AYSE,
      current_wage: "45000.00",
      current_valid_from: "2026-01-01",
      history: [wage()],
    },
    { employee: CAN, current_wage: null, current_valid_from: null, history: [] },
  ];
  if (includeFormer)
    rows.push({ employee: ECE, current_wage: null, current_valid_from: null, history: [] });
  return rows;
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(authApi.fetchCsrf).mockResolvedValue();
  vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("yonetim"));
  vi.mocked(workflowApi.fetchTasks).mockResolvedValue(page([]));
  vi.mocked(workflowApi.fetchNotifications).mockResolvedValue(page([]));
  vi.mocked(workflowApi.fetchUnreadCount).mockResolvedValue(0);
  vi.mocked(wagesApi.getWageSummary).mockImplementation(async (former) => summary(former));
});

describe("personel ücretleri", () => {
  it("Personel sekmelerinde açılır; ücret binlik ayraçla girilir, geçersiz tutar kaydedilmez", async () => {
    const user = userEvent.setup();
    vi.mocked(wagesApi.addWage).mockResolvedValue(wage({ id: 6, gross_monthly: "48500.00" }));
    renderApp("/personel/ucretler");
    const ayse = (await screen.findByText("Ayşe Demir")).closest("tr")!;
    expect(screen.getByRole("tab", { name: "Ücretler" })).toHaveAttribute("aria-selected", "true");
    expect(within(ayse).getByText("45.000,00")).toBeInTheDocument();
    expect(wagesApi.getWageSummary).toHaveBeenCalledWith(false);
    const can = screen.getByText("Can Kaya").closest("tr")!;
    expect(within(can).getByText("Girilmedi")).toBeInTheDocument();
    expect(within(can).getByRole("button", { name: "Geçmiş (0): Can Kaya" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Ücret ekle: Ayşe Demir" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/Güncel ücret 45.000,00 TL/)).toBeInTheDocument();
    const amount = within(dialog).getByLabelText(/Brüt aylık/);
    await user.type(amount, "48.500,123");
    expect(within(dialog).getByText(/Geçerli bir tutar girin/)).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Kaydet" })).toBeDisabled();
    await user.clear(amount);
    await user.type(amount, "48.500");
    expect(within(dialog).getByText("48.500,00 TL olarak kaydedilir.")).toBeInTheDocument();
    fireEvent.change(within(dialog).getByLabelText(/Geçerlilik başlangıcı/), {
      target: { value: "2026-11-01" },
    });
    await user.type(within(dialog).getByLabelText("Not"), "Zam");
    await user.click(within(dialog).getByRole("button", { name: "Kaydet" }));
    await waitFor(() =>
      expect(wagesApi.addWage).toHaveBeenCalledWith({
        employee: 1,
        gross_monthly: "48500",
        valid_from: "2026-11-01",
        note: "Zam",
      }),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    // Liste yeniden okunur.
    await waitFor(() => expect(wagesApi.getWageSummary).toHaveBeenCalledTimes(2));
  });

  it("ilk ücretin başlangıcı işe giriş tarihidir", async () => {
    const user = userEvent.setup();
    renderApp("/personel/ucretler");
    await user.click(await screen.findByRole("button", { name: "Ücret ekle: Can Kaya" }));
    const dialog = await screen.findByRole("dialog");
    expect(
      within(dialog).getByText(/İlk ücret: başlangıç varsayılan olarak işe giriş/),
    ).toBeInTheDocument();
    expect(within(dialog).getByLabelText(/Geçerlilik başlangıcı/)).toHaveValue("2026-03-01");
  });

  it("liste değişince açık ücret penceresi kapanır ve kendiliğinden açılmaz", async () => {
    const user = userEvent.setup();
    const { router } = renderApp("/personel/ucretler");
    await screen.findByText("Ayşe Demir");
    await user.click(screen.getByLabelText("Ayrılanları da göster"));
    await user.click(await screen.findByRole("button", { name: "Ücret ekle: Ece Ak" }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    await act(() => router.navigate(-1));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await user.click(screen.getByLabelText("Ayrılanları da göster"));
    expect(await screen.findByText("Ece Ak")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("ayrılanlar anahtarıyla eski personel listelenir", async () => {
    const user = userEvent.setup();
    renderApp("/personel/ucretler");
    await screen.findByText("Ayşe Demir");
    expect(screen.queryByText("Ece Ak")).not.toBeInTheDocument();
    await user.click(screen.getByLabelText("Ayrılanları da göster"));
    const ece = (await screen.findByText("Ece Ak")).closest("tr")!;
    expect(wagesApi.getWageSummary).toHaveBeenCalledWith(true);
    expect(within(ece).getByText("Çıkış · 15.10.2026")).toBeInTheDocument();
    expect(within(ece).getByRole("button", { name: "Ücret ekle: Ece Ak" })).toBeEnabled();
  });

  it("ücret kaydı gerekçeyle kaldırılır", async () => {
    const user = userEvent.setup();
    vi.mocked(wagesApi.removeWage).mockResolvedValue(wage({ is_active: false }));
    renderApp("/personel/ucretler");
    await user.click(await screen.findByRole("button", { name: "Geçmiş (1): Ayşe Demir" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/Yönetim/)).toBeInTheDocument();
    await user.click(
      within(dialog).getByRole("button", { name: "Kaldır: 01.01.2026 · 45.000,00 TL" }),
    );
    const submit = within(dialog).getByRole("button", { name: "Kaldır" });
    expect(submit).toBeDisabled();
    await user.type(within(dialog).getByLabelText(/Kaldırma nedeni/), "Yanlış tutar");
    await user.click(submit);
    await waitFor(() => expect(wagesApi.removeWage).toHaveBeenCalledWith(5, "Yanlış tutar"));
    await waitFor(() =>
      expect(within(dialog).queryByLabelText(/Kaldırma nedeni/)).not.toBeInTheDocument(),
    );
  });

  it("eski Maliyet adresi ayrılanlar süzgeciyle yeni sekmeye yönlenir", async () => {
    const { router } = renderApp("/maliyet/ucretler?ayrilanlar=1");
    expect(await screen.findByText("Ece Ak")).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/personel/ucretler");
    expect(router.state.location.search).toBe("?ayrilanlar=1");
    expect(wagesApi.getWageSummary).toHaveBeenCalledWith(true);
  });

  it("yönetim dışındaki rol ücretleri açamaz", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("dolum"));
    renderApp("/personel/ucretler");
    expect(await screen.findByText("Yetkiniz yok")).toBeInTheDocument();
    expect(wagesApi.getWageSummary).not.toHaveBeenCalled();
  });
});
