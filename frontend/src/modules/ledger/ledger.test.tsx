import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as authApi from "../../api/auth";
import * as ledgerApi from "../../api/ledger";
import type { LedgerEntry, PartnerRow, Statement } from "../../api/ledger";
import * as workflowApi from "../../api/workflow";
import { page, userWith } from "../../test/fixtures";
import { renderApp } from "../../test/render";

vi.mock("../../api/auth");
vi.mock("../../api/workflow");
vi.mock("../../api/ledger", async (importOriginal) => ({
  ...(await importOriginal<typeof ledgerApi>()),
  listPartners: vi.fn(),
  getPartnerSummary: vi.fn(),
  getStatement: vi.fn(),
  listMissingPrices: vi.fn(),
  postEntry: vi.fn(),
  reverseEntry: vi.fn(),
  setShipmentLinePrice: vi.fn(),
  getReturnSuggestion: vi.fn(),
  downloadPartners: vi.fn(),
  downloadStatement: vi.fn(),
}));

const partner = {
  id: 7,
  code: "MUS-000001",
  name: "Ak Market",
  payment_term_days: 30,
  vat_exempt: false,
  is_active: true,
};

const aging = {
  not_due: "200.00",
  d1_30: "300.00",
  d31_60: "0.00",
  d61_90: "0.00",
  d90_plus: "0.00",
};

function row(amounts = true): PartnerRow {
  return {
    partner,
    balances: [
      amounts
        ? {
            currency: "TRY",
            last_date: "2026-11-16",
            debit: "1700.00",
            credit: "1200.00",
            balance: "500.00",
            overdue: "300.00",
            aging,
          }
        : { currency: "TRY", last_date: "2026-11-16" },
    ],
    missing: 1,
  };
}

function entry(overrides: Partial<LedgerEntry> = {}): LedgerEntry {
  return {
    id: 31,
    number: "CH-2026-00004",
    entry_date: "2026-11-16",
    kind: "COLLECTION",
    kind_display: "Tahsilat",
    currency: "TRY",
    debit: "0.00",
    credit: "1200.00",
    net_amount: null,
    vat_amount: null,
    exchange_rate: null,
    method: "TRANSFER",
    method_display: "Havale / EFT",
    reference: "",
    description: "",
    shipment: null,
    shipment_number: null,
    goods_receipt: null,
    goods_receipt_number: null,
    customer_return: null,
    customer_return_number: null,
    reversal_of: null,
    reversal_of_number: null,
    created_by_name: "Yönetim",
    created_at: "2026-11-16T10:00:00+03:00",
    ...overrides,
  };
}

function statement(): Statement {
  return {
    partner,
    date_from: null,
    date_to: null,
    currencies: [
      {
        currency: "TRY",
        opening: "0.00",
        rows: [
          {
            entry: entry({
              id: 30,
              number: "CH-2026-00001",
              kind: "SALE",
              kind_display: "Satış (sevkiyat)",
              debit: "1700.00",
              credit: "0.00",
              method: "",
              method_display: "",
              shipment: 5,
              shipment_number: "SV-2026-00003",
            }),
            balance: "1700.00",
            due_date: "2026-12-16",
            is_reversed: false,
          },
          { entry: entry(), balance: "500.00", due_date: null, is_reversed: false },
        ],
        total_debit: "1700.00",
        total_credit: "1200.00",
        closing: "500.00",
      },
    ],
    returns: [],
  };
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(authApi.fetchCsrf).mockResolvedValue();
  vi.mocked(workflowApi.fetchTasks).mockResolvedValue(page([]));
  vi.mocked(workflowApi.fetchNotifications).mockResolvedValue(page([]));
  vi.mocked(workflowApi.fetchUnreadCount).mockResolvedValue(0);
  vi.mocked(ledgerApi.listPartners).mockResolvedValue({
    ...page([row()]),
    totals: [{ currency: "TRY", open: "500.00", advance: "0.00", overdue: "300.00" }],
  });
  vi.mocked(ledgerApi.getPartnerSummary).mockResolvedValue({
    partner,
    balances: row().balances,
    missing: 1,
  });
  vi.mocked(ledgerApi.getStatement).mockResolvedValue(statement());
  vi.mocked(ledgerApi.listMissingPrices).mockResolvedValue([
    {
      kind: "shipment",
      line_id: 44,
      document_id: 6,
      document_number: "SV-2026-00006",
      document_date: "2026-11-17",
      partner,
      material_code: "MM-750",
      material_name: "Bulaşık deterjanı 750 ml",
      quantity: "3.0000",
      unit_code: "KOLI",
    },
  ]);
});

