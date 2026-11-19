import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as authApi from "../../api/auth";
import * as ledgerApi from "../../api/ledger";
import * as mdApi from "../../api/masterdata";
import * as salesApi from "../../api/sales";
import type { CustomerTracking, TrackedOrder } from "../../api/sales";
import * as workflowApi from "../../api/workflow";
import { page, userWith, withAccess, withoutAccess } from "../../test/fixtures";
import { renderApp } from "../../test/render";

vi.mock("../../api/auth");
vi.mock("../../api/sales", async (importOriginal) => ({
  ...(await importOriginal<typeof salesApi>()),
  listSalesOrders: vi.fn(),
  listTrackedOrders: vi.fn(),
  listCustomerTracking: vi.fn(),
  listShippedLots: vi.fn(),
}));
vi.mock("../../api/ledger", async (importOriginal) => ({
  ...(await importOriginal<typeof ledgerApi>()),
  getPartnerSummary: vi.fn(),
}));
vi.mock("../../api/masterdata", async (importOriginal) => ({
  ...(await importOriginal<typeof mdApi>()),
  listRecords: vi.fn(),
  getRecord: vi.fn(),
}));
vi.mock("../../api/workflow");

const LEDGER = { "ledger.customers": "rv", "sensitive.prices": "v" };

function customerRow(overrides: Partial<CustomerTracking> = {}): CustomerTracking {
  return {
    id: 3,
    code: "M-ZINCIR",
    name: "Zincir Market A.Ş.",
    open_orders: 2,
    late_orders: 1,
    due_soon: 1,
    oldest_due_date: "2026-11-15",
    max_days_late: 4,
    ...overrides,
  };
}

function tracked(overrides: Partial<TrackedOrder> = {}): TrackedOrder {
  return {
    id: 7,
    number: "SS-2026-00001",
    status: "PARTIALLY_SHIPPED",
    status_display: "Kısmen sevk edildi",
    customer: 3,
    customer_code: "M-ZINCIR",
    customer_name: "Zincir Market A.Ş.",
    order_date: "2026-11-01",
    requested_delivery_date: "2026-11-10",
    promised_date: "2026-11-15",
    due_date: "2026-11-15",
    days_late: 4,
    is_late: true,
    last_dispatched_at: "2026-11-12T10:00:00+03:00",
    customer_po_no: "PO-1",
    lines: [
      {
        id: 11,
        line_no: 1,
        product: 90,
        product_code: "BULASIK-750",
        product_name: "Bulaşık deterjanı 750 ml",
        quantity: "2.0000",
        unit_code: "KOLI",
        base_quantity: "24.0000",
        base_unit_code: "ADET",
        shipped_quantity: "12.0000",
        planned_quantity: "0.0000",
        remaining_quantity: "12.0000",
        shipped_in_unit: "1.0000",
        remaining_in_unit: "1.0000",
        unit_price: "10.0000",
        currency: "TRY",
        line_total: "20.00",
      },
    ],
    shipments: [
      {
        id: 21,
        number: "SV-2026-00001",
        status: "DISPATCHED",
        status_display: "Sevk edildi",
        planned_date: "2026-11-12",
        dispatched_at: "2026-11-12T10:00:00+03:00",
      },
    ],
    totals: [{ currency: "TRY", amount: "20.00" }],
    ...overrides,
  };
}

function inDays(days: number): string {
  const now = new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Istanbul" }).format(new Date());
  const [y, m, d] = now.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d + days)).toISOString().slice(0, 10);
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(authApi.fetchCsrf).mockResolvedValue();
  vi.mocked(workflowApi.fetchTasks).mockResolvedValue(page([]));
  vi.mocked(workflowApi.fetchNotifications).mockResolvedValue(page([]));
  vi.mocked(workflowApi.fetchUnreadCount).mockResolvedValue(0);
  vi.mocked(mdApi.listRecords).mockResolvedValue(page([]));
  vi.mocked(salesApi.listSalesOrders).mockResolvedValue(page([]));
  vi.mocked(salesApi.listShippedLots).mockResolvedValue(page([]));
  vi.mocked(workflowApi.fetchComments).mockResolvedValue([]);
  vi.mocked(workflowApi.fetchRecordHistory).mockResolvedValue([]);
  vi.mocked(salesApi.listCustomerTracking).mockResolvedValue(page([customerRow()]));
  vi.mocked(salesApi.listTrackedOrders).mockResolvedValue(page([tracked()]));
  vi.mocked(ledgerApi.getPartnerSummary).mockResolvedValue({
    partner: {
      id: 3,
      code: "M-ZINCIR",
      name: "Zincir Market A.Ş.",
      payment_term_days: 30,
      vat_exempt: false,
      is_active: true,
    },
    balances: [{ currency: "TRY", last_date: "2026-11-12", balance: "1500.00", overdue: "300.00" }],
    missing: 0,
  });
});

