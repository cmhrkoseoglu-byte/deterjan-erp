import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as authApi from "../../api/auth";
import * as mdApi from "../../api/masterdata";
import * as portalApi from "../../api/portal";
import type {
  OrderableProduct,
  OrderRequest,
  StaffOrderRequest,
  PortalAccount,
  PortalOrder,
  PortalShipment,
  Receipt,
  SupplierOrder,
} from "../../api/portal";
import type { CurrentUser } from "../../api/types";
import * as workflowApi from "../../api/workflow";
import { httpError, page, userWith } from "../../test/fixtures";
import { renderApp } from "../../test/render";

vi.mock("../../api/auth");
vi.mock("../../api/workflow");
vi.mock("../../api/portal");
vi.mock("../../api/masterdata", async (importOriginal) => ({
  ...(await importOriginal<typeof mdApi>()),
  listRecords: vi.fn(),
}));

function portalUser(kind: "customer" | "supplier", overrides: Partial<CurrentUser> = {}) {
  return {
    ...userWith(),
    username: `${kind}.yetkili`,
    full_name: "Portal Yetkili",
    roles: [],
    access: {},
    account_type: kind === "customer" ? "customer_portal" : "supplier_portal",
    idle_timeout_seconds: 1800,
    ...overrides,
  } as CurrentUser;
}

const ORDER: PortalOrder = {
  id: 7,
  number: "SS-2026-00007",
  customer_po_no: "PO-55",
  order_date: "2026-11-01",
  requested_delivery_date: "2026-11-10",
  promised_date: "2026-11-12",
  due_date: "2026-11-12",
  status: "PARTIALLY_SHIPPED",
  status_display: "Kısmen sevk edildi",
  delivery_address: "Gebze",
  lines: [
    {
      line_no: 1,
      product_code: "BULASIK-750",
      product_name: "Bulaşık deterjanı",
      quantity: "2.0000",
      unit_code: "KOLI",
      base_quantity: "24.0000",
      base_unit_code: "ADET",
      shipped_quantity: "12.0000",
      remaining_quantity: "12.0000",
      shipped_in_unit: "1.0000",
      remaining_in_unit: "1.0000",
      unit_price: "10.0000",
      currency: "TRY",
      line_total: "20.00",
    },
  ],
  totals: [{ currency: "TRY", amount: "20.00" }],
};

const SHIPMENT: PortalShipment = {
  id: 21,
  number: "SV-2026-00021",
  status: "DISPATCHED",
  status_display: "Sevk edildi",
  order_id: 7,
  order_number: "SS-2026-00007",
  customer_po_no: "PO-55",
  planned_date: "2026-11-05",
  dispatched_at: "2026-11-05T10:00:00+03:00",
  vehicle_plate: "34 ABC 123",
  carrier: "",
  has_waybill: true,
};

const SUPPLIER_ORDER: SupplierOrder = {
  id: 9,
  number: "SA-2026-00009",
  order_date: "2026-11-02",
  sent_at: "2026-11-02T09:00:00+03:00",
  currency: "TRY",
  status: "PARTIALLY_RECEIVED",
  status_display: "Kısmen teslim alındı",
  notes: "Analiz sertifikası ekleyin",
  total: "1000.00",
  lines: [
    {
      line_no: 1,
      material_code: "HM-LAS",
      material_name: "LAS",
      quantity: "100.0000",
      unit_code: "KG",
      base_quantity: "100.0000",
      base_unit_code: "KG",
      unit_price: "10.0000",
      line_total: "1000.00",
      expected_date: "2026-11-20",
      received_quantity: "40.0000",
      remaining_quantity: "60.0000",
      received_in_unit: "40.0000",
      remaining_in_unit: "60.0000",
    },
  ],
};

const RECEIPT: Receipt = {
  id: 4,
  number: "MK-2026-00004",
  receipt_date: "2026-11-10",
  delivery_note_no: "TED-7",
  lines: [
    {
      line_no: 1,
      material_code: "HM-LAS",
      material_name: "LAS",
      quantity: "40.0000",
      unit_code: "KG",
      supplier_lot_no: "TL-55",
      order_number: "SA-2026-00009",
    },
  ],
};

