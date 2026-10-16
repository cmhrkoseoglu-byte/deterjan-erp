import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as authApi from "../../api/auth";
import * as inventoryApi from "../../api/inventory";
import * as mdApi from "../../api/masterdata";
import * as returnsApi from "../../api/returns";
import type { CustomerReturnDetail } from "../../api/returns";
import * as workflowApi from "../../api/workflow";
import { page, userWith } from "../../test/fixtures";
import { renderApp } from "../../test/render";
import { recordPath } from "../../workflow/recordLinks";

vi.mock("../../api/auth");
vi.mock("../../api/returns", async (importOriginal) => ({
  ...(await importOriginal<typeof returnsApi>()),
  listReturns: vi.fn(),
  getReturn: vi.fn(),
  saveReturn: vi.fn(),
  receiveReturn: vi.fn(),
  scrapReturnLine: vi.fn(),
}));
vi.mock("../../api/inventory", async (importOriginal) => ({
  ...(await importOriginal<typeof inventoryApi>()),
  listLots: vi.fn(),
}));
vi.mock("../../api/masterdata", async (importOriginal) => ({
  ...(await importOriginal<typeof mdApi>()),
  listRecords: vi.fn(),
}));
vi.mock("../../api/workflow");

function doc(overrides: Partial<CustomerReturnDetail> = {}): CustomerReturnDetail {
  return {
    id: 4,
    number: "IA-2026-00001",
    status: "RECEIVED",
    status_display: "Teslim alındı",
    cancel_reason: "",
    cancelled_at: null,
    received_at: "2026-10-16T09:00:00+03:00",
    received_by_name: "Sevkiyat",
    closed_at: null,
    created_at: "2026-10-16T08:00:00+03:00",
    created_by_name: "Sevkiyat",
    customer: 3,
    customer_code: "M001",
    customer_name: "Zincir Market A.Ş.",
    return_date: "2026-10-16",
    reason: "Kapak sızdırıyor",
    quarantine_location: 2,
    quarantine_location_code: "IADE-KRNT",
    note: "",
    line_count: 1,
    lines: [
      {
        id: 11,
        line_no: 1,
        product: 60,
        product_code: "MM-750",
        product_name: "Bulaşık deterjanı 750 ml",
        lot: 30,
        lot_no: "D-261017-001",
        lot_status: "REJECTED",
        lot_status_display: "Reddedildi",
        expiry_date: "2028-10-17",
        quantity: "12.0000",
        unit: 1,
        unit_code: "ADET",
        base_quantity: "12.0000",
        base_unit_code: "ADET",
        sample: 31,
        sample_number: "NM-2026-00009",
        sample_status: "DECIDED",
        disposition: "SCRAP",
        disposition_display: "İmha",
        decided_at: "2026-10-16T10:00:00+03:00",
        is_scrapped: false,
        is_settled: false,
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
  vi.mocked(inventoryApi.listLots).mockResolvedValue(page([]));
  vi.mocked(returnsApi.listReturns).mockResolvedValue(page([doc()]));
  vi.mocked(returnsApi.getReturn).mockResolvedValue(doc());
});

describe("iade listesi", () => {
  it("sevkiyat yeni iade açabilir ve satıra tıklayınca detaya gider", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("sevkiyat"));
    renderApp("/iadeler");
    expect(await screen.findByRole("button", { name: "Yeni iade" })).toBeInTheDocument();
    await userEvent.click(await screen.findByText("IA-2026-00001"));
    expect(await screen.findByRole("heading", { name: "İade IA-2026-00001" })).toBeInTheDocument();
  });

  it("laboratuvar listeyi görür ama iade açamaz", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("laboratuvar"));
    renderApp("/iadeler");
    expect(await screen.findByText("Zincir Market A.Ş.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Yeni iade" })).not.toBeInTheDocument();
  });

  it("üretim rolü iadeleri göremez", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("uretim"));
    renderApp("/iadeler");
    expect(await screen.findByText("Yetkiniz yok")).toBeInTheDocument();
  });
});

describe("iade detayı", () => {
  it("imha kararı verilen satırı depo imha eder", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("depo"));
    const scrapped = doc({
      status: "CLOSED",
      lines: [{ ...doc().lines[0], is_scrapped: true, is_settled: true }],
    });
    vi.mocked(returnsApi.scrapReturnLine).mockImplementation(async () => {
      vi.mocked(returnsApi.getReturn).mockResolvedValue(scrapped);
      return scrapped;
    });
    renderApp("/iadeler/4");
    const row = (await screen.findByText("D-261017-001")).closest("tr")!;
    expect(within(row).getByText("İmha")).toBeInTheDocument();
    expect(within(row).getByRole("link", { name: "NM-2026-00009" })).toHaveAttribute(
      "href",
      "/kalite/numuneler/31",
    );
    await userEvent.click(within(row).getByRole("button", { name: "İmha et" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText("Not"), "Atık firmasına verildi");
    await userEvent.click(within(dialog).getByRole("button", { name: "İmha et" }));
    await waitFor(() =>
      expect(returnsApi.scrapReturnLine).toHaveBeenCalledWith(4, 11, "Atık firmasına verildi"),
    );
    expect(await screen.findByText("İmha edildi")).toBeInTheDocument();
  });

  it("laboratuvar imha düğmesini görmez", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("laboratuvar"));
    renderApp("/iadeler/4");
    await screen.findByText("D-261017-001");
    expect(screen.queryByRole("button", { name: "İmha et" })).not.toBeInTheDocument();
  });

  it("taslak iade onayla teslim alınır", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("sevkiyat"));
    const draft = doc({
      status: "DRAFT",
      received_at: null,
      lines: [{ ...doc().lines[0], disposition: "PENDING", sample: null, sample_number: null }],
    });
    vi.mocked(returnsApi.getReturn).mockResolvedValue(draft);
    vi.mocked(returnsApi.saveReturn).mockResolvedValue(draft);
    vi.mocked(returnsApi.receiveReturn).mockResolvedValue(doc({ lines: draft.lines }));
    renderApp("/iadeler/4");
    await userEvent.click(await screen.findByRole("button", { name: "Teslim al" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Teslim al" }));
    await waitFor(() => expect(returnsApi.receiveReturn).toHaveBeenCalledWith(4));
    expect(returnsApi.saveReturn).toHaveBeenCalledWith(
      4,
      expect.objectContaining({
        reason: "Kapak sızdırıyor",
        lines: [{ id: 11, product: 60, lot: 30, quantity: "12", unit: 1 }],
      }),
    );
  });

  it("görev bağlantısı iade sayfasına gider", () => {
    expect(recordPath({ model: "returns.customerreturn", id: 4, repr: "IA" })).toBe("/iadeler/4");
  });
});
