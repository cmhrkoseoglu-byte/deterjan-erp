import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as authApi from "../../api/auth";
import * as mdApi from "../../api/masterdata";
import * as productionApi from "../../api/production";
import type {
  BatchLine,
  ProductionBatchDetail,
  ProductionOrderDetail,
  RequirementRow,
} from "../../api/production";
import * as workflowApi from "../../api/workflow";
import { httpError, page, userWith } from "../../test/fixtures";
import { renderApp } from "../../test/render";
import { recordPath } from "../../workflow/recordLinks";
import { deviationPct, gaugeValue, lineState, remaining } from "./calc";

vi.mock("../../api/auth");
vi.mock("../../api/production", async (importOriginal) => ({
  ...(await importOriginal<typeof productionApi>()),
  listOrders: vi.fn(),
  listBatches: vi.fn(),
  getOrder: vi.fn(),
  getBatch: vi.fn(),
  orderAction: vi.fn(),
  pickMaterial: vi.fn(),
  pickSuggestions: vi.fn(),
  consume: vi.fn(),
}));
vi.mock("../../api/masterdata", async (importOriginal) => ({
  ...(await importOriginal<typeof mdApi>()),
  listRecords: vi.fn(),
}));
vi.mock("../../api/workflow");

function requirement(overrides: Partial<RequirementRow> = {}): RequirementRow {
  return {
    id: 11,
    sequence: 1,
    material: 50,
    material_code: "LAS",
    material_name: "LAS %96",
    unit: "KG",
    required_quantity: "600.0000",
    tolerance_pct: "1.00",
    is_water: false,
    instruction: "",
    picked_quantity: "0.0000",
    consumed_quantity: "0.0000",
    to_pick: "600.0000",
    is_ready: false,
    ...overrides,
  };
}

function order(overrides: Partial<ProductionOrderDetail> = {}): ProductionOrderDetail {
  return {
    id: 3,
    number: "UE-2026-00001",
    status: "APPROVED",
    status_display: "Onaylandı",
    product: 80,
    product_code: "BULASIK-LIMON",
    product_name: "Bulaşık deterjanı",
    base_unit: "KG",
    recipe_version: 9,
    recipe_id: 4,
    recipe_code: "REC-BULASIK",
    version_no: 1,
    planned_quantity: "1000.0000",
    unit: 1,
    unit_code: "KG",
    planned_base_quantity: "1000.0000",
    planned_date: "2026-10-16",
    equipment: 6,
    equipment_code: "KT-01",
    equipment_name: "Karıştırma tankı 1",
    production_location: 8,
    production_location_code: "URETIM-1",
    priority: 2,
    priority_display: "Normal",
    notes: "",
    created_by_name: "Planlama",
    created_at: "2026-10-15T10:00:00+03:00",
    requirements: [
      requirement(),
      requirement({
        id: 12,
        sequence: 2,
        material: 51,
        material_code: "SU",
        material_name: "Şebeke suyu",
        is_water: true,
        required_quantity: "400.0000",
        to_pick: "0.0000",
        is_ready: true,
      }),
    ],
    picks: [],
    batches: [],
    allowed_transitions: ["MATERIAL_PREP", "CANCELLED"],
    remaining_quantity: "1000.0000",
    suggested_batch_quantity: "1000.0000",
    approved_by_name: "Planlama",
    approved_at: "2026-10-15T10:05:00+03:00",
    completed_at: null,
    cancel_reason: "",
    ...overrides,
  };
}

function line(overrides: Partial<BatchLine> = {}): BatchLine {
  return {
    requirement: 11,
    sequence: 1,
    material: 50,
    material_code: "LAS",
    material_name: "LAS %96",
    unit: "KG",
    tolerance_pct: "1.00",
    is_water: false,
    instruction: "Yavaşça ekle.",
    planned_quantity: "600.0000",
    consumed_quantity: "0.0000",
    deviation_pct: "0.00",
    state: "pending",
    available: [
      {
        lot: 70,
        lot_no: "H-261015-001",
        expiry_date: null,
        location: 8,
        location_code: "URETIM-1",
        quantity: "600.0000",
      },
    ],
    ...overrides,
  };
}

