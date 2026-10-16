import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as authApi from "../../api/auth";
import * as mdApi from "../../api/masterdata";
import * as salesApi from "../../api/sales";
import type {
  PickSuggestion,
  SalesOrderDetail,
  Shipment,
  ShipmentDetail,
  ShippedLot,
} from "../../api/sales";
import * as scanApi from "../../api/scan";
import type { ScanResult } from "../../api/scan";
import * as workflowApi from "../../api/workflow";
import { httpError, page, userWith } from "../../test/fixtures";
import { renderApp } from "../../test/render";
import { recordPath } from "../../workflow/recordLinks";

vi.mock("../../api/auth");
vi.mock("../../api/scan");
vi.mock("../../api/sales", async (importOriginal) => ({
  ...(await importOriginal<typeof salesApi>()),
  listSalesOrders: vi.fn(),
  getSalesOrder: vi.fn(),
  listShipments: vi.fn(),
  getShipment: vi.fn(),
  planShipment: vi.fn(),
  updateShipment: vi.fn(),
  pickLot: vi.fn(),
  undoPick: vi.fn(),
  loadShipment: vi.fn(),
  dispatchShipment: vi.fn(),
  cancelShipment: vi.fn(),
  shipmentSuggestions: vi.fn(),
  listShippedLots: vi.fn(),
}));
vi.mock("../../api/masterdata", async (importOriginal) => ({
  ...(await importOriginal<typeof mdApi>()),
  listRecords: vi.fn(),
  getRecord: vi.fn(),
}));
vi.mock("../../api/workflow");

function shipment(overrides: Partial<ShipmentDetail> = {}): ShipmentDetail {
  return {
    id: 70,
    number: "SV-2026-00001",
    status: "PLANNED",
    status_display: "Planlandı",
    sales_order: 7,
    order_number: "SS-2026-00001",
    customer: 3,
    customer_code: "M-ZINCIR",
    customer_name: "Zincir Market A.Ş.",
    planned_date: "2026-10-17",
    loading_location: 12,
    loading_location_code: "SEVK",
    vehicle_plate: "34 ABC 123",
    driver_name: "Ali Veli",
    driver_id_no_masked: "*******8901",
    carrier: "Kendi aracımız",
    notes: "",
    loaded_at: null,
    loaded_by_name: null,
    dispatched_at: null,
    dispatched_by_name: null,
    cancel_reason: "",
    cancelled_at: null,
    created_at: "2026-10-16T10:00:00+03:00",
    created_by_name: "Sevkiyat",
    delivery_address: "Gebze",
    min_remaining_shelf_life_days: 180,
    lines: [
      {
        id: 81,
        order_line: 11,
        line_no: 1,
        product: 90,
        product_code: "BULASIK-750",
        product_name: "Bulaşık deterjanı 750 ml",
        quantity: "720.0000",
        unit: "ADET",
        picked_quantity: "0.0000",
      },
    ],
    picks: [],
    ...overrides,
  };
}

const PICK = {
  id: 91,
  line: 81,
  line_no: 1,
  product_code: "BULASIK-750",
  lot: 60,
  lot_no: "D-261016-001",
  expiry_date: "2028-10-16",
  quantity: "720.0000",
  from_location_code: "MAMUL-DEPO",
  to_location_code: "SEVK",
  picked_by_name: "Depo",
  picked_at: "2026-10-16T11:00:00+03:00",
  deviation_reason: "",
  returned_at: null,
  is_shipped: false,
};

