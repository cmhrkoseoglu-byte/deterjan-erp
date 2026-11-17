import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as attachmentsApi from "../../api/attachments";
import * as authApi from "../../api/auth";
import * as inventoryApi from "../../api/inventory";
import type { GoodsReceiptDetail, LotDetail, StockAdjustmentDetail } from "../../api/inventory";
import * as labelsApi from "../../api/labels";
import * as mdApi from "../../api/masterdata";
import * as qualityApi from "../../api/quality";
import type { Sample } from "../../api/quality";
import * as workflowApi from "../../api/workflow";
import { page, userWith, withoutAccess } from "../../test/fixtures";
import { renderApp } from "../../test/render";

// Kişiye özel yetkiyle depo ekranları (plan §5.9, §8 madde 2): varsayılan paketlerdeki davranış
// inventory.test.tsx'tedir; burada yalnız rol paketinden ayrılan kişiler denenir.

vi.mock("../../api/auth");
vi.mock("../../api/attachments", async (importOriginal) => ({
  ...(await importOriginal<typeof attachmentsApi>()),
  listAttachments: vi.fn(),
}));
vi.mock("../../api/labels", async (importOriginal) => ({
  ...(await importOriginal<typeof labelsApi>()),
  listPrinters: vi.fn(),
  getLabelSettings: vi.fn(),
  listPallets: vi.fn(),
}));
vi.mock("../../api/inventory", async (importOriginal) => ({
  ...(await importOriginal<typeof inventoryApi>()),
  listLots: vi.fn(),
  listBalances: vi.fn(),
  listGoodsReceipts: vi.fn(),
  listAdjustments: vi.fn(),
  listMovements: vi.fn(),
  getLot: vi.fn(),
  getLotTrace: vi.fn(),
  getGoodsReceipt: vi.fn(),
  getAdjustment: vi.fn(),
  saveAdjustment: vi.fn(),
  postAdjustment: vi.fn(),
}));
vi.mock("../../api/masterdata", async (importOriginal) => ({
  ...(await importOriginal<typeof mdApi>()),
  listRecords: vi.fn(),
}));
vi.mock("../../api/workflow");
vi.mock("../../api/quality", async (importOriginal) => ({
  ...(await importOriginal<typeof qualityApi>()),
  listSamples: vi.fn(),
}));

function adjustment(overrides: Partial<StockAdjustmentDetail> = {}): StockAdjustmentDetail {
  return {
    id: 9,
    number: "SD-2026-00001",
    status: "DRAFT",
    status_display: "Taslak",
    cancel_reason: "",
    cancelled_at: null,
    posted_at: null,
    posted_by_name: null,
    created_at: "2026-10-15T10:00:00+03:00",
    created_by_name: "Depo",
    note: "",
    line_count: 1,
    adjustment_date: "2026-10-15",
    lines: [
      {
        id: 1,
        line_no: 1,
        lot: 7,
        lot_no: "H-261015-001",
        material_code: "LABSA",
        material_name: "LABSA",
        unit: "KG",
        location: 5,
        location_code: "HM-01",
        system_quantity: "1000.0000",
        counted_quantity: "990.0000",
        difference: "-10.0000",
        reason: "Sayım farkı",
      },
    ],
    ...overrides,
  };
}

function receipt(): GoodsReceiptDetail {
  return {
    id: 4,
    number: "MK-2026-00001",
    status: "POSTED",
    status_display: "Kaydedildi",
    cancel_reason: "",
    cancelled_at: null,
    extra_costs: [],
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
    lines: [
      {
        id: 1,
        line_no: 1,
        material: 50,
        material_code: "LABSA",
        material_name: "LABSA",
        quantity: "1000.0000",
        unit: 1,
        unit_code: "KG",
        supplier_lot_no: "TL-55",
        manufactured_at: null,
        expiry_date: "2027-10-15",
        unit_price: "12.5000",
        currency: "TRY",
        exchange_rate: null,
        created_lot: 7,
        created_lot_no: "H-261015-001",
        created_lot_status: "QUARANTINE",
      },
    ],
  } as GoodsReceiptDetail;
}

function lot(): LotDetail {
  return {
    id: 7,
    lot_no: "H-261015-001",
    material: 50,
    material_code: "LABSA",
    material_name: "LABSA",
    material_type: "RAW",
    material_gtin: "",
    material_case_gtin: "",
    unit: "KG",
    status: "QUARANTINE",
    status_display: "Karantina",
    source: "PURCHASE",
    source_display: "Satın alma",
    supplier: 3,
    supplier_name: "Kimya A.Ş.",
    supplier_lot_no: "TL-55",
    manufactured_at: null,
    expiry_date: "2027-10-15",
    is_expired: false,
    released_by_name: null,
    released_at: null,
    status_note: "",
    total_quantity: "1000.0000",
    allowed_transitions: ["RELEASED", "REJECTED", "BLOCKED"],
    created_at: "2026-10-15T10:00:00+03:00",
    balances: [],
    receipt: { model: "inventory.goodsreceipt", id: 4, number: "MK-2026-00001" },
  };
}