const ACCOUNT: PortalAccount = {
  id: 3,
  kind: "customer",
  username: "ali.musteri",
  full_name: "Ali Müşteri",
  email: "ali@example.com",
  phone: "",
  is_active: true,
  last_login: null,
  password_change_required: true,
  firm_id: 5,
  firm_code: "M-ZINCIR",
  firm_name: "Zincir Market A.Ş.",
  firm_is_active: true,
  created_at: "2026-11-19T10:00:00+03:00",
};

const REQUEST: OrderRequest = {
  id: 11,
  number: "MT-2026-00011",
  status: "SUBMITTED",
  status_display: "Gönderildi",
  requested_delivery_date: "2026-12-01",
  customer_po_no: "PO-9",
  delivery_address: "Gebze",
  note: "",
  lines: [
    {
      line_no: 1,
      product: 90,
      product_code: "BULASIK-750",
      product_name: "Bulaşık deterjanı",
      quantity: "2.0000",
      unit: 7,
      unit_code: "KOLI",
    },
  ],
  reject_reason: "",
  order_id: null,
  order_number: null,
  created_at: "2026-11-20T10:00:00+03:00",
  decided_at: null,
};

const STAFF_REQUEST: StaffOrderRequest = {
  ...REQUEST,
  customer: 5,
  customer_code: "M-ZINCIR",
  customer_name: "Zincir Market A.Ş.",
  created_by_name: "Ali Müşteri",
  decided_by_name: "",
  sales_order: null,
};

const PRODUCT: OrderableProduct = {
  id: 90,
  code: "BULASIK-750",
  name: "Bulaşık deterjanı",
  units: [
    { id: 1, code: "ADET", name: "Adet" },
    { id: 7, code: "KOLI", name: "Koli" },
  ],
};

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(authApi.fetchCsrf).mockResolvedValue();
  vi.mocked(workflowApi.fetchTasks).mockResolvedValue(page([]));
  vi.mocked(workflowApi.fetchNotifications).mockResolvedValue(page([]));
  vi.mocked(workflowApi.fetchUnreadCount).mockResolvedValue(0);
  vi.mocked(portalApi.fetchPortalMe).mockResolvedValue({
    kind: "customer",
    firm_code: "M-ZINCIR",
    firm_name: "Zincir Market A.Ş.",
  });
  vi.mocked(portalApi.listCustomerOrders).mockResolvedValue(page([ORDER]));
  vi.mocked(portalApi.getCustomerOrder).mockResolvedValue(ORDER);
  vi.mocked(portalApi.listCustomerShipments).mockResolvedValue(page([SHIPMENT]));
  vi.mocked(portalApi.getCustomerShipment).mockResolvedValue({
    ...SHIPMENT,
    lines: [
      {
        line_no: 1,
        product_code: "BULASIK-750",
        product_name: "Bulaşık deterjanı",
        quantity: "12.0000",
        base_unit_code: "ADET",
        quantity_in_unit: "1.0000",
        unit_code: "KOLI",
      },
    ],
  });
  vi.mocked(portalApi.listSupplierOrders).mockResolvedValue(page([SUPPLIER_ORDER]));
  vi.mocked(portalApi.getSupplierOrder).mockResolvedValue(SUPPLIER_ORDER);
  vi.mocked(portalApi.listReceipts).mockResolvedValue(page([RECEIPT]));
  vi.mocked(portalApi.getReceipt).mockResolvedValue(RECEIPT);
  vi.mocked(portalApi.fetchBalances).mockResolvedValue([
    {
      currency: "TRY",
      debit: "1500.00",
      credit: "0.00",
      balance: "1500.00",
      overdue: "300.00",
      last_date: "2026-11-05",
      aging: { not_due: "1200.00", d1_30: "300.00", d31_60: "0", d61_90: "0", d90_plus: "0" },
    },
  ]);
  vi.mocked(portalApi.fetchStatement).mockResolvedValue({
    date_from: null,
    date_to: null,
    currencies: [
      {
        currency: "TRY",
        opening: "0",
        total_debit: "1500.00",
        total_credit: "0",
        closing: "1500.00",
        rows: [
          {
            number: "CH-2026-00001",
            entry_date: "2026-11-05",
            kind_display: "Satış",
            document: "SV-2026-00021",
            description: "",
            debit: "1500.00",
            credit: "0.00",
            balance: "1500.00",
            due_date: "2026-12-05",
            is_reversed: false,
          },
        ],
      },
    ],
  });
  vi.mocked(portalApi.downloadWaybill).mockResolvedValue();
  vi.mocked(portalApi.downloadSupplierOrder).mockResolvedValue();
  vi.mocked(portalApi.downloadStatementPdf).mockResolvedValue();
  vi.mocked(portalApi.listRequests).mockResolvedValue(page([REQUEST]));
  vi.mocked(portalApi.getRequest).mockResolvedValue(REQUEST);
  vi.mocked(portalApi.listOrderableProducts).mockResolvedValue([PRODUCT]);
  vi.mocked(portalApi.listStaffRequests).mockResolvedValue(page([STAFF_REQUEST]));
  vi.mocked(portalApi.getStaffRequest).mockResolvedValue(STAFF_REQUEST);
});