function batch(overrides: Partial<ProductionBatchDetail> = {}): ProductionBatchDetail {
  return {
    id: 21,
    batch_no: "B-261015-001",
    sequence: 1,
    order: 3,
    order_number: "UE-2026-00001",
    order_status: "IN_PRODUCTION",
    product_code: "BULASIK-LIMON",
    product_name: "Bulaşık deterjanı",
    unit: "KG",
    equipment: 6,
    equipment_code: "KT-01",
    status: "IN_PROGRESS",
    status_display: "Devam ediyor",
    planned_quantity: "1000.0000",
    actual_output_quantity: null,
    yield_pct: null,
    output_lot: 90,
    output_lot_no: "B-261015-001",
    output_lot_status: "QUARANTINE",
    output_lot_status_display: "Karantina",
    started_at: "2026-10-15T11:00:00+03:00",
    started_by_name: "Operatör",
    finished_at: null,
    finished_by_name: null,
    finish_note: "",
    cancel_reason: "",
    lines: [line()],
    consumptions: [],
    allowed_transitions: ["COMPLETED", "CANCELLED"],
    ...overrides,
  };
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(authApi.fetchCsrf).mockResolvedValue();
  vi.mocked(workflowApi.fetchTasks).mockResolvedValue(page([]));
  vi.mocked(workflowApi.fetchNotifications).mockResolvedValue(page([]));
  vi.mocked(workflowApi.fetchUnreadCount).mockResolvedValue(0);
  vi.mocked(workflowApi.fetchComments).mockResolvedValue([]);
  vi.mocked(workflowApi.fetchRecordHistory).mockResolvedValue([]);
  vi.mocked(mdApi.listRecords).mockResolvedValue(page([]));
  vi.mocked(productionApi.listOrders).mockResolvedValue(page([order()]));
  vi.mocked(productionApi.listBatches).mockResolvedValue(page([]));
  vi.mocked(productionApi.getOrder).mockResolvedValue(order());
  vi.mocked(productionApi.getBatch).mockResolvedValue(batch());
  vi.mocked(productionApi.pickSuggestions).mockResolvedValue([]);
});

describe("tolerans hesabı", () => {
  it("sapma yüzdesi ve satır durumu backend ile aynı kuralı izler", () => {
    expect(deviationPct("600", "606")).toBe(1);
    expect(lineState("600", "0", "1")).toBe("pending");
    expect(lineState("600", "606", "1")).toBe("ok");
    expect(lineState("600", "607", "1")).toBe("over");
    expect(lineState("600", "590", "1")).toBe("under");
    expect(remaining("600", "250")).toBe(350);
    expect(remaining("600", "700")).toBe(0);
    expect(gaugeValue("600", "720")).toBe(100);
  });
});

describe("üretim sekmeleri", () => {
  it("depo hazırlama sekmesine düşer", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("depo"));
    renderApp("/uretim");
    expect(await screen.findByRole("tab", { name: "Malzeme hazırlama", selected: true }));
    expect(await screen.findByTestId("prep-orders")).toHaveTextContent("UE-2026-00001");
    expect(productionApi.listOrders).toHaveBeenCalledWith(expect.anything(), [
      "APPROVED",
      "MATERIAL_PREP",
    ]);
  });

  it("üretim rolü şarjlar sekmesine düşer, hazırlamayı ve yeni emir düğmesini görmez", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("uretim"));
    renderApp("/uretim");
    expect(await screen.findByRole("tab", { name: "Şarjlar", selected: true }));
    const names = screen.getAllByRole("tab").map((tab) => tab.textContent);
    expect(names).toEqual(["Üretim emirleri", "Şarjlar"]);
    expect(screen.queryByRole("button", { name: "Yeni üretim emri" })).toBeNull();
  });

  it("planlama yeni emir açabilir", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("planlama"));
    renderApp("/uretim");
    expect(await screen.findByRole("button", { name: "Yeni üretim emri" }));
  });

  it("satın alma üretim sayfasına giremez", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("satin_alma"));
    renderApp("/uretim");
    expect(await screen.findByText(/yetkiniz yok/i));
  });

  it("görevdeki üretim kayıtları detay sayfasına gider", () => {
    expect(recordPath({ model: "production.productionorder", id: 3, repr: "" })).toBe(
      "/uretim/emirler/3",
    );
    expect(recordPath({ model: "production.productionbatch", id: 21, repr: "" })).toBe(
      "/uretim/sarjlar/21",
    );
  });
});