function suggestions(overrides: Partial<PickSuggestion> = {}): PickSuggestion[] {
  return [
    {
      line: 81,
      line_no: 1,
      product: 90,
      product_code: "BULASIK-750",
      product_name: "Bulaşık deterjanı 750 ml",
      unit: "ADET",
      quantity: "720.0000",
      picked_quantity: "0.0000",
      remaining_quantity: "720.0000",
      suggestions: [
        {
          lot: 60,
          lot_no: "D-261016-001",
          expiry_date: "2028-10-16",
          location: 9,
          location_code: "MAMUL-DEPO",
          quantity: "500.0000",
          reserved_quantity: "500.0000",
          reserved: true,
          meets_shelf_life: true,
        },
        {
          lot: 61,
          lot_no: "D-261016-002",
          expiry_date: "2028-12-01",
          location: 9,
          location_code: "MAMUL-DEPO",
          quantity: "400.0000",
          reserved_quantity: "0.0000",
          reserved: false,
          meets_shelf_life: true,
        },
        {
          lot: 62,
          lot_no: "D-260101-009",
          expiry_date: "2026-12-01",
          location: 9,
          location_code: "MAMUL-DEPO",
          quantity: "100.0000",
          reserved_quantity: "0.0000",
          reserved: false,
          meets_shelf_life: false,
        },
      ],
      ...overrides,
    },
  ];
}

function scanned(id: number, lotNo: string): ScanResult {
  return {
    kind: "lot",
    code: lotNo,
    lots: [
      {
        id,
        lot_no: lotNo,
        material: 90,
        material_code: "BULASIK-750",
        material_name: "Bulaşık deterjanı 750 ml",
        material_type: "FINISHED",
        unit: "ADET",
        status: "RELEASED",
        status_display: "Serbest",
        expiry_date: "2028-12-01",
        is_expired: false,
      },
    ],
    material: null,
    location: null,
    pallet: null,
    gs1: {},
  };
}

function order(): SalesOrderDetail {
  return {
    id: 7,
    number: "SS-2026-00001",
    status: "CONFIRMED",
    status_display: "Onaylandı",
    customer: 3,
    customer_code: "M-ZINCIR",
    customer_name: "Zincir Market A.Ş.",
    order_date: "2026-10-16",
    requested_delivery_date: "2026-10-17",
    delivery_address: "Gebze",
    customer_po_no: "",
    notes: "",
    line_count: 2,
    has_shortage: false,
    confirmed_at: "2026-10-16T09:00:00+03:00",
    confirmed_by_name: "Sevkiyat",
    closed_at: null,
    cancel_reason: "",
    cancelled_at: null,
    created_at: "2026-10-16T08:00:00+03:00",
    created_by_name: "Sevkiyat",
    min_remaining_shelf_life_days: 180,
    is_editable: false,
    totals: [],
    reservations: [],
    shipments: [],
    lines: [
      {
        id: 11,
        line_no: 1,
        product: 90,
        product_code: "BULASIK-750",
        product_name: "Bulaşık deterjanı 750 ml",
        quantity: "1.0000",
        unit: 7,
        unit_code: "PALET",
        base_quantity: "720.0000",
        base_unit_code: "ADET",
        reserved_quantity: "720.0000",
        shipped_quantity: "0.0000",
        shortage_quantity: "0.0000",
        planned_quantity: "0.0000",
        plannable_quantity: "720.0000",
      },
      {
        id: 12,
        line_no: 2,
        product: 91,
        product_code: "CAM-500",
        product_name: "Cam temizleyici 500 ml",
        quantity: "24.0000",
        unit: 1,
        unit_code: "ADET",
        base_quantity: "24.0000",
        base_unit_code: "ADET",
        reserved_quantity: "24.0000",
        shipped_quantity: "24.0000",
        shortage_quantity: "0.0000",
        planned_quantity: "0.0000",
        plannable_quantity: "0.0000",
      },
    ],
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
  vi.mocked(salesApi.listSalesOrders).mockResolvedValue(page([]));
  vi.mocked(salesApi.getSalesOrder).mockResolvedValue(order());
  vi.mocked(salesApi.listShipments).mockResolvedValue(page([shipment() as Shipment]));
  vi.mocked(salesApi.getShipment).mockResolvedValue(shipment());
  vi.mocked(salesApi.shipmentSuggestions).mockResolvedValue(suggestions());
  vi.mocked(salesApi.listShippedLots).mockResolvedValue(page([]));
});