describe("cari listesi", () => {
  it("yönetim iki sekmeyi, bakiyeyi ve vadesi geçeni görür", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("yonetim"));
    renderApp("/cari-hesaplar");

    expect(await screen.findByRole("tab", { name: "Müşteriler" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Tedarikçiler" })).toBeInTheDocument();
    const line = (await screen.findByText("Ak Market")).closest("tr")!;
    expect(within(line).getByText("500,00 TRY (B)")).toBeInTheDocument();
    expect(within(line).getByText("300,00 TRY")).toBeInTheDocument();
    expect(within(line).getByText("1 belge")).toBeInTheDocument();
    expect(screen.getByText("Toplam alacağımız")).toBeInTheDocument();
    // Dönem notu yalnız tedarikçilerde (DECISIONS 2026-11-20).
    expect(screen.queryByText(/20 Kasım 2026 itibarıyla/)).not.toBeInTheDocument();
    expect(ledgerApi.listPartners).toHaveBeenCalledWith(
      "customers",
      expect.objectContaining({ page: 1 }),
    );
  });

  it("sevkiyat yalnız müşteri sekmesini görür, tutar görmez", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("sevkiyat"));
    vi.mocked(ledgerApi.listPartners).mockResolvedValue(page([row(false)]));
    renderApp("/cari-hesaplar");

    expect(await screen.findByText("Ak Market")).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Tedarikçiler" })).not.toBeInTheDocument();
    expect(screen.getByText(/Tutarları görme yetkiniz yok/)).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Bakiye" })).not.toBeInTheDocument();
  });

  it("satın alma tedarikçi sekmesine düşer", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("satin_alma"));
    renderApp("/cari-hesaplar");

    expect(await screen.findByRole("tab", { name: "Tedarikçiler" })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Müşteriler" })).not.toBeInTheDocument();
    await waitFor(() =>
      expect(ledgerApi.listPartners).toHaveBeenCalledWith("suppliers", expect.anything()),
    );
    expect(
      screen.getByText(/Cari bakiyeler 20 Kasım 2026 itibarıyla sıfırdan başlatılmıştır/),
    ).toBeInTheDocument();
  });

  it("planlama cari hesapları göremez", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("planlama"));
    renderApp("/cari-hesaplar");

    expect(await screen.findByText("Yetkiniz yok")).toBeInTheDocument();
  });
});

describe("cari ekstresi", () => {
  it("ekstre, yaşlandırma ve tahsilat girişi", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("yonetim"));
    vi.mocked(ledgerApi.postEntry).mockResolvedValue(entry({ number: "CH-2026-00009" }));
    renderApp("/cari-hesaplar/musteriler/7");

    expect(
      await screen.findByRole("heading", { name: "MUS-000001 — Ak Market" }),
    ).toBeInTheDocument();
    expect(await screen.findByText("SV-2026-00003")).toBeInTheDocument();
    expect(screen.getByText("1-30 gün")).toBeInTheDocument();
    expect(screen.getByText("Fiyatı eksik belgeler")).toBeInTheDocument();
    // Sevkiyat kaydı iptal edilemez; tahsilat edilebilir.
    const sale = screen.getByText("CH-2026-00001").closest("tr")!;
    expect(within(sale).queryByRole("button", { name: "İptal et" })).not.toBeInTheDocument();
    const collection = screen.getByText("CH-2026-00004").closest("tr")!;
    expect(within(collection).getByRole("button", { name: "İptal et" })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Tahsilat gir" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByRole("textbox", { name: /Tutar/ }), "1.250,50");
    await userEvent.click(within(dialog).getByRole("button", { name: "Kaydet" }));

    await waitFor(() =>
      expect(ledgerApi.postEntry).toHaveBeenCalledWith(
        "customers",
        7,
        expect.objectContaining({
          kind: "COLLECTION",
          amount: "1250.50",
          currency: "TRY",
          method: "TRANSFER",
          direction: null,
        }),
      ),
    );
  });

  it("iptal gerekçeyle ters kayıt ister", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("yonetim"));
    vi.mocked(ledgerApi.reverseEntry).mockResolvedValue(entry({ kind: "REVERSAL" }));
    renderApp("/cari-hesaplar/musteriler/7");

    const collection = (await screen.findByText("CH-2026-00004")).closest("tr")!;
    await userEvent.click(within(collection).getByRole("button", { name: "İptal et" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByRole("textbox", { name: /İptal nedeni/ }), "Hata");
    await userEvent.click(within(dialog).getByRole("button", { name: "İptal et" }));

    await waitFor(() =>
      expect(ledgerApi.reverseEntry).toHaveBeenCalledWith("customers", 7, 31, "Hata"),
    );
  });

  it("fiyatı eksik sevkiyat satırına fiyat girilir", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("yonetim"));
    vi.mocked(ledgerApi.setShipmentLinePrice).mockResolvedValue([]);
    renderApp("/cari-hesaplar/musteriler/7");

    await userEvent.click(await screen.findByRole("button", { name: "Fiyat gir" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByRole("textbox", { name: /Birim fiyat/ }), "120");
    await userEvent.click(within(dialog).getByRole("button", { name: "Kaydet" }));

    await waitFor(() =>
      expect(ledgerApi.setShipmentLinePrice).toHaveBeenCalledWith({
        line: 44,
        unit_price: "120",
        currency: "TRY",
        note: "",
      }),
    );
  });

  it("sevkiyat ekstreyi tutarsız görür, kayıt giremez", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("sevkiyat"));
    renderApp("/cari-hesaplar/musteriler/7");

    expect(await screen.findByText("CH-2026-00004")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Tahsilat gir" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /PDF/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Fiyat gir" })).not.toBeInTheDocument();
  });

  it("sevkiyat tedarikçi ekstresini açamaz", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("sevkiyat"));
    renderApp("/cari-hesaplar/tedarikciler/7");

    expect(await screen.findByText("Yetkiniz yok")).toBeInTheDocument();
  });

  it("tedarikçi ekstresinde dönem notu görünür", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("satin_alma"));
    renderApp("/cari-hesaplar/tedarikciler/7");

    expect(await screen.findByRole("heading", { name: /Ak Market/ })).toBeInTheDocument();
    expect(screen.getByText(/önceki dönem kapatılmıştır/)).toBeInTheDocument();
  });
});
