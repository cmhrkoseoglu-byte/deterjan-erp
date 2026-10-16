import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as authApi from "../../api/auth";
import * as mdApi from "../../api/masterdata";
import * as purchasingApi from "../../api/purchasing";
import type { PurchaseOrder, PurchaseOrderDetail, PurchaseRequest } from "../../api/purchasing";
import * as workflowApi from "../../api/workflow";
import { visibleMenu } from "../../layout/menu";
import { page, userWith } from "../../test/fixtures";
import { renderApp } from "../../test/render";
import { recordPath } from "../../workflow/recordLinks";

vi.mock("../../api/auth");
vi.mock("../../api/purchasing", async (importOriginal) => ({
  ...(await importOriginal<typeof purchasingApi>()),
  listPurchaseOrders: vi.fn(),
  getPurchaseOrder: vi.fn(),
  savePurchaseOrder: vi.fn(),
  submitPurchaseOrder: vi.fn(),
  approvePurchaseOrder: vi.fn(),
  sendPurchaseOrder: vi.fn(),
  receivePurchaseOrder: vi.fn(),
  listPurchaseRequests: vi.fn(),
  savePurchaseRequest: vi.fn(),
  listSuggestions: vi.fn(),
  listExpectedDeliveries: vi.fn(),
  getSupplierPerformance: vi.fn(),
  getPurchasingSettings: vi.fn(),
  savePurchasingSettings: vi.fn(),
}));
vi.mock("../../api/masterdata", async (importOriginal) => ({
  ...(await importOriginal<typeof mdApi>()),
  listRecords: vi.fn(),
}));
vi.mock("../../api/workflow");

function summary(overrides: Partial<PurchaseOrder> = {}): PurchaseOrder {
  return {
    id: 5,
    number: "SA-2026-00001",
    status: "APPROVED",
    status_display: "Onaylandı",
    supplier: 3,
    supplier_code: "T-KIMYA",
    supplier_name: "Kimya A.Ş.",
    supplier_email: "satis@kimya.com",
    order_date: "2026-10-16",
    currency: "EUR",
    exchange_rate: "36.000000",
    notes: "",
    total: "2500.00",
    total_try: "90000.00",
    expected_date: "2026-10-20",
    approval_total_try: "90000.00",
    approval_limit_try: null,
    approved_at: "2026-10-16T10:00:00+03:00",
    approved_by_name: "Yönetim",
    sent_at: null,
    sent_by_name: null,
    sent_to: "",
    closed_note: "",
    cancel_reason: "",
    cancelled_at: null,
    created_at: "2026-10-16T09:00:00+03:00",
    created_by_name: "Satın Alma",
    ...overrides,
  };
}

function detail(overrides: Partial<PurchaseOrderDetail> = {}): PurchaseOrderDetail {
  return {
    ...summary(),
    can_approve: false,
    receipts: [],
    lines: [
      {
        id: 21,
        line_no: 1,
        material: 40,
        material_code: "LAS",
        material_name: "LAS %96",
        quantity: "1000.0000",
        unit: 1,
        unit_code: "KG",
        base_quantity: "1000.0000",
        base_unit_code: "KG",
        unit_price: "2.5000",
        line_total: "2500.00",
        expected_date: "2026-10-20",
        note: "",
        requests: [],
        request_numbers: [],
        received_quantity: "400.0000",
        pending_quantity: "600.0000",
      },
    ],
    ...overrides,
  };
}

function request(overrides: Partial<PurchaseRequest> = {}): PurchaseRequest {
  return {
    id: 9,
    number: "ST-2026-00001",
    status: "OPEN",
    status_display: "Açık",
    source: "AUTO",
    source_display: "Otomatik",
    material: 40,
    material_code: "LAS",
    material_name: "LAS %96",
    unit_code: "KG",
    quantity: "700.0000",
    need_date: "2026-10-20",
    reason: "Otomatik öneri",
    order_id: null,
    order_number: null,
    cancel_reason: "",
    cancelled_at: null,
    created_at: "2026-10-16T07:00:00+03:00",
    created_by: null,
    created_by_name: null,
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
  vi.mocked(purchasingApi.listPurchaseOrders).mockResolvedValue(page([summary()]));
  vi.mocked(purchasingApi.getPurchaseOrder).mockResolvedValue(detail());
  vi.mocked(purchasingApi.listPurchaseRequests).mockResolvedValue(page([request()]));
  vi.mocked(purchasingApi.listSuggestions).mockResolvedValue([]);
  vi.mocked(purchasingApi.listExpectedDeliveries).mockResolvedValue([]);
});