describe("üretim emri", () => {
  it("su satırını hazırlanmaz olarak gösterir; depo hazırlamaya gidebilir", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("depo"));
    renderApp("/uretim/emirler/3");
    const table = await screen.findByTestId("requirements");
    expect(within(table).getByText("Şebeke suyu (hazırlanmaz)"));
    expect(screen.getByRole("button", { name: "Malzeme hazırla" }));
    expect(screen.queryByRole("button", { name: "Onayla" })).toBeNull();
  });
});

describe("malzeme hazırlama", () => {
  it("karantinadaki lot okutulunca hatayı gösterir", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("depo"));
    vi.mocked(productionApi.pickMaterial).mockRejectedValue(
      httpError(400, {
        code: "lot_not_usable",
        detail: "Lot H-261015-009 karantinada; kullanılamaz.",
      }),
    );
    renderApp("/uretim/emirler/3/hazirlama");
    const scan = await screen.findByLabelText("Lot barkodu");
    await userEvent.type(scan, "h-261015-009{Enter}");
    expect(await screen.findByTestId("pick-error")).toHaveTextContent("karantinada");
    expect(productionApi.pickMaterial).toHaveBeenCalledWith(3, {
      requirement: 11,
      lot_no: "h-261015-009",
      quantity: "600",
    });
    // Su satırı hazırlama kartlarında yok; tüm satırlar hazır olmadan "Malzeme hazır" kapalı.
    expect(screen.getByTestId("prep-lines")).not.toHaveTextContent("SU");
    expect(screen.getByRole("button", { name: "Malzeme hazır" })).toBeDisabled();
  });

  it("tüm satırlar hazırsa malzeme hazır bildirilir", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("depo"));
    const ready = order({
      status: "MATERIAL_PREP",
      requirements: [
        requirement({ picked_quantity: "600.0000", to_pick: "0.0000", is_ready: true }),
      ],
    });
    vi.mocked(productionApi.getOrder).mockResolvedValue(ready);
    vi.mocked(productionApi.orderAction).mockResolvedValue({ ...ready, status: "MATERIAL_READY" });
    renderApp("/uretim/emirler/3/hazirlama");
    await userEvent.click(await screen.findByRole("button", { name: "Malzeme hazır" }));
    await waitFor(() => expect(productionApi.orderAction).toHaveBeenCalledWith(3, "mark-ready"));
  });
});

describe("şarj tartımı", () => {
  it("tolerans dışı tartımda not ister ve notla kaydeder", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("uretim"));
    vi.mocked(productionApi.consume).mockResolvedValue(
      batch({ lines: [line({ consumed_quantity: "610.0000", state: "over" })] }),
    );
    renderApp("/uretim/sarjlar/21");
    const form = await screen.findByTestId("weigh-form");
    expect(within(form).getByText("Yavaşça ekle."));
    // Tek kullanılabilir lot önceden seçilir; kalan miktar önerilir.
    expect(within(form).getByLabelText("Lot barkodu")).toHaveValue("H-261015-001");
    const qty = within(form).getByLabelText("Tartılan miktar (KG)");
    expect(qty).toHaveValue("600");
    await userEvent.clear(qty);
    await userEvent.type(qty, "610");
    expect(within(form).getByText("Tolerans dışı (fazla)"));
    const save = within(form).getByRole("button", { name: "Tartımı kaydet" });
    expect(save).toBeDisabled();
    await userEvent.type(within(form).getByLabelText(/Sapma notu/), "Fazla döküldü");
    await userEvent.click(save);
    await waitFor(() =>
      expect(productionApi.consume).toHaveBeenCalledWith(21, {
        requirement: 11,
        lot: 70,
        quantity: "610",
        note: "Fazla döküldü",
      }),
    );
  });

  it("depo rolü şarjı görür ama tartamaz", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("depo"));
    renderApp("/uretim/sarjlar/21");
    expect(await screen.findByTestId("batch-lines"));
    expect(screen.queryByTestId("weigh-form")).toBeNull();
    expect(screen.queryByRole("button", { name: "Şarjı bitir" })).toBeNull();
  });
});