describe("müşteri portalı", () => {
  it("açılışta portal düzeniyle siparişlerini görür; çalışan menüsü yoktur", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(portalUser("customer"));
    const { router } = renderApp("/");

    const table = await screen.findByTestId("portal-orders");
    expect(router.state.location.pathname).toBe("/portal/siparisler");
    expect(table).toHaveTextContent("SS-2026-00007");
    expect(table).toHaveTextContent("1 / 2 KOLI");
    expect(await screen.findByTestId("portal-firm")).toHaveTextContent("Zincir Market A.Ş.");
    expect(screen.getByRole("link", { name: "Sevkiyatlar" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Teslimatlarım" })).toBeNull();
    expect(screen.queryByText("Görevlerim")).toBeNull();
    expect(workflowApi.fetchUnreadCount).not.toHaveBeenCalled();
  });

  it("çalışan sayfalarına giderse portala döner", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(portalUser("customer"));
    const { router } = renderApp("/sevkiyat/siparisler");
    await screen.findByTestId("portal-orders");
    expect(router.state.location.pathname).toBe("/portal/siparisler");
  });

  it("sipariş sayfasında satırlar ve sevkiyatlar; irsaliye indirilir", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(portalUser("customer"));
    renderApp("/portal/siparisler/7");

    const lines = await screen.findByTestId("portal-order-lines");
    expect(lines).toHaveTextContent("BULASIK-750");
    expect(lines).toHaveTextContent("20,00 TRY");
    const shipments = await screen.findByTestId("portal-order-shipments");
    expect(portalApi.listCustomerShipments).toHaveBeenCalledWith({
      sales_order: 7,
      page_size: 100,
    });
    await user.click(within(shipments).getByRole("button", { name: "İrsaliye (PDF)" }));
    await waitFor(() => expect(portalApi.downloadWaybill).toHaveBeenCalledWith(SHIPMENT));
  });

  it("cari hesabında bakiye, vadesi geçen ve ekstre; PDF indirilir", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(portalUser("customer"));
    renderApp("/portal/cari");

    const balance = await screen.findByTestId("portal-balance-TRY");
    expect(balance).toHaveTextContent("1.500,00 TRY (B)");
    expect(balance).toHaveTextContent("Vadesi geçen: 300,00 TRY");
    expect(await screen.findByTestId("portal-statement-TRY")).toHaveTextContent("SV-2026-00021");
    expect(portalApi.fetchBalances).toHaveBeenCalledWith("customer");
    await user.click(screen.getByRole("button", { name: "Ekstre (PDF)" }));
    await waitFor(() =>
      expect(portalApi.downloadStatementPdf).toHaveBeenCalledWith("customer", {
        date_from: undefined,
        date_to: undefined,
      }),
    );
  });

  it("geçici şifreyle giren portal Güvenlik sayfasına gider", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(
      portalUser("customer", { password_change_required: true }),
    );
    vi.mocked(authApi.fetchSecurity).mockResolvedValue({
      otp_enabled: false,
      otp_required: false,
      recovery_codes_remaining: 0,
      field_device: false,
      idle_timeout_seconds: 1800,
      password_help: [],
    });
    const { router } = renderApp("/portal/siparisler");
    await waitFor(() => expect(router.state.location.pathname).toBe("/portal/guvenlik"));
    expect(portalApi.listCustomerOrders).not.toHaveBeenCalled();
  });
});