describe("satın alma", () => {
  it("menü: depo, planlama ve üretim de satın almayı görür; laboratuvar görmez", () => {
    for (const role of ["satin_alma", "yonetim", "depo", "planlama", "uretim"] as const) {
      expect(visibleMenu(userWith(role)).map((item) => item.key)).toContain("purchasing");
    }
    expect(visibleMenu(userWith("laboratuvar")).map((item) => item.key)).not.toContain(
      "purchasing",
    );
  });

  it("satın alma sipariş listesini tutarla görür ve yeni sipariş açabilir", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("satin_alma"));
    renderApp("/satin-alma");
    const table = await screen.findByTestId("purchase-orders");
    await within(table).findByText("SA-2026-00001");
    expect(table).toHaveTextContent("2.500,00");
    expect(screen.getByRole("button", { name: "Yeni sipariş" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Tedarikçi performansı" })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Ayarlar" })).toBeNull();
  });

  it("planlama yalnızca talepleri ve önerileri görür", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("planlama"));
    renderApp("/satin-alma");
    const table = await screen.findByTestId("purchase-requests");
    await within(table).findByText("ST-2026-00001");
    expect(screen.getByRole("tab", { name: "Öneriler" })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Siparişler" })).toBeNull();
  });

  it("depo beklenen teslimatları görür; sipariş detayında tutar yok, mal kabul açar", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("depo"));
    vi.mocked(purchasingApi.listExpectedDeliveries).mockResolvedValue([
      {
        order_line: 21,
        order_id: 5,
        order_number: "SA-2026-00001",
        order_status: "APPROVED",
        supplier_id: 3,
        supplier_name: "Kimya A.Ş.",
        material: 40,
        material_code: "LAS",
        material_name: "LAS %96",
        quantity: "1000.0000",
        unit_code: "KG",
        base_unit_code: "KG",
        base_quantity: "1000.0000",
        received_quantity: "400.0000",
        pending_quantity: "600.0000",
        expected_date: "2026-10-01",
        is_late: true,
      },
    ]);
    const line = { ...detail().lines[0], unit_price: undefined, line_total: undefined };
    vi.mocked(purchasingApi.getPurchaseOrder).mockResolvedValue(
      detail({ total: undefined, total_try: undefined, lines: [line] }),
    );
    vi.mocked(purchasingApi.receivePurchaseOrder).mockResolvedValue({
      id: 77,
      number: "MK-2026-00010",
    });
    renderApp("/satin-alma");
    const table = await screen.findByTestId("expected-deliveries");
    expect(table).toHaveTextContent("Gecikti");
    await userEvent.click(within(table).getByText("SA-2026-00001"));

    const lines = await screen.findByTestId("purchase-lines");
    expect(lines).toHaveTextContent("600 KG");
    expect(screen.queryByText("Birim fiyat")).toBeNull();
    expect(screen.getByText(/Tutarlar yalnızca/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Siparişten mal kabul" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByLabelText(/Gelen miktar/)).toHaveValue("600");
    await userEvent.click(within(dialog).getByRole("button", { name: "Siparişten mal kabul" }));
    await waitFor(() => expect(purchasingApi.receivePurchaseOrder).toHaveBeenCalled());
    const [orderId, payload] = vi.mocked(purchasingApi.receivePurchaseOrder).mock.calls[0];
    expect(orderId).toBe(5);
    expect(payload.lines).toEqual([
      {
        order_line: 21,
        quantity: "600",
        supplier_lot_no: "",
        manufactured_at: null,
        expiry_date: null,
      },
    ]);
  });

  it("limit dışındaki taslak yönetim onayına gönderilir", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("satin_alma"));
    const draft = detail({ status: "DRAFT", can_approve: false });
    vi.mocked(purchasingApi.getPurchaseOrder).mockResolvedValue(draft);
    vi.mocked(purchasingApi.savePurchaseOrder).mockResolvedValue(draft);
    vi.mocked(purchasingApi.submitPurchaseOrder).mockResolvedValue(
      detail({ status: "PENDING_APPROVAL" }),
    );
    renderApp("/satin-alma/siparisler/5");

    expect(await screen.findAllByTestId("purchase-line")).toHaveLength(1);
    expect(screen.queryByRole("button", { name: "Onayla" })).toBeNull();
    expect(screen.getByText(/yönetim onaylar/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Yönetim onayına gönder" }));
    await waitFor(() => expect(purchasingApi.submitPurchaseOrder).toHaveBeenCalledWith(5));
    const payload = vi.mocked(purchasingApi.savePurchaseOrder).mock.calls[0][1];
    expect(payload).toMatchObject({
      supplier: 3,
      currency: "EUR",
      exchange_rate: "36",
      lines: [
        {
          id: 21,
          material: 40,
          quantity: "1000",
          unit: 1,
          unit_price: "2.5",
          expected_date: "2026-10-20",
          requests: [],
        },
      ],
    });
  });

  it("yönetim onaydaki siparişi onaylar", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("yonetim"));
    vi.mocked(purchasingApi.getPurchaseOrder).mockResolvedValue(
      detail({ status: "PENDING_APPROVAL", can_approve: true }),
    );
    vi.mocked(purchasingApi.approvePurchaseOrder).mockResolvedValue(detail());
    renderApp("/satin-alma/siparisler/5");

    expect(await screen.findByTestId("purchase-total")).toHaveTextContent("90.000,00");
    expect(screen.getByRole("button", { name: "Taslağa geri gönder" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Onayla" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Onayla" }));
    await waitFor(() => expect(purchasingApi.approvePurchaseOrder).toHaveBeenCalledWith(5));
  });

  it("gönderimde tedarikçi e-postası onaylanır", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("satin_alma"));
    vi.mocked(purchasingApi.sendPurchaseOrder).mockResolvedValue(detail({ status: "SENT" }));
    renderApp("/satin-alma/siparisler/5");

    await userEvent.click(await screen.findByRole("button", { name: "Tedarikçiye gönder" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByLabelText(/E-posta adresi/)).toHaveValue("satis@kimya.com");
    await userEvent.click(within(dialog).getByRole("button", { name: "Tedarikçiye gönder" }));
    await waitFor(() =>
      expect(purchasingApi.sendPurchaseOrder).toHaveBeenCalledWith(5, "satis@kimya.com"),
    );
  });

  it("öneriden talep açılır", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("satin_alma"));
    vi.mocked(mdApi.listRecords).mockResolvedValue(
      page([
        {
          id: 40,
          code: "LAS",
          name: "LAS %96",
          base_unit: 1,
          base_unit_code: "KG",
        } as unknown as mdApi.Material,
      ]),
    );
    vi.mocked(purchasingApi.listSuggestions).mockResolvedValue([
      {
        material: 40,
        material_code: "LAS",
        material_name: "LAS %96",
        unit_code: "KG",
        demand: "1200.0000",
        min_stock: "500.0000",
        free_stock: "800.0000",
        open_orders: "150.0000",
        open_requests: "50.0000",
        suggested: "700.0000",
        need_date: "2026-10-20",
        sources: [{ order_number: "UE-2026-00001", planned_date: "2026-10-20", quantity: "600" }],
      },
    ]);
    vi.mocked(purchasingApi.savePurchaseRequest).mockResolvedValue(request());
    renderApp("/satin-alma/oneriler");

    const table = await screen.findByTestId("purchase-suggestions");
    expect(table).toHaveTextContent("UE-2026-00001");
    await userEvent.click(within(table).getByRole("button", { name: "Talep aç" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Kaydet" }));
    await waitFor(() =>
      expect(purchasingApi.savePurchaseRequest).toHaveBeenCalledWith(null, {
        material: 40,
        quantity: "700",
        need_date: "2026-10-20",
        reason: "",
      }),
    );
  });

  it("yönetim onay limitini girer", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("yonetim"));
    vi.mocked(purchasingApi.getPurchasingSettings).mockResolvedValue({
      approval_limit_try: null,
      over_receipt_tolerance_pct: "10.00",
      updated_at: "2026-10-16T09:00:00+03:00",
      updated_by_name: null,
    });
    vi.mocked(purchasingApi.savePurchasingSettings).mockResolvedValue({
      approval_limit_try: "50000.00",
      over_receipt_tolerance_pct: "10.00",
      updated_at: "2026-10-16T10:00:00+03:00",
      updated_by_name: "Yönetim",
    });
    renderApp("/satin-alma/ayarlar");
    await userEvent.type(await screen.findByLabelText(/Onay limiti/), "50000");
    await userEvent.click(screen.getByRole("button", { name: "Kaydet" }));
    await waitFor(() =>
      expect(purchasingApi.savePurchasingSettings).toHaveBeenCalledWith({
        approval_limit_try: "50000",
        over_receipt_tolerance_pct: "10",
      }),
    );
  });

  it("görevdeki sipariş kaydı detay sayfasına gider", () => {
    expect(recordPath({ model: "purchasing.purchaseorder", id: 5, repr: "" })).toBe(
      "/satin-alma/siparisler/5",
    );
  });
});
