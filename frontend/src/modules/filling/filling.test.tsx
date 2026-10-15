import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as authApi from "../../api/auth";
import * as fillingApi from "../../api/filling";
import type {
  ConsumptionReport,
  FillingOrderDetail,
  FillingRequirementRow,
  FillingRunDetail,
} from "../../api/filling";
import * as mdApi from "../../api/masterdata";
import * as workflowApi from "../../api/workflow";
import { httpError, page, userWith } from "../../test/fixtures";
import { renderApp } from "../../test/render";
import { recordPath } from "../../workflow/recordLinks";

vi.mock("../../api/auth");
vi.mock("../../api/filling", async (importOriginal) => ({
  ...(await importOriginal<typeof fillingApi>()),
  listFillingOrders: vi.fn(),
  listRuns: vi.fn(),
  listSpecs: vi.fn(),
  getFillingOrder: vi.fn(),
  getRun: vi.fn(),
  fillingOrderAction: vi.fn(),
  pickPackaging: vi.fn(),
  packagingSuggestions: vi.fn(),
  orderReport: vi.fn(),
  runReport: vi.fn(),
  scanPackaging: vi.fn(),
  recordScrap: vi.fn(),
  finishRun: vi.fn(),
  consumeBulk: vi.fn(),
}));
vi.mock("../../api/masterdata", async (importOriginal) => ({
  ...(await importOriginal<typeof mdApi>()),
  listRecords: vi.fn(),
}));
vi.mock("../../api/workflow");

function requirement(overrides: Partial<FillingRequirementRow> = {}): FillingRequirementRow {
  return {
    id: 31,
    sequence: 1,
    material: 70,
    material_code: "SISE-750",
    material_name: "Şişe 750 ml",
    unit: "ADET",
    quantity_per_unit: "1.000000",
    scrap_allowance_pct: "2.00",
    required_quantity: "1020.0000",
    net_quantity: "1000.0000",
    picked_quantity: "0.0000",
    to_pick: "1020.0000",
    is_ready: false,
    ...overrides,
  };
}

function order(overrides: Partial<FillingOrderDetail> = {}): FillingOrderDetail {
  return {
    id: 5,
    number: "DO-2026-00001",
    status: "APPROVED",
    status_display: "Onaylandı",
    finished_product: 90,
    finished_product_code: "BULASIK-LIMON-750",
    finished_product_name: "Bulaşık deterjanı limonlu 750 ml",
    unit: "ADET",
    packaging_spec: 3,
    packaging_spec_version: 1,
    bulk_product: 80,
    bulk_product_code: "BULASIK-LIMON",
    fill_quantity: "750.0000",
    fill_unit_code: "ML",
    planned_units: 1000,
    filling_line: 7,
    filling_line_code: "DH-01",
    filling_line_name: "Dolum hattı 1",
    line_location_code: "DOLUM-1",
    output_location: 9,
    output_location_code: "MAMUL-DEPO",
    planned_date: "2026-10-21",
    notes: "",
    created_by_name: "Planlama",
    created_at: "2026-10-15T10:00:00+03:00",
    units_per_case: 12,
    requirements: [
      requirement(),
      requirement({
        id: 32,
        sequence: 2,
        material: 71,
        material_code: "KOLI-12",
        material_name: "Koli 12'li",
        quantity_per_unit: "0.083333",
        scrap_allowance_pct: "1.00",
        required_quantity: "85.0000",
        net_quantity: "84.0000",
        picked_quantity: "85.0000",
        to_pick: "0.0000",
        is_ready: true,
      }),
    ],
    picks: [],
    runs: [],
    allowed_transitions: ["MATERIAL_PREP", "CANCELLED"],
    approved_by_name: "Planlama",
    approved_at: "2026-10-15T10:05:00+03:00",
    completed_at: null,
    cancel_reason: "",
    ...overrides,
  };
}

