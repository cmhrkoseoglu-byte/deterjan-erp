import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as authApi from "../../api/auth";
import * as costingApi from "../../api/costing";
import type { LotCostDetail, LotCostHistory, StockValue } from "../../api/costing";
import * as inventoryApi from "../../api/inventory";
import type { GoodsReceiptDetail } from "../../api/inventory";
import * as masterdataApi from "../../api/masterdata";
import * as workflowApi from "../../api/workflow";
import { page, userWith } from "../../test/fixtures";
import { renderApp } from "../../test/render";

vi.mock("../../api/auth");
vi.mock("../../api/costing", async (importOriginal) => ({
  ...(await importOriginal<typeof costingApi>()),
  listLotCosts: vi.fn(),
  getLotCostHistory: vi.fn(),
  recalculateLotCost: vi.fn(),
  listRates: vi.fn(),
  createRate: vi.fn(),
  listStandardCosts: vi.fn(),
  saveStandardCost: vi.fn(),
  setStandardCostActive: vi.fn(),
  getReport: vi.fn(),
}));
vi.mock("../../api/inventory", async (importOriginal) => ({
  ...(await importOriginal<typeof inventoryApi>()),
  getGoodsReceipt: vi.fn(),
  setReceiptCosts: vi.fn(),
}));
vi.mock("../../api/masterdata", async (importOriginal) => ({
  ...(await importOriginal<typeof masterdataApi>()),
  listRecords: vi.fn(),
}));
vi.mock("../../api/workflow");

function bulkCost(extra: Partial<LotCostDetail> = {}): LotCostDetail {
  return {
    id: 11,
    lot: 30,
    lot_no: "B-261016-001",
    lot_source: "PRODUCTION",
    material: 60,
    material_code: "BULASIK",
    material_name: "Bulaşık deterjanı",
    material_type: "BULK",
    unit: "KG",
    version: 1,
    is_current: true,
    method: "PRODUCTION",
    quantity: "980.0000",
    total_cost: "41903.94",
    unit_cost: "42.7591",
    finished_scrap_cost: "0.00",
    is_estimated: false,
    has_missing: false,
    cost_date: "2026-10-16",
    calculated_at: "2026-10-16T12:00:00+03:00",
    calculated_by_name: "Üretim",
    note: "",
    lines: [
      {
        line_no: 1,
        category: "MATERIAL",
        description: "LAS %96",
        material: 50,
        material_code: "LAS",
        source_lot: 7,
        source_lot_no: "H-261016-001",
        quantity: "600.0000",
        unit: "KG",
        unit_cost: "46.0618",
        amount: "27637.08",
        is_estimated: false,
        is_missing: false,
      },
      {
        line_no: 2,
        category: "ENERGY",
        description: "Enerji (kg çıktı)",
        material: null,
        material_code: null,
        source_lot: null,
        source_lot_no: null,
        quantity: "980.0000",
        unit: null,
        unit_cost: "0.5000",
        amount: "490.00",
        is_estimated: false,
        is_missing: false,
      },
    ],
    ...extra,
  };
}

function history(versions: LotCostDetail[]): LotCostHistory {
  return {
    lot: 30,
    lot_no: "B-261016-001",
    material_code: "BULASIK",
    material_name: "Bulaşık deterjanı",
    is_costable: true,
    versions,
  };
}

beforeEach(() => {
  vi.mocked(authApi.fetchCsrf).mockResolvedValue();
  vi.mocked(workflowApi.fetchTasks).mockResolvedValue(page([]));
  vi.mocked(workflowApi.fetchNotifications).mockResolvedValue(page([]));
  vi.mocked(workflowApi.fetchUnreadCount).mockResolvedValue(0);
  vi.mocked(masterdataApi.listRecords).mockResolvedValue(page([]));
  vi.mocked(costingApi.listLotCosts).mockResolvedValue(page([bulkCost()]));
  vi.mocked(costingApi.getLotCostHistory).mockResolvedValue(history([bulkCost()]));
  vi.mocked(costingApi.listRates).mockResolvedValue(page([]));
  vi.mocked(costingApi.listStandardCosts).mockResolvedValue(page([]));
});