describe("sevkiyat planlama", () => {
  it("siparişten kalan miktarla sevkiyat planlanır ve sevkiyat sayfasına gidilir", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("sevkiyat"));
    vi.mocked(salesApi.planShipment).mockResolvedValue(shipment());
    const { router } = renderApp("/sevkiyat/siparisler/7");

    await user.click(await screen.findByRole("button", { name: "Sevkiyat planla" }));
    const dialog = await screen.findByRole("dialog");
    // Yalnızca planlanabilir satır gelir; miktarı kalan kadardır.
    const lines = within(dialog).getByTestId("plan-lines");
    expect(lines).toHaveTextContent("BULASIK-750");
    expect(lines).not.toHaveTextContent("CAM-500");
    const qty = within(dialog).getByRole("textbox", { name: "Bu sevkiyatta 1" });
    expect(qty).toHaveValue("720");
    await user.clear(qty);
    await user.type(qty, "480");
    await user.type(within(dialog).getByRole("textbox", { name: "Plaka" }), "34 ABC 123");
    await user.type(within(dialog).getByRole("textbox", { name: "Şoför" }), "Ali Veli");
    await user.type(
      within(dialog).getByRole("textbox", { name: "Şoför TC kimlik no" }),
      "12345678901",
    );
    await user.click(within(dialog).getByRole("button", { name: "Planla" }));

    await waitFor(() =>
      expect(salesApi.planShipment).toHaveBeenCalledWith({
        sales_order: 7,
        planned_date: "2026-10-17",
        vehicle_plate: "34 ABC 123",
        driver_name: "Ali Veli",
        driver_id_no: "12345678901",
        carrier: "",
        notes: "",
        lines: [{ order_line: 11, quantity: "480" }],
      }),
    );
    await waitFor(() => expect(router.state.location.pathname).toBe("/sevkiyat/sevkiyatlar/70"));
  });

  it("planlama siparişte sevkiyat planlayamaz", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("planlama"));
    renderApp("/sevkiyat/siparisler/7");
    await screen.findByTestId("order-lines");
    expect(screen.queryByRole("button", { name: "Sevkiyat planla" })).toBeNull();
  });

  it("sevkiyat listesi açılır, satıra tıklayınca detaya gidilir", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("sevkiyat"));
    renderApp("/sevkiyat/sevkiyatlar");
    const table = await screen.findByTestId("shipments");
    await user.click(await within(table).findByText("SV-2026-00001"));
    expect(
      await screen.findByRole("heading", { name: "Sevkiyat SV-2026-00001" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Toplama" })).toBeNull();
  });
});