function run(overrides: Partial<FillingRunDetail> = {}): FillingRunDetail {
  return {
    id: 41,
    sequence: 1,
    order: 5,
    order_number: "DO-2026-00001",
    order_status: "IN_PROGRESS",
    finished_product_code: "BULASIK-LIMON-750",
    finished_product_name: "Bulaşık deterjanı limonlu 750 ml",
    status: "IN_PROGRESS",
    status_display: "Dolumda",
    output_lot: 95,
    output_lot_no: "D-261015-001",
    output_lot_status: "QUARANTINE",
    output_lot_status_display: "Karantina",
    operator_name: "Dolumcu",
    started_at: "2026-10-15T11:00:00+03:00",
    finished_at: null,
    finished_by_name: null,
    good_units: null,
    theoretical_bulk: null,
    actual_bulk: null,
    bulk_variance_pct: null,
    finish_note: "",
    cancel_reason: "",
    bulk_product: 80,
    bulk_product_code: "BULASIK-LIMON",
    bulk_unit: "KG",
    fill_quantity: "750.0000",
    fill_unit_code: "ML",
    planned_units: 1000,
    line_location_code: "DOLUM-1",
    consumptions: [],
    scraps: [],
    scanned_lots: [],
    packaging: [],
    bulk_lots: [
      {
        material: 80,
        material_code: "BULASIK-LIMON",
        unit: "KG",
        lot: 60,
        lot_no: "B-261015-001",
        expiry_date: null,
        location: 4,
        location_code: "TANK-1",
        quantity: "1000.0000",
      },
    ],
    line_stock: [],
    allowed_transitions: ["COMPLETED", "CANCELLED"],
    ...overrides,
  };
}

const report: ConsumptionReport = {
  good_units: 1000,
  scrapped_units: 5,
  bulk_product_code: "BULASIK-LIMON",
  bulk_unit: "KG",
  threshold_pct: "1.50",
  bulk_over_threshold: true,
  bulk: {
    theoretical: "780.0000",
    consumed: "790.0000",
    scrap: "3.0000",
    actual: "793.0000",
    variance: "13.0000",
    variance_pct: "1.67",
  },
  packaging: [],
  runs: [],
};

beforeEach(() => {
  report.runs = [run({ status: "COMPLETED" })];
  vi.resetAllMocks();
  vi.mocked(authApi.fetchCsrf).mockResolvedValue();
  vi.mocked(workflowApi.fetchTasks).mockResolvedValue(page([]));
  vi.mocked(workflowApi.fetchNotifications).mockResolvedValue(page([]));
  vi.mocked(workflowApi.fetchUnreadCount).mockResolvedValue(0);
  vi.mocked(workflowApi.fetchComments).mockResolvedValue([]);
  vi.mocked(workflowApi.fetchRecordHistory).mockResolvedValue([]);
  vi.mocked(mdApi.listRecords).mockResolvedValue(page([]));
  vi.mocked(fillingApi.listFillingOrders).mockResolvedValue(page([order()]));
  vi.mocked(fillingApi.listRuns).mockResolvedValue(page([]));
  vi.mocked(fillingApi.listSpecs).mockResolvedValue(page([]));
  vi.mocked(fillingApi.getFillingOrder).mockResolvedValue(order());
  vi.mocked(fillingApi.getRun).mockResolvedValue(run());
  vi.mocked(fillingApi.packagingSuggestions).mockResolvedValue([]);
  vi.mocked(fillingApi.orderReport).mockResolvedValue(report);
  vi.mocked(fillingApi.runReport).mockResolvedValue(report);
});

describe("dolum sekmeleri", () => {
  it("depo ambalaj hazırlama sekmesine düşer", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("depo"));
    renderApp("/dolum");
    expect(await screen.findByRole("tab", { name: "Ambalaj hazırlama", selected: true }));
    expect(await screen.findByTestId("prep-orders")).toHaveTextContent("DO-2026-00001");
    expect(fillingApi.listFillingOrders).toHaveBeenCalledWith(expect.anything(), [
      "APPROVED",
      "MATERIAL_PREP",
    ]);
  });

  it("dolum rolü hat sekmesine düşer, hazırlamayı ve yeni emir düğmesini görmez", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("dolum"));
    renderApp("/dolum");
    expect(await screen.findByRole("tab", { name: "Dolum hattı", selected: true }));
    const names = screen.getAllByRole("tab").map((tab) => tab.textContent);
    expect(names).toEqual(["Dolum emirleri", "Dolum hattı", "Ambalaj reçeteleri"]);
    expect(screen.queryByRole("button", { name: "Yeni dolum emri" })).toBeNull();
  });

  it("laboratuvar dolum sayfasına giremez", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("laboratuvar"));
    renderApp("/dolum");
    expect(await screen.findByText(/yetkiniz yok/i));
  });

  it("görevdeki dolum kayıtları detay sayfasına gider", () => {
    expect(recordPath({ model: "filling.fillingorder", id: 5, repr: "" })).toBe("/dolum/emirler/5");
    expect(recordPath({ model: "filling.fillingrun", id: 41, repr: "" })).toBe(
      "/dolum/partiler/41",
    );
  });
});