describe("tedarikçi portalı", () => {
  beforeEach(() => {
    vi.mocked(portalApi.fetchPortalMe).mockResolvedValue({
      kind: "supplier",
      firm_code: "T-LAS",
      firm_name: "LAS Kimya Ltd.",
    });
  });

  it("gönderilmiş siparişleri, notu ve teslim alınan miktarı görür; PDF indirir", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(portalUser("supplier"));
    renderApp("/portal/siparisler/9");

    const lines = await screen.findByTestId("portal-supplier-order-lines");
    expect(lines).toHaveTextContent("HM-LAS");
    expect(lines).toHaveTextContent("40 KG");
    expect(lines).toHaveTextContent("60 KG");
    expect(screen.getByText("Analiz sertifikası ekleyin")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Teslimatlarım" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Sevkiyatlar" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Sipariş (PDF)" }));
    await waitFor(() =>
      expect(portalApi.downloadSupplierOrder).toHaveBeenCalledWith(SUPPLIER_ORDER),
    );
  });

  it("teslimatlarını görür; müşteri sayfası siparişlere döner", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(portalUser("supplier"));
    const { router } = renderApp("/portal/teslimatlar/4");
    expect(await screen.findByTestId("portal-receipt-lines")).toHaveTextContent("TL-55");

    router.navigate("/portal/sevkiyatlar");
    await screen.findByTestId("portal-supplier-orders");
    expect(router.state.location.pathname).toBe("/portal/siparisler");
    expect(portalApi.listCustomerShipments).not.toHaveBeenCalled();
  });
});

describe("çalışan ve admin", () => {
  it("çalışan portal adresini açamaz", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("sevkiyat"));
    const { router } = renderApp("/portal/siparisler");
    await waitFor(() => expect(router.state.location.pathname).not.toMatch(/^\/portal/));
    expect(portalApi.listCustomerOrders).not.toHaveBeenCalled();
  });

  it("admin portal hesabı açar; geçici şifre bir kez görünür", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("admin"));
    vi.mocked(portalApi.listPortalAccounts).mockResolvedValue(page([ACCOUNT]));
    vi.mocked(mdApi.listRecords).mockResolvedValue(
      page([{ id: 5, code: "M-ZINCIR", name: "Zincir Market A.Ş." } as mdApi.Partner]),
    );
    vi.mocked(portalApi.createPortalAccount).mockResolvedValue({
      account: ACCOUNT,
      temporary_password: "Gecici-1234",
    });
    renderApp("/sistem/kullanicilar?tur=portal");

    const table = await screen.findByTestId("portal-accounts");
    expect(table).toHaveTextContent("ali.musteri");
    expect(table).toHaveTextContent("Geçici şifre");
    await user.click(screen.getByRole("button", { name: "Yeni portal hesabı" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("textbox", { name: "Müşteri" }));
    await user.click(await screen.findByRole("option", { name: "M-ZINCIR — Zincir Market A.Ş." }));
    await user.type(within(dialog).getByLabelText(/Kullanıcı adı/), "ali.musteri");
    await user.type(within(dialog).getByLabelText(/Ad soyad/), "Ali Müşteri");
    await user.click(within(dialog).getByRole("button", { name: "Hesabı aç" }));

    expect(await screen.findByTestId("temporary-password")).toHaveTextContent("Gecici-1234");
    expect(portalApi.createPortalAccount).toHaveBeenCalledWith({
      username: "ali.musteri",
      full_name: "Ali Müşteri",
      email: "",
      phone: "",
      customer: 5,
      supplier: null,
    });
  });
});

