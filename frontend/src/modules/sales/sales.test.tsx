import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as authApi from "../../api/auth";
import * as mdApi from "../../api/masterdata";
import * as salesApi from "../../api/sales";
import type { SalesOrder, SalesOrderDetail } from "../../api/sales";
import * as workflowApi from "../../api/workflow";
import { page, userWith } from "../../test/fixtures";
import { renderApp } from "../../test/render";
import { recordPath } from "../../workflow/recordLinks";

vi.mock("../../api/auth");
vi.mock("../../api/sales", async (importOriginal) => ({
  ...(await importOriginal<typeof salesApi>()),
  listSalesOrders: vi.fn(),
  getSalesOrder: vi.fn(),
  saveSalesOrder: vi.fn(),
  confirmSalesOrder: vi.fn(),
  reserveShortages: vi.fn(),
  releaseReservation: vi.fn(),
  reserveLot: vi.fn(),
  listCandidates: vi.fn(),
}));
vi.mock("../../api/masterdata", async (importOriginal) => ({
  ...(await importOriginal<typeof mdApi>()),
  listRecords: vi.fn(),
  getRecord: vi.fn(),
}));
vi.mock("../../api/workflow");

function summary(overrides: Partial<SalesOrder> = {}): SalesOrder {
  return {
    id: 7,
    number: "SS-2026-00001",
    status: "CONFIRMED",
    status_display: "Onaylandı",
    customer: 3,
    customer_code: "M-ZINCIR",
    customer_name: "Zincir Market A.Ş.",
    order_date: "2026-10-16",
    requested_delivery_date: "2026-10-19",
    delivery_address: "Gebze",
    customer_po_no: "PO-1",
    notes: "",
    line_count: 1,
    has_shortage: true,
    confirmed_at: "2026-10-16T09:00:00+03:00",
    confirmed_by_name: "Sevkiyat",
    closed_at: null,
    cancel_reason: "",
    cancelled_at: null,
    created_at: "2026-10-16T08:00:00+03:00",
    created_by_name: "Sevkiyat",
    ...overrides,
  };
}

function detail(overrides: Partial<SalesOrderDetail> = {}): SalesOrderDetail {
  return {
    ...summary(),
    min_remaining_shelf_life_days: 180,
    is_editable: false,
    lines: [
      {
        id: 11,
        line_no: 1,
        product: 90,
        product_code: "BULASIK-LIMON-750",
        product_name: "Bulaşık deterjanı limonlu 750 ml",
        quantity: "1.0000",
        unit: 7,
        unit_code: "PALET",
        base_quantity: "720.0000",
        base_unit_code: "ADET",
        unit_price: "1150.0000",
        currency: "TRY",
        line_total: "1150.00",
        note: "",
        reserved_quantity: "700.0000",
        shipped_quantity: "0.0000",
        shortage_quantity: "20.0000",
        planned_quantity: "0.0000",
        plannable_quantity: "720.0000",
      },
    ],
    totals: [{ currency: "TRY", amount: "1150.00" }],
    shipments: [],
    reservations: [
      {
        id: 51,
        line: 11,
        line_no: 1,
        lot: 60,
        lot_no: "D-261016-001",
        expiry_date: "2028-10-16",
        location: 9,
        location_code: "MAMUL-DEPO",
        quantity: "700.0000",
        unit: "ADET",
        status: "ACTIVE",
        status_display: "Aktif",
        note: "",
        created_at: "2026-10-16T09:00:00+03:00",
        created_by_name: "Sevkiyat",
        closed_at: null,
      },
    ],
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
  vi.mocked(salesApi.listSalesOrders).mockResolvedValue(page([summary()]));
  vi.mocked(salesApi.getSalesOrder).mockResolvedValue(detail());
  vi.mocked(salesApi.listCandidates).mockResolvedValue([]);
});