describe("dolum emri", () => {
  it("ihtiyaç fire payı dahil ve hariç gösterilir; planlama onaylanmış emri iptal edebilir", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("planlama"));
    renderApp("/dolum/emirler/5");
    const table = await screen.findByTestId("requirements");
    const row = within(table).getByText("SISE-750 - Şişe 750 ml").closest("tr")!;
    expect(row).toHaveTextContent("1.020 ADET");
    expect(row).toHaveTextContent("1.000 ADET");
    expect(screen.getByRole("button", { name: "Emri iptal et" }));
    expect(screen.queryByRole("button", { name: "Ambalaj hazırla" })).toBeNull();
  });

  it("biten partiyle rapor ve bulk farkı uyarısı görünür", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("dolum"));
    vi.mocked(fillingApi.getFillingOrder).mockResolvedValue(
      order({
        status: "IN_PROGRESS",
        runs: [{ ...run(), status: "COMPLETED", good_units: 1000, bulk_variance_pct: "1.67" }],
      }),
    );
    renderApp("/dolum/emirler/5");
    expect(await screen.findByTestId("consumption-report")).toHaveTextContent("793");
    expect(screen.getByText(/eşiğini aşıyor/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Dolumu bitir" }));
  });
});

describe("ambalaj hazırlama", () => {
  it("okutulan lotu hazırlar, yanlış malzemenin hatasını gösterir", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("depo"));
    vi.mocked(fillingApi.pickPackaging).mockRejectedValueOnce(
      httpError(400, { code: "lot_material_mismatch", detail: "Lot başka malzemenin." }),
    );
    renderApp("/dolum/emirler/5/hazirlama");
    const scan = await screen.findByRole("textbox", { name: "Lot okut" });
    await user.type(scan, "H-261015-009{Enter}");
    expect(await screen.findByTestId("pick-error")).toHaveTextContent("Lot başka malzemenin.");
    expect(fillingApi.pickPackaging).toHaveBeenCalledWith(5, {
      requirement: 31,
      lot_no: "H-261015-009",
      quantity: "1020",
    });
    expect(screen.getByRole("button", { name: "Ambalaj hazır" })).toBeDisabled();
  });
});

describe("dolum hattı tableti", () => {
  it("bulk lotu listeden seçip tüketir", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("dolum"));
    vi.mocked(fillingApi.consumeBulk).mockResolvedValue(run());
    renderApp("/dolum/partiler/41");
    await user.click(
      await within(await screen.findByTestId("bulk-lots")).findByText("B-261015-001"),
    );
    await user.type(screen.getByRole("textbox", { name: "Miktar (KG)" }), "500,5");
    await user.click(screen.getByRole("button", { name: "Tüketimi kaydet" }));
    await waitFor(() =>
      expect(fillingApi.consumeBulk).toHaveBeenCalledWith(41, { lot: 60, quantity: "500.5" }),
    );
  });

  it("mamul firesi hızlı düğmeyle kaydedilir; diğer nedeni açıklama ister", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("dolum"));
    vi.mocked(fillingApi.recordScrap).mockResolvedValue(run());
    renderApp("/dolum/partiler/41");
    const reasons = await screen.findByTestId("scrap-reasons");
    await user.click(within(reasons).getByRole("button", { name: "Sızıntı" }));
    await user.type(screen.getByRole("textbox", { name: "Miktar (ADET)" }), "4");
    await user.click(screen.getByRole("button", { name: "Fireyi kaydet" }));
    await waitFor(() =>
      expect(fillingApi.recordScrap).toHaveBeenCalledWith(41, {
        kind: "FINISHED",
        reason_code: "LEAK",
        quantity: "4",
        note: "",
      }),
    );
    await user.click(within(reasons).getByRole("button", { name: "Diğer" }));
    await user.type(screen.getByRole("textbox", { name: "Miktar (ADET)" }), "1");
    expect(screen.getByRole("button", { name: "Fireyi kaydet" })).toBeDisabled();
  });

  it("yanlış ambalaj lotu okutulunca hata gösterir", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("dolum"));
    vi.mocked(fillingApi.scanPackaging).mockRejectedValue(
      httpError(400, { code: "lot_material_mismatch", detail: "Bu lot reçetede yok." }),
    );
    renderApp("/dolum/partiler/41");
    const inputs = await screen.findAllByRole("textbox", { name: "Lot okut" });
    await user.type(inputs[1], "H-999{Enter}");
    expect(await screen.findByTestId("scan-error")).toHaveTextContent("Bu lot reçetede yok.");
  });

  it("biten partide düzenleme alanları yok, rapor var", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("dolum"));
    vi.mocked(fillingApi.getRun).mockResolvedValue(
      run({ status: "COMPLETED", good_units: 1000, allowed_transitions: [] }),
    );
    renderApp("/dolum/partiler/41");
    expect(await screen.findByTestId("consumption-report"));
    expect(screen.queryByRole("button", { name: "Partiyi bitir" })).toBeNull();
  });
});