describe("aydınlatma metni", () => {
  it("giriş yapmadan açılır, taslak uyarısıyla görünür; giriş ekranında bağlantısı var", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockRejectedValue(httpError(401));
    const { router } = renderApp("/login");

    await user.click(
      await screen.findByRole("link", { name: "Kişisel verilerin korunması aydınlatma metni" }),
    );
    expect(router.state.location.pathname).toBe("/aydinlatma");
    expect(
      await screen.findByRole("heading", { name: "Kişisel verilerin korunması aydınlatma metni" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Taslak")).toBeInTheDocument();
  });
});

describe("sipariş talebi", () => {
  it("müşteri talep gönderir; ürün seçilince birim gelir, fiyat görünmez", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(portalUser("customer"));
    vi.mocked(portalApi.createRequest).mockResolvedValue(REQUEST);
    const { router } = renderApp("/portal/talepler/yeni");

    await user.click(await screen.findByRole("textbox", { name: "Ürün" }));
    await user.click(
      await screen.findByRole("option", { name: "BULASIK-750 — Bulaşık deterjanı" }),
    );
    await user.type(screen.getByRole("textbox", { name: "Miktar" }), "2");
    expect(screen.getByRole("textbox", { name: "Birim" })).toHaveValue("Adet");
    await user.click(screen.getByRole("textbox", { name: "Birim" }));
    await user.click(await screen.findByRole("option", { name: "Koli" }));
    await user.type(screen.getByLabelText("Sipariş no'nuz"), "PO-9");
    expect(screen.queryByText(/Birim fiyat|Tutar/)).toBeNull();
    await user.click(screen.getByRole("button", { name: "Talebi gönder" }));

    await waitFor(() =>
      expect(portalApi.createRequest).toHaveBeenCalledWith({
        requested_delivery_date: null,
        customer_po_no: "PO-9",
        delivery_address: "",
        note: "",
        lines: [{ product: 90, quantity: "2", unit: 7 }],
      }),
    );
    await waitFor(() => expect(router.state.location.pathname).toBe("/portal/talepler/11"));
  });

  it("Taleplerim listelenir; karar bekleyen talep geri çekilir", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(portalUser("customer"));
    vi.mocked(portalApi.withdrawRequest).mockResolvedValue({
      ...REQUEST,
      status: "WITHDRAWN",
      status_display: "Geri çekildi",
    });
    renderApp("/portal/talepler");
    expect(await screen.findByTestId("portal-requests")).toHaveTextContent("MT-2026-00011");
    expect(screen.getByRole("link", { name: "Taleplerim" })).toBeInTheDocument();

    await user.click(screen.getByText("MT-2026-00011"));
    await user.click(await screen.findByRole("button", { name: "Talebi geri çek" }));
    await waitFor(() => expect(portalApi.withdrawRequest).toHaveBeenCalledWith(11));
    expect(await screen.findByText("Geri çekildi")).toBeInTheDocument();
  });

  it("reddedilen talepte gerekçe görünür", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(portalUser("customer"));
    vi.mocked(portalApi.getRequest).mockResolvedValue({
      ...REQUEST,
      status: "REJECTED",
      status_display: "Reddedildi",
      reject_reason: "Bu ürünü artık üretmiyoruz",
    });
    renderApp("/portal/talepler/11");
    expect(await screen.findByText("Bu ürünü artık üretmiyoruz")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Talebi geri çek" })).toBeNull();
  });

  it("tedarikçi talep sayfasını açamaz", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(portalUser("supplier"));
    const { router } = renderApp("/portal/talepler");
    await waitFor(() => expect(router.state.location.pathname).toBe("/portal/siparisler"));
    expect(portalApi.listRequests).not.toHaveBeenCalled();
  });

  it("sevkiyat talebi siparişe çevirir ve taslak siparişe gider", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("sevkiyat"));
    vi.mocked(portalApi.convertRequest).mockResolvedValue({
      ...STAFF_REQUEST,
      status: "CONVERTED",
      status_display: "Siparişe çevrildi",
      sales_order: 33,
      order_number: "SS-2026-00033",
    });
    const { router } = renderApp("/sevkiyat/portal-talepleri");
    const table = await screen.findByTestId("portal-requests-staff");
    expect(table).toHaveTextContent("Zincir Market A.Ş.");
    expect(portalApi.listStaffRequests).toHaveBeenCalledWith({
      page_size: 100,
      status: "SUBMITTED",
    });

    await user.click(within(table).getByText("MT-2026-00011"));
    await user.click(await screen.findByRole("button", { name: "Siparişe çevir" }));
    await waitFor(() => expect(portalApi.convertRequest).toHaveBeenCalledWith(11));
    await waitFor(() => expect(router.state.location.pathname).toBe("/sevkiyat/siparisler/33"));
  });

  it("gerekçeyle reddeder; Değiştirir'i olmayan karar düğmelerini görmez", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("sevkiyat"));
    vi.mocked(portalApi.rejectRequest).mockResolvedValue({
      ...STAFF_REQUEST,
      status: "REJECTED",
      status_display: "Reddedildi",
      reject_reason: "Mükerrer",
    });
    renderApp("/sevkiyat/portal-talepleri/11");
    await user.click(await screen.findByRole("button", { name: "Reddet" }));
    const dialog = await screen.findByRole("dialog");
    const confirm = within(dialog).getByRole("button", { name: "Reddet" });
    expect(confirm).toBeDisabled();
    await user.type(within(dialog).getByLabelText(/Gerekçe/), "Mükerrer");
    await user.click(confirm);
    await waitFor(() => expect(portalApi.rejectRequest).toHaveBeenCalledWith(11, "Mükerrer"));
  });

  it("planlama talepleri görür ama karar veremez", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("planlama"));
    renderApp("/sevkiyat/portal-talepleri/11");
    expect(await screen.findByTestId("portal-request-staff-lines")).toHaveTextContent("KOLI");
    expect(screen.queryByRole("button", { name: "Siparişe çevir" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Reddet" })).toBeNull();
  });
});