describe("satış siparişleri", () => {
  it("sevkiyat sipariş listesini eksik işaretiyle görür ve yeni sipariş açabilir", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("sevkiyat"));
    renderApp("/sevkiyat");
    const table = await screen.findByTestId("sales-orders");
    await within(table).findByText("SS-2026-00001");
    expect(within(table).getByText("Eksik var")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Yeni sipariş" })).toBeInTheDocument();
  });

  it("planlama siparişleri görür ama yeni sipariş açamaz", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("planlama"));
    renderApp("/sevkiyat/siparisler");
    await screen.findByText("SS-2026-00001");
    expect(screen.queryByRole("button", { name: "Yeni sipariş" })).toBeNull();
  });

  it("üretim rolü sevkiyat sayfasına giremez", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("uretim"));
    renderApp("/sevkiyat");
    expect(await screen.findByText(/yetkiniz yok/i));
  });

  it("detayda satır miktarları, toplam ve rezervasyonlar görünür; eksikler rezerve edilir", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("sevkiyat"));
    const filled = detail({
      has_shortage: false,
      lines: [{ ...detail().lines[0], reserved_quantity: "720.0000", shortage_quantity: "0.0000" }],
    });
    vi.mocked(salesApi.reserveShortages).mockResolvedValue(filled);
    renderApp("/sevkiyat/siparisler/7");

    const lines = await screen.findByTestId("order-lines");
    expect(lines).toHaveTextContent("1 PALET");
    expect(lines).toHaveTextContent("720 ADET");
    expect(screen.getByTestId("order-totals")).toHaveTextContent("Toplam: 1.150,00 TRY");
    expect(screen.getByTestId("reservations")).toHaveTextContent("D-261016-001");
    expect(screen.getByText("180 gün")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Eksikleri rezerve et" }));
    await waitFor(() => expect(salesApi.reserveShortages).toHaveBeenCalledWith(7));
  });

  it("satıra elle lot seçilir; raf ömrü yetersiz lot seçilemez", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("sevkiyat"));
    vi.mocked(salesApi.listCandidates).mockResolvedValue([
      {
        lot: 61,
        lot_no: "D-261016-002",
        expiry_date: "2026-12-01",
        location: 9,
        location_code: "MAMUL-DEPO",
        quantity: "100.0000",
        reserved_quantity: "0.0000",
        available_quantity: "100.0000",
        unit: "ADET",
        meets_shelf_life: false,
      },
      {
        lot: 62,
        lot_no: "D-261016-003",
        expiry_date: "2028-12-01",
        location: 9,
        location_code: "MAMUL-DEPO",
        quantity: "50.0000",
        reserved_quantity: "0.0000",
        available_quantity: "50.0000",
        unit: "ADET",
        meets_shelf_life: true,
      },
    ]);
    vi.mocked(salesApi.reserveLot).mockResolvedValue(detail());
    renderApp("/sevkiyat/siparisler/7");

    await userEvent.click(await screen.findByRole("button", { name: "Lot seç" }));
    const short = await screen.findByRole("radio", { name: /D-261016-002/ });
    expect(short).toBeDisabled();
    await userEvent.click(screen.getByRole("radio", { name: /D-261016-003/ }));
    expect(screen.getByLabelText("Rezerve edilecek adet")).toHaveValue("20");
    await userEvent.click(screen.getByRole("button", { name: "Rezerve et" }));
    await waitFor(() =>
      expect(salesApi.reserveLot).toHaveBeenCalledWith(7, {
        line: 11,
        lot: 62,
        location: 9,
        quantity: "20",
      }),
    );
  });

  it("taslak sipariş düzenlenir ve onaylanır", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("yonetim"));
    const draft = detail({ status: "DRAFT", is_editable: true, reservations: [] });
    vi.mocked(salesApi.getSalesOrder).mockResolvedValue(draft);
    vi.mocked(salesApi.saveSalesOrder).mockResolvedValue(draft);
    vi.mocked(salesApi.confirmSalesOrder).mockResolvedValue(detail());
    renderApp("/sevkiyat/siparisler/7");

    expect(await screen.findAllByTestId("order-line")).toHaveLength(1);
    await userEvent.click(screen.getByRole("button", { name: "Onayla ve rezerve et" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Onayla ve rezerve et" }));
    await waitFor(() => expect(salesApi.confirmSalesOrder).toHaveBeenCalledWith(7));
    const payload = vi.mocked(salesApi.saveSalesOrder).mock.calls[0][1];
    expect(payload.lines).toEqual([
      {
        id: 11,
        product: 90,
        quantity: "1",
        unit: 7,
        unit_price: "1150",
        currency: "TRY",
        note: "",
      },
    ]);
  });

  it("müşteri kartı sipariş geçmişini gösterir", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("sevkiyat"));
    vi.mocked(mdApi.getRecord).mockResolvedValue({
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
    });
    renderApp("/sevkiyat/musteriler/3");

    expect(await screen.findByText("Müşteri kartı: Zincir Market A.Ş.")).toBeInTheDocument();
    expect(await screen.findByTestId("customer-orders")).toHaveTextContent("SS-2026-00001");
    expect(salesApi.listSalesOrders).toHaveBeenCalledWith({ customer: 3, page_size: 100 });
  });

  it("görevdeki sipariş kaydı detay sayfasına gider", () => {
    expect(recordPath({ model: "sales.salesorder", id: 7, repr: "" })).toBe(
      "/sevkiyat/siparisler/7",
    );
  });
});