describe("sipariş takibi", () => {
  it("müşteri seçilince geciken siparişi, kalanı ve sevkiyatı gösterir", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(
      withoutAccess(userWith("sevkiyat"), {
        "ledger.customers": "rvca",
        "sensitive.prices": "rvca",
      }),
    );
    renderApp("/sevkiyat/takip");

    const customers = await screen.findByTestId("tracking-customers");
    expect(within(customers).getByText("4 gün")).toBeInTheDocument();
    await user.click(within(customers).getByText("Zincir Market A.Ş."));

    const orders = await screen.findByTestId("tracking-orders");
    expect(salesApi.listTrackedOrders).toHaveBeenCalledWith({ customer: 3, page_size: 100 });
    const row = within(orders).getByTestId("tracking-order-7");
    expect(row).toHaveTextContent("SS-2026-00001");
    expect(row).toHaveTextContent("4 gün gecikti");
    expect(row).toHaveTextContent("1 / 2 KOLI");
    expect(row).toHaveTextContent("20,00 TRY");

    await user.click(within(row).getByRole("button", { name: "Satırları göster" }));
    const lines = await screen.findByTestId("tracking-lines-7");
    expect(lines).toHaveTextContent("12 ADET");
    expect(screen.getByRole("link", { name: "SV-2026-00001" })).toBeInTheDocument();

    // Cari yetkisi olmayan bakiyeyi görmez ve sormaz.
    expect(screen.queryByTestId("tracking-balance")).toBeNull();
    expect(ledgerApi.getPartnerSummary).not.toHaveBeenCalled();
  });

  it("süzgeçler takip uç noktalarına gider", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("sevkiyat"));
    renderApp("/sevkiyat/takip");

    const customers = await screen.findByTestId("tracking-customers");
    const [customerLate] = screen.getAllByLabelText("Yalnız gecikenler");
    await user.click(customerLate);
    await waitFor(() =>
      expect(salesApi.listCustomerTracking).toHaveBeenLastCalledWith({
        page: 1,
        page_size: 50,
        search: undefined,
        late: true,
      }),
    );

    await user.click(within(customers).getByText("Zincir Market A.Ş."));
    const selected = await screen.findByTestId("tracking-selected");
    await user.click(within(selected).getByLabelText("Yalnız gecikenler"));
    await user.click(within(selected).getByLabelText("Bu hafta vadesi gelenler"));
    await user.click(within(selected).getByLabelText(/Biten siparişleri de göster/));
    await waitFor(() =>
      expect(salesApi.listTrackedOrders).toHaveBeenLastCalledWith({
        customer: 3,
        page_size: 100,
        late: true,
        due_before: inDays(7),
        include_finished: true,
      }),
    );
  });

  it("cari yetkisi ve fiyat görme yetkisi olan bakiyeyi ve vadesi geçeni görür", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(withAccess(userWith("sevkiyat"), LEDGER));
    renderApp("/sevkiyat/takip");

    await user.click(await screen.findByText("Zincir Market A.Ş."));
    const balance = await screen.findByTestId("tracking-balance");
    await within(balance).findByText("1.500,00 TRY (B)");
    expect(balance).toHaveTextContent("Vadesi geçen: 300,00 TRY");
    expect(within(balance).getByRole("link", { name: "Cari ekstresi" })).toHaveAttribute(
      "href",
      "/cari-hesaplar/musteriler/3",
    );
    expect(ledgerApi.getPartnerSummary).toHaveBeenCalledWith("customers", 3);
  });

  it("fiyat görmeyen cari kullanıcısı bakiyeyi görmez", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(
      withoutAccess(withAccess(userWith("sevkiyat"), LEDGER), { "sensitive.prices": "rvca" }),
    );
    renderApp("/sevkiyat/takip");

    await user.click(await screen.findByText("Zincir Market A.Ş."));
    await screen.findByTestId("tracking-orders");
    expect(screen.queryByTestId("tracking-balance")).toBeNull();
    expect(ledgerApi.getPartnerSummary).not.toHaveBeenCalled();
  });

  it("siparişleri göremeyen sekmeyi görmez ve takip sormaz", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(
      withoutAccess(userWith("depo"), { "sales.orders": "rvca" }),
    );
    renderApp("/sevkiyat");

    await screen.findByRole("tab", { name: "Toplama" });
    expect(screen.queryByRole("tab", { name: "Sipariş takibi" })).toBeNull();
    expect(salesApi.listCustomerTracking).not.toHaveBeenCalled();
  });

  it("müşteri kartında açık siparişler paneli görünür", async () => {
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

    expect(await screen.findByText("Açık siparişler")).toBeInTheDocument();
    expect(await screen.findByTestId("tracking-order-7")).toHaveTextContent("4 gün gecikti");
    expect(salesApi.listTrackedOrders).toHaveBeenCalledWith({ customer: 3, page_size: 100 });
  });
});