describe("e-posta tercihi", () => {
  const SECURITY = {
    otp_enabled: false,
    otp_required: false,
    recovery_codes_remaining: 0,
    field_device: false,
    idle_timeout_seconds: 1800,
    password_help: [],
  };

  it("müşteri Güvenlik sayfasında e-postaları kapatır", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(portalUser("customer"));
    vi.mocked(authApi.fetchSecurity).mockResolvedValue(SECURITY);
    vi.mocked(portalApi.fetchEmailPreference).mockResolvedValue({
      email: "yetkili@musteri.ornek",
      enabled: true,
    });
    vi.mocked(portalApi.setEmailPreference).mockResolvedValue({
      email: "yetkili@musteri.ornek",
      enabled: false,
    });
    renderApp("/portal/guvenlik");
    expect(await screen.findByText("yetkili@musteri.ornek")).toBeInTheDocument();
    const toggle = screen.getByRole("switch", { name: "Sipariş ve sevk e-postalarını al" });
    expect(toggle).toBeChecked();
    await user.click(toggle);
    await waitFor(() => expect(portalApi.setEmailPreference).toHaveBeenCalled());
    expect(vi.mocked(portalApi.setEmailPreference).mock.calls[0]?.[0]).toBe(false);
    await waitFor(() => expect(toggle).not.toBeChecked());
  });

  it("e-postası olmayan hesapta uyarı görünür, düğme kapalı", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(portalUser("customer"));
    vi.mocked(authApi.fetchSecurity).mockResolvedValue(SECURITY);
    vi.mocked(portalApi.fetchEmailPreference).mockResolvedValue({ email: "", enabled: true });
    renderApp("/portal/guvenlik");
    expect(await screen.findByText(/e-posta adresi tanımlı değil/)).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "Sipariş ve sevk e-postalarını al" })).toBeDisabled();
  });

  it("tedarikçide e-posta tercihi yok", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(portalUser("supplier"));
    vi.mocked(authApi.fetchSecurity).mockResolvedValue(SECURITY);
    renderApp("/portal/guvenlik");
    expect(await screen.findByRole("heading", { name: "Güvenlik" })).toBeInTheDocument();
    expect(screen.queryByText("E-posta bildirimleri")).toBeNull();
    expect(portalApi.fetchEmailPreference).not.toHaveBeenCalled();
  });
});