describe("maliyet", () => {
  it("yönetim lot maliyetlerini görür ve kalem kalem dökümü açar", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("yonetim"));
    const { router } = renderApp("/maliyet");
    const row = (await screen.findByText("B-261016-001")).closest("tr")!;
    expect(within(row).getByText("41.903,94")).toBeInTheDocument();
    expect(within(row).getByText("42,7591")).toBeInTheDocument();
    await user.click(row);
    await waitFor(() => expect(router.state.location.pathname).toBe("/maliyet/lotlar/30"));
    expect(await screen.findByText("27.637,08")).toBeInTheDocument();
    expect(screen.getByText("Enerji")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "H-261016-001" })).toHaveAttribute(
      "href",
      "/maliyet/lotlar/7",
    );
  });

  it("yeniden hesaplama not ister ve bağlı lot seçeneğini gönderir", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("yonetim"));
    vi.mocked(costingApi.recalculateLotCost).mockResolvedValue(
      history([bulkCost({ id: 12, version: 2, note: "Fiyat" }), bulkCost({ is_current: false })]),
    );
    renderApp("/maliyet/lotlar/30");
    await user.click(await screen.findByRole("button", { name: "Yeniden hesapla" }));
    const dialog = await screen.findByRole("dialog");
    const submit = within(dialog).getByRole("button", { name: "Yeniden hesapla" });
    expect(submit).toBeDisabled();
    await user.type(within(dialog).getByLabelText(/Sürüm notu/), "Fiyat");
    await user.click(within(dialog).getByLabelText(/üretilen lotları da/));
    await user.click(submit);
    await waitFor(() =>
      expect(costingApi.recalculateLotCost).toHaveBeenCalledWith(30, "Fiyat", true),
    );
    expect(await screen.findByText("Sürüm 2")).toBeInTheDocument();
    expect(screen.getByText("Sürümler")).toBeInTheDocument();
  });

  it("gider oranı eklenir", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("yonetim"));
    vi.mocked(costingApi.createRate).mockResolvedValue({
      id: 1,
      stage: "PRODUCTION",
      kind: "ENERGY",
      rate_per_kg: "0.5000",
      valid_from: "2026-10-01",
      note: "",
      created_at: "",
      created_by_name: null,
    });
    renderApp("/maliyet/oranlar");
    await user.click(await screen.findByRole("button", { name: "Oran ekle" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText(/Oran \(TL\/kg\)/), "0,5");
    await user.click(within(dialog).getByRole("button", { name: "Kaydet" }));
    await waitFor(() =>
      expect(costingApi.createRate).toHaveBeenCalledWith(
        expect.objectContaining({ stage: "PRODUCTION", kind: "ENERGY", rate_per_kg: "0.5" }),
      ),
    );
  });

  it("stok değeri raporu toplamı ve Excel bağlantısını gösterir", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("yonetim"));
    const value: StockValue = {
      total_value: "64486.52",
      by_type: [{ material_type: "RAW", value: "64486.52" }],
      rows: [
        {
          material_id: 50,
          material_code: "LAS",
          material_name: "LAS %96",
          material_type: "RAW",
          unit: "KG",
          quantity: "1400.0000",
          value: "64486.52",
          average_unit_cost: "46.0618",
          uncosted_quantity: "0",
          estimated_quantity: "0",
        },
      ],
    };
    vi.mocked(costingApi.getReport).mockResolvedValue(value);
    renderApp("/maliyet/raporlar");
    expect(await screen.findAllByText("64.486,52 TL")).toHaveLength(2);
    expect(screen.getByText("LAS — LAS %96")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Excel" })).toHaveAttribute(
      "href",
      "/api/v1/costing/reports/stock-value/xlsx/",
    );
  });

  it("yönetim dışındaki rol maliyet sayfasını açamaz", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("satin_alma"));
    vi.mocked(costingApi.listLotCosts).mockClear();
    renderApp("/maliyet");
    expect(await screen.findByText("Yetkiniz yok")).toBeInTheDocument();
    expect(costingApi.listLotCosts).not.toHaveBeenCalled();
  });
});