const sample = {
  id: 31,
  number: "NM-2026-00001",
  status: "IN_TEST",
  status_display: "Testte",
  lot: 7,
  lot_no: "H-261015-001",
  stage: "INCOMING",
  stage_display: "Giriş kontrolü",
  specification: 2,
  specification_label: "v1",
  taken_at: "2026-10-15T10:00:00+03:00",
  decided_at: null,
} as Sample;

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(attachmentsApi.listAttachments).mockResolvedValue([]);
  vi.mocked(labelsApi.listPrinters).mockResolvedValue([]);
  vi.mocked(labelsApi.listPallets).mockResolvedValue([]);
  vi.mocked(labelsApi.getLabelSettings).mockResolvedValue({
    company_name: "",
    gs1_company_prefix: "",
    sscc_extension_digit: 0,
    next_sscc_serial: 1,
    default_printer: null,
    default_printer_code: null,
    sscc_enabled: false,
    updated_at: "2026-10-15T09:00:00+03:00",
  });
  vi.mocked(authApi.fetchCsrf).mockResolvedValue();
  vi.mocked(workflowApi.fetchTasks).mockResolvedValue(page([]));
  vi.mocked(workflowApi.fetchNotifications).mockResolvedValue(page([]));
  vi.mocked(workflowApi.fetchUnreadCount).mockResolvedValue(0);
  vi.mocked(workflowApi.fetchComments).mockResolvedValue([]);
  vi.mocked(workflowApi.fetchRecordHistory).mockResolvedValue([]);
  vi.mocked(mdApi.listRecords).mockResolvedValue(page([]));
  vi.mocked(inventoryApi.listLots).mockResolvedValue(page([]));
  vi.mocked(inventoryApi.listBalances).mockResolvedValue(page([]));
  vi.mocked(inventoryApi.listGoodsReceipts).mockResolvedValue(page([]));
  vi.mocked(inventoryApi.listAdjustments).mockResolvedValue(page([]));
  vi.mocked(inventoryApi.listMovements).mockResolvedValue(page([]));
  vi.mocked(qualityApi.listSamples).mockResolvedValue(page([]));
});

describe("kişiye özel yetkiyle depo", () => {
  it("sayım düzeltmeyi onaylayan ama değiştiremeyen kişi taslağı yeniden kaydetmeden stoka alır", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(
      withoutAccess(userWith("depo"), { "inventory.adjustments": "c" }),
    );
    vi.mocked(inventoryApi.getAdjustment).mockResolvedValue(adjustment());
    vi.mocked(inventoryApi.postAdjustment).mockResolvedValue(
      adjustment({ status: "POSTED", status_display: "Kaydedildi" }),
    );
    renderApp("/depo/sayim/9");

    await user.click(await screen.findByRole("button", { name: "Kaydet ve stoka al" }));
    expect(screen.queryByRole("button", { name: "Taslağı kaydet" })).not.toBeInTheDocument();
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Kaydet ve stoka al" }));
    await waitFor(() => expect(inventoryApi.postAdjustment).toHaveBeenCalledWith(9));
    expect(inventoryApi.saveAdjustment).not.toHaveBeenCalled();
  });

  it("fiyatları görüp mal kabul fiyatlarını değiştiremeyen kişide fiyat paneli salt okunurdur", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(
      withoutAccess(userWith("satin_alma"), { "inventory.receipt_prices": "c" }),
    );
    vi.mocked(inventoryApi.getGoodsReceipt).mockResolvedValue(receipt());
    renderApp("/depo/mal-kabul/4");

    expect(await screen.findByText("Fiyat ve ek masraf")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Birim fiyat LABSA" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Fiyatları kaydet" })).not.toBeInTheDocument();
  });

  it("hiçbir depo sekmesini göremeyen kişiye depo sayfası kapalıdır", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue({ ...userWith(), access: {} });
    renderApp("/depo");
    expect(await screen.findByRole("heading", { name: "Yetkiniz yok" })).toBeInTheDocument();
  });

  it("lot sayfasındaki numune numarası, numune sayfasını açamayana düz metindir (§8 madde 2)", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("depo"));
    vi.mocked(inventoryApi.getLot).mockResolvedValue(lot());
    vi.mocked(inventoryApi.getLotTrace).mockResolvedValue({
      id: 7,
      lot_no: "H-261015-001",
      status: "QUARANTINE",
      status_display: "Karantina",
      lot_source: "PURCHASE",
      lot_source_display: "Satın alma",
      material_id: 50,
      material_code: "LABSA",
      material_name: "LABSA",
      material_type: "RAW",
      unit: "KG",
      expiry_date: null,
      quantity: null,
      quantity_unit: null,
      children: [],
    });
    vi.mocked(qualityApi.listSamples).mockResolvedValue(page([sample]));
    renderApp("/depo/lotlar/7");

    const samples = await screen.findByTestId("lot-samples");
    expect(within(samples).getByText("NM-2026-00001")).toBeInTheDocument();
    expect(within(samples).queryByRole("link")).not.toBeInTheDocument();
    // Mal kabul kaydını herkes okur: bağlantı kalır.
    expect(screen.getByRole("link", { name: "MK-2026-00001" })).toHaveAttribute(
      "href",
      "/depo/mal-kabul/4",
    );
  });

  it("mal kabul okuması kaldırılan kişide lot sayfasındaki mal kabul numarası düz metindir", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(
      withoutAccess(userWith("uretim"), {
        "inventory.receipts": "r",
        "inventory.open_records": "r",
      }),
    );
    vi.mocked(inventoryApi.getLot).mockResolvedValue(lot());
    vi.mocked(inventoryApi.getLotTrace).mockResolvedValue({
      id: 7,
      lot_no: "H-261015-001",
      status: "QUARANTINE",
      status_display: "Karantina",
      lot_source: "PURCHASE",
      lot_source_display: "Satın alma",
      material_id: 50,
      material_code: "LABSA",
      material_name: "LABSA",
      material_type: "RAW",
      unit: "KG",
      expiry_date: null,
      quantity: null,
      quantity_unit: null,
      children: [],
    });
    renderApp("/depo/lotlar/7");

    expect(await screen.findByText("MK-2026-00001")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "MK-2026-00001" })).not.toBeInTheDocument();
  });
});