describe("sevkiyat detayı", () => {
  it("şoför TC no maskeli görünür; yüklenen sevkiyatı sevkiyat onaylar, irsaliye açılır", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("sevkiyat"));
    const loaded = shipment({
      status: "LOADED",
      lines: [{ ...shipment().lines[0], picked_quantity: "720.0000" }],
      picks: [PICK],
    });
    vi.mocked(salesApi.getShipment).mockResolvedValue(loaded);
    const dispatched: ShipmentDetail = {
      ...loaded,
      status: "DISPATCHED",
      picks: [{ ...PICK, is_shipped: true }],
    };
    vi.mocked(salesApi.dispatchShipment).mockImplementation(async () => {
      vi.mocked(salesApi.getShipment).mockResolvedValue(dispatched);
      return dispatched;
    });
    renderApp("/sevkiyat/sevkiyatlar/70");

    expect(await screen.findByTestId("driver-id")).toHaveTextContent("*******8901");
    expect(screen.queryByText("12345678901")).toBeNull();
    expect(screen.getByRole("link", { name: "İrsaliye (PDF)" })).toHaveAttribute(
      "href",
      "/api/v1/sales/shipments/70/waybill.pdf",
    );
    expect(screen.queryByRole("button", { name: "Yükleme tamam" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Sevki onayla" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Sevki onayla" }));
    await waitFor(() => expect(salesApi.dispatchShipment).toHaveBeenCalledWith(70));
    const shipped = await screen.findAllByText("Sevk edildi");
    expect(shipped.length).toBeGreaterThan(0);
  });

  it("planlanan sevkiyatta irsaliye yok; araç bilgisi düzenlenir, boş TC no gönderilmez", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("sevkiyat"));
    vi.mocked(salesApi.updateShipment).mockResolvedValue(shipment({ vehicle_plate: "06 XY 99" }));
    renderApp("/sevkiyat/sevkiyatlar/70");

    await screen.findByTestId("shipment-lines");
    expect(screen.queryByRole("link", { name: "İrsaliye (PDF)" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Toplama ekranı" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Araç ve şoför" }));
    const dialog = await screen.findByRole("dialog");
    const plate = within(dialog).getByRole("textbox", { name: "Plaka" });
    await user.clear(plate);
    await user.type(plate, "06 XY 99");
    await user.click(within(dialog).getByRole("button", { name: "Kaydet" }));
    await waitFor(() =>
      expect(salesApi.updateShipment).toHaveBeenCalledWith(70, {
        planned_date: "2026-10-17",
        vehicle_plate: "06 XY 99",
        driver_name: "Ali Veli",
        carrier: "Kendi aracımız",
        notes: "",
      }),
    );
  });

  it("depo toplanan sevkiyatta okutmayı geri alır ve yüklemeyi bitirir", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("depo"));
    const picking = shipment({
      status: "PICKING",
      lines: [{ ...shipment().lines[0], picked_quantity: "500.0000" }],
      picks: [{ ...PICK, quantity: "500.0000" }],
    });
    vi.mocked(salesApi.getShipment).mockResolvedValue(picking);
    vi.mocked(salesApi.undoPick).mockResolvedValue(picking);
    vi.mocked(salesApi.loadShipment).mockResolvedValue({ ...picking, status: "LOADED" });
    renderApp("/sevkiyat/sevkiyatlar/70");

    const picks = await screen.findByTestId("shipment-picks");
    expect(screen.queryByRole("button", { name: "Sevki onayla" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Sevkiyatı iptal et" })).toBeNull();
    await user.click(within(picks).getByRole("button", { name: "Geri al" }));
    let dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Geri al" }));
    await waitFor(() => expect(salesApi.undoPick).toHaveBeenCalledWith(70, 91));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

    await user.click(screen.getByRole("button", { name: "Yükleme tamam" }));
    dialog = await screen.findByRole("dialog");
    // Satır eksik toplandı: kısmi yükleme sorulur.
    expect(dialog).toHaveTextContent("Eksikle yüklensin mi?");
    await user.click(within(dialog).getByRole("button", { name: "Yükleme tamam" }));
    await waitFor(() => expect(salesApi.loadShipment).toHaveBeenCalledWith(70));
  });

  it("yüklenen sevkiyatta okutmayı depo geri alır, sevkiyat geri alamaz", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("depo"));
    const loaded = shipment({
      status: "LOADED",
      lines: [{ ...shipment().lines[0], picked_quantity: "720.0000" }],
      picks: [PICK],
    });
    vi.mocked(salesApi.getShipment).mockResolvedValue(loaded);
    vi.mocked(salesApi.undoPick).mockResolvedValue(loaded);
    renderApp("/sevkiyat/sevkiyatlar/70");

    const picks = await screen.findByTestId("shipment-picks");
    await user.click(within(picks).getByRole("button", { name: "Geri al" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Geri al" }));
    await waitFor(() => expect(salesApi.undoPick).toHaveBeenCalledWith(70, 91));
  });

  it("sevkiyat rolü yüklenen sevkiyatta okutmayı geri alamaz", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("sevkiyat"));
    vi.mocked(salesApi.getShipment).mockResolvedValue(
      shipment({
        status: "LOADED",
        lines: [{ ...shipment().lines[0], picked_quantity: "720.0000" }],
        picks: [PICK],
      }),
    );
    renderApp("/sevkiyat/sevkiyatlar/70");

    const picks = await screen.findByTestId("shipment-picks");
    expect(within(picks).queryByRole("button", { name: "Geri al" })).toBeNull();
  });

  it("görevdeki sevkiyat kaydı detay sayfasına gider", () => {
    expect(recordPath({ model: "sales.shipment", id: 70, repr: "" })).toBe(
      "/sevkiyat/sevkiyatlar/70",
    );
  });
});