function receipt(extra: Partial<GoodsReceiptDetail> = {}): GoodsReceiptDetail {
  return {
    id: 4,
    number: "MK-2026-00001",
    status: "POSTED",
    status_display: "Kaydedildi",
    cancel_reason: "",
    cancelled_at: null,
    posted_at: "2026-10-15T11:00:00+03:00",
    posted_by_name: "Depo",
    created_at: "2026-10-15T10:00:00+03:00",
    created_by_name: "Depo",
    note: "",
    line_count: 1,
    supplier: 3,
    supplier_code: "T-01",
    supplier_name: "Kimya A.Ş.",
    receipt_date: "2026-10-15",
    delivery_note_no: "IRS-9",
    quarantine_location: 2,
    quarantine_location_code: "KAR-01",
    storage_location: null,
    storage_location_code: null,
    extra_costs: [],
    lines: [
      {
        id: 1,
        line_no: 1,
        material: 50,
        material_code: "LAS",
        material_name: "LAS %96",
        quantity: "1000.0000",
        unit: 1,
        unit_code: "KG",
        supplier_lot_no: "",
        manufactured_at: null,
        expiry_date: null,
        unit_price: "1.5000",
        currency: "USD",
        exchange_rate: "30.0000",
        created_lot: 7,
        created_lot_no: "H-261015-001",
        created_lot_status: "RELEASED",
      },
    ],
    ...extra,
  };
}

describe("mal kabulde fiyat ve ek masraf", () => {
  it("satın alma kaydedilmiş mal kabule notla ek masraf girer", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("satin_alma"));
    vi.mocked(inventoryApi.getGoodsReceipt).mockResolvedValue(receipt());
    vi.mocked(inventoryApi.setReceiptCosts).mockResolvedValue(receipt());
    renderApp("/depo/mal-kabul/4");
    expect(await screen.findByText("Fiyat ve ek masraf")).toBeInTheDocument();
    expect(screen.getByLabelText("Birim fiyat LAS")).toHaveValue("1.5");
    expect(screen.getByLabelText("Kur (TL) LAS")).toHaveValue("30");
    await user.click(screen.getByRole("button", { name: "Ek masraf ekle" }));
    const extra = screen.getByTestId("extra-cost");
    await user.type(within(extra).getByLabelText("Tutar (TL)"), "1.300,50");
    const save = screen.getByRole("button", { name: "Fiyatları kaydet" });
    expect(save).toBeDisabled();
    await user.type(screen.getByLabelText(/Düzeltme notu/), "Nakliye faturası");
    await user.click(save);
    await waitFor(() =>
      expect(inventoryApi.setReceiptCosts).toHaveBeenCalledWith(4, {
        lines: [{ id: 1, unit_price: "1.5", currency: "USD", exchange_rate: "30" }],
        extra_costs: [
          { kind: "FREIGHT", description: "", amount: "1300.50", allocation: "QUANTITY" },
        ],
        note: "Nakliye faturası",
      }),
    );
  });

  it("depo fiyat bölümünü ve fiyat kutusunu görmez", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("depo"));
    const doc = receipt({ status: "DRAFT", status_display: "Taslak", extra_costs: null });
    doc.lines = doc.lines.map((line) => {
      const copy = { ...line };
      delete copy.unit_price;
      delete copy.currency;
      delete copy.exchange_rate;
      return copy;
    });
    vi.mocked(inventoryApi.getGoodsReceipt).mockResolvedValue(doc);
    renderApp("/depo/mal-kabul/4");
    expect(await screen.findByRole("button", { name: "Taslağı kaydet" })).toBeInTheDocument();
    expect(screen.queryByText("Fiyat ve ek masraf")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Birim fiyat")).not.toBeInTheDocument();
  });
});