describe("toplama tableti", () => {
  it("depo sevkiyat sayfasında toplama listesine düşer", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("depo"));
    const { router } = renderApp("/sevkiyat");
    const list = await screen.findByTestId("picking-list");
    expect(salesApi.listShipments).toHaveBeenCalledWith(
      { page_size: 100, ordering: "planned_date" },
      ["PLANNED", "PICKING"],
    );
    await user.click(await within(list).findByText("SV-2026-00001"));
    await waitFor(() =>
      expect(router.state.location.pathname).toBe("/sevkiyat/sevkiyatlar/70/toplama"),
    );
    expect(await screen.findByRole("heading", { name: "Toplama: SV-2026-00001" }));
  });

  it("rezerve lot okutulur; miktar rezerve kadar gelir ve toplanır", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("depo"));
    vi.mocked(scanApi.scanCode).mockResolvedValue(scanned(60, "D-261016-001"));
    vi.mocked(salesApi.pickLot).mockResolvedValue(shipment({ status: "PICKING" }));
    renderApp("/sevkiyat/sevkiyatlar/70/toplama");

    expect(await screen.findByText("Müşteri en az 180 gün raf ömrü istiyor.")).toBeInTheDocument();
    const rows = await screen.findByTestId("pick-suggestions");
    const short = within(rows).getByText("D-260101-009").closest("tr")!;
    expect(within(short).getByText("Raf ömrü yetersiz")).toBeInTheDocument();

    await user.type(screen.getByRole("textbox", { name: "Lot okut" }), "LOT:D-261016-001{Enter}");
    const qty = screen.getByRole("textbox", { name: "Miktar (ADET)" });
    await waitFor(() => expect(qty).toHaveFocus());
    expect(qty).toHaveValue("500");
    await user.type(qty, "{Enter}");
    await waitFor(() =>
      expect(salesApi.pickLot).toHaveBeenCalledWith(70, { lot: 60, quantity: "500" }),
    );
  });

  it("rezervasyondan farklı lot gerekçe ister, gerekçeyle toplanır", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("depo"));
    vi.mocked(scanApi.scanCode).mockResolvedValue(scanned(61, "D-261016-002"));
    vi.mocked(salesApi.pickLot)
      .mockRejectedValueOnce(
        httpError(400, { code: "lot_not_reserved", detail: "Lot bu siparişe rezerve değil." }),
      )
      .mockResolvedValueOnce(shipment({ status: "PICKING" }));
    renderApp("/sevkiyat/sevkiyatlar/70/toplama");

    await user.type(
      await screen.findByRole("textbox", { name: "Lot okut" }),
      "D-261016-002{Enter}",
    );
    const qty = screen.getByRole("textbox", { name: "Miktar (ADET)" });
    await waitFor(() => expect(qty).toHaveValue("400"));
    await user.click(screen.getByRole("button", { name: "Topla" }));
    const dialog = await screen.findByRole("dialog", { name: "Rezervasyondan farklı lot" });
    const submit = within(dialog).getByRole("button", { name: "Gerekçeyle topla" });
    expect(submit).toBeDisabled();
    await user.click(within(dialog).getByText("Önde duran palet"));
    await user.click(submit);
    await waitFor(() =>
      expect(salesApi.pickLot).toHaveBeenLastCalledWith(70, {
        lot: 61,
        quantity: "400",
        reason: "Önde duran palet",
      }),
    );
  });

  it("raf ömrü yetersiz lotun hatası okutma alanında gösterilir", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("depo"));
    vi.mocked(scanApi.scanCode).mockResolvedValue(scanned(62, "D-260101-009"));
    vi.mocked(salesApi.pickLot).mockRejectedValue(
      httpError(400, { code: "shelf_life_too_short", detail: "Raf ömrü yetersiz." }),
    );
    renderApp("/sevkiyat/sevkiyatlar/70/toplama");

    await user.type(
      await screen.findByRole("textbox", { name: "Lot okut" }),
      "D-260101-009{Enter}",
    );
    await user.click(screen.getByRole("button", { name: "Topla" }));
    expect(await screen.findByTestId("scan-error")).toHaveTextContent("Raf ömrü yetersiz.");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("miktar alanında art arda Enter, istek sürerken toplamayı ikinci kez göndermez", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("depo"));
    vi.mocked(scanApi.scanCode).mockResolvedValue(scanned(60, "D-261016-001"));
    let finishPick: (saved: ShipmentDetail) => void = () => undefined;
    vi.mocked(salesApi.pickLot).mockImplementation(
      () =>
        new Promise<ShipmentDetail>((resolve) => {
          finishPick = resolve;
        }),
    );
    renderApp("/sevkiyat/sevkiyatlar/70/toplama");

    await user.type(
      await screen.findByRole("textbox", { name: "Lot okut" }),
      "D-261016-001{Enter}",
    );
    const qty = screen.getByRole("textbox", { name: "Miktar (ADET)" });
    await waitFor(() => expect(qty).toHaveValue("500"));
    // Aynı anda (yeniden çizimden önce) iki Enter: `isPending` henüz güncellenmemişken de tek istek.
    fireEvent.keyDown(qty, { key: "Enter" });
    fireEvent.keyDown(qty, { key: "Enter" });
    await waitFor(() => expect(salesApi.pickLot).toHaveBeenCalled());
    expect(salesApi.pickLot).toHaveBeenCalledTimes(1);
    await user.type(qty, "{Enter}{Enter}");
    await user.type(qty, "{Enter}");
    expect(salesApi.pickLot).toHaveBeenCalledTimes(1);

    finishPick(shipment({ status: "PICKING" }));
    await waitFor(() => expect(qty).toHaveValue(""));
    expect(salesApi.pickLot).toHaveBeenCalledTimes(1);
  });

  it("toplamadan sonra eksik kalan satır seçili kalır", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("depo"));
    const glass = (picked: string, remaining: string): PickSuggestion => ({
      line: 82,
      line_no: 2,
      product: 91,
      product_code: "CAM-500",
      product_name: "Cam temizleyici 500 ml",
      unit: "ADET",
      quantity: "24.0000",
      picked_quantity: picked,
      remaining_quantity: remaining,
      suggestions: [
        {
          lot: 70,
          lot_no: "C-261016-001",
          expiry_date: "2028-10-16",
          location: 9,
          location_code: "MAMUL-DEPO",
          quantity: "30.0000",
          reserved_quantity: "30.0000",
          reserved: true,
          meets_shelf_life: true,
        },
      ],
    });
    let picked = false;
    vi.mocked(salesApi.shipmentSuggestions).mockImplementation(async () => [
      ...suggestions(),
      picked ? glass("10.0000", "14.0000") : glass("0.0000", "24.0000"),
    ]);
    vi.mocked(salesApi.pickLot).mockImplementation(async () => {
      picked = true;
      return shipment({ status: "PICKING" });
    });
    renderApp("/sevkiyat/sevkiyatlar/70/toplama");

    const lines = await screen.findByTestId("pick-lines");
    await user.click(await within(lines).findByRole("button", { name: /CAM-500/ }));
    const heading = "CAM-500 - Cam temizleyici 500 ml";
    expect(await screen.findByRole("heading", { name: heading })).toBeInTheDocument();
    await user.click(within(screen.getByTestId("pick-suggestions")).getByText("C-261016-001"));
    const qty = screen.getByRole("textbox", { name: "Miktar (ADET)" });
    await waitFor(() => expect(qty).toHaveValue("24"));
    await user.clear(qty);
    await user.type(qty, "10{Enter}");
    await waitFor(() =>
      expect(salesApi.pickLot).toHaveBeenCalledWith(70, { lot: 70, quantity: "10" }),
    );
    // Toplama bitince okutma alanına dönülür; satır eksik olduğu için seçim değişmez.
    await waitFor(() => expect(screen.getByRole("textbox", { name: "Lot okut" })).toHaveFocus());
    const card = within(screen.getByTestId("pick-lines")).getByRole("button", { name: /CAM-500/ });
    expect(card).toHaveTextContent("Kalan: 14 ADET");
    expect(card).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("heading", { name: heading })).toBeInTheDocument();
  });

  it("rezervesiz lotun önerilen miktarı tek lokasyonun stoğudur, rezerve lot toplanır", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("depo"));
    vi.mocked(scanApi.scanCode).mockResolvedValue(scanned(61, "D-261016-002"));
    const [reserved, free] = suggestions()[0].suggestions;
    vi.mocked(salesApi.shipmentSuggestions).mockResolvedValue(
      suggestions({
        suggestions: [
          { ...reserved, quantity: "260.0000", reserved_quantity: "200.0000" },
          {
            ...reserved,
            location: 10,
            location_code: "RAF-2",
            quantity: "150.0000",
            reserved_quantity: "150.0000",
          },
          { ...free, quantity: "300.0000" },
          { ...free, location: 10, location_code: "RAF-2", quantity: "250.0000" },
        ],
      }),
    );
    renderApp("/sevkiyat/sevkiyatlar/70/toplama");

    await user.type(
      await screen.findByRole("textbox", { name: "Lot okut" }),
      "D-261016-002{Enter}",
    );
    const qty = screen.getByRole("textbox", { name: "Miktar (ADET)" });
    // Rezervesiz kısım backend'de tek lokasyondan alınır: 300 + 250 değil, en büyüğü 300.
    await waitFor(() => expect(qty).toHaveValue("300"));
    // Rezerve lot, satırın tüm lokasyonlardaki rezervasyonlarından toplanır: 200 + 150
    // (aynı yerdeki rezervesiz 60 sayılmaz).
    const rows = screen.getByTestId("pick-suggestions");
    expect(within(rows).getByText("Rezerve 200")).toBeInTheDocument();
    await user.click(within(rows).getAllByText("D-261016-001")[0]);
    await waitFor(() => expect(qty).toHaveValue("350"));
  });

  it("sevkiyat rolü toplama yapamaz", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("sevkiyat"));
    renderApp("/sevkiyat/sevkiyatlar/70/toplama");
    expect(await screen.findByRole("heading", { name: "Toplama: SV-2026-00001" }));
    expect(screen.queryByRole("textbox", { name: "Lot okut" })).toBeNull();
    expect(salesApi.shipmentSuggestions).not.toHaveBeenCalled();
  });
});

describe("müşteri kartı", () => {
  const customer = {
    id: 3,
    code: "M-ZINCIR",
    name: "Zincir Market A.Ş.",
    tax_office: "",
    tax_number: "",
    address: "Gebze",
    phone: "",
    email: "",
    contact_person: "",
    is_active: true,
    min_remaining_shelf_life_days: 180,
  };

  function shippedLot(overrides: Partial<ShippedLot> = {}): ShippedLot {
    return {
      id: 91,
      shipment: 70,
      shipment_number: "SV-2026-00001",
      order_number: "SS-2026-00001",
      dispatched_at: "2026-10-16T15:00:00+03:00",
      product_code: "BULASIK-750",
      product_name: "Bulaşık deterjanı 750 ml",
      lot: 60,
      lot_no: "D-261016-001",
      expiry_date: "2028-10-16",
      quantity: "720.0000",
      ...overrides,
    };
  }

  it("sevkiyat müşteriye sevk edilen lotları görür", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("sevkiyat"));
    vi.mocked(mdApi.getRecord).mockResolvedValue(customer);
    vi.mocked(salesApi.listShippedLots).mockResolvedValue(page([shippedLot()]));
    renderApp("/sevkiyat/musteriler/3");
    const table = await screen.findByTestId("shipped-lots");
    expect(table).toHaveTextContent("D-261016-001");
    expect(table).toHaveTextContent("720");
    expect(within(table).getByRole("link", { name: "SV-2026-00001" })).toHaveAttribute(
      "href",
      "/sevkiyat/sevkiyatlar/70",
    );
    expect(salesApi.listShippedLots).toHaveBeenCalledWith(3, 1);
    // Tek sayfa: sayfalama gösterilmez.
    expect(screen.queryByRole("button", { name: "2" })).toBeNull();
  });

  it("sevk edilen lotlar sayfalanır; ikinci sayfa istenir", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("sevkiyat"));
    vi.mocked(mdApi.getRecord).mockResolvedValue(customer);
    vi.mocked(salesApi.listShippedLots).mockImplementation(async (_customer, pageNo = 1) => ({
      count: salesApi.SHIPPED_LOTS_PAGE_SIZE + 1,
      next: pageNo === 1 ? "/api/v1/sales/shipped-lots/?page=2" : null,
      previous: pageNo === 1 ? null : "/api/v1/sales/shipped-lots/?page=1",
      results: [
        pageNo === 1
          ? shippedLot()
          : shippedLot({
              id: 12,
              lot: 40,
              lot_no: "D-250101-001",
              shipment_number: "SV-2025-00042",
            }),
      ],
    }));
    renderApp("/sevkiyat/musteriler/3");

    expect(await screen.findByTestId("shipped-lots")).toHaveTextContent("D-261016-001");
    expect(salesApi.listShippedLots).toHaveBeenCalledWith(3, 1);
    await user.click(screen.getByRole("button", { name: "2" }));
    await waitFor(() => expect(salesApi.listShippedLots).toHaveBeenCalledWith(3, 2));
    await waitFor(() =>
      expect(screen.getByTestId("shipped-lots")).toHaveTextContent("D-250101-001"),
    );
    expect(screen.getByTestId("shipped-lots")).not.toHaveTextContent("D-261016-001");
  });

  it("sevk edilen lotların bir sayfası yüklenemezse sayfalayıcı kalır, ilk sayfaya dönülür", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("sevkiyat"));
    vi.mocked(mdApi.getRecord).mockResolvedValue(customer);
    vi.mocked(salesApi.listShippedLots).mockImplementation(async (_customer, pageNo = 1) => {
      if (pageNo === 2) throw httpError(404, { detail: "Geçersiz sayfa." });
      return {
        count: salesApi.SHIPPED_LOTS_PAGE_SIZE + 1,
        next: "/api/v1/sales/shipped-lots/?page=2",
        previous: null,
        results: [shippedLot()],
      };
    });
    renderApp("/sevkiyat/musteriler/3");

    expect(await screen.findByTestId("shipped-lots")).toHaveTextContent("D-261016-001");
    await user.click(screen.getByRole("button", { name: "2" }));
    expect(await screen.findByText("Geçersiz sayfa.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "1" }));
    await waitFor(() =>
      expect(screen.getByTestId("shipped-lots")).toHaveTextContent("D-261016-001"),
    );
  });

  it("depo müşteri kartında sevk edilen lotları istemez", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("depo"));
    vi.mocked(mdApi.getRecord).mockResolvedValue(customer);
    renderApp("/sevkiyat/musteriler/3");
    await screen.findByTestId("customer-orders");
    expect(screen.queryByText("Sevk edilen lotlar")).toBeNull();
    expect(salesApi.listShippedLots).not.toHaveBeenCalled();
  });
});
