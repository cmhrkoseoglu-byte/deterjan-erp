import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as authApi from "../../api/auth";
import * as inventoryApi from "../../api/inventory";
import type { LotDetail } from "../../api/inventory";
import * as traceApi from "../../api/traceability";
import type { BackwardNode, ForwardNode, RecallResult } from "../../api/traceability";
import * as workflowApi from "../../api/workflow";
import { page, userWith } from "../../test/fixtures";
import { renderApp } from "../../test/render";

vi.mock("../../api/auth");
vi.mock("../../api/traceability", async (importOriginal) => ({
  ...(await importOriginal<typeof traceApi>()),
  getBackwardTrace: vi.fn(),
  getForwardTrace: vi.fn(),
  getRecall: vi.fn(),
}));
vi.mock("../../api/inventory", async (importOriginal) => ({
  ...(await importOriginal<typeof inventoryApi>()),
  listLots: vi.fn(),
  getLot: vi.fn(),
}));
vi.mock("../../api/workflow");

const base = {
  status: "RELEASED" as const,
  status_display: "Serbest",
  lot_source: "PURCHASE" as const,
  lot_source_display: "Satın alma",
  material_type: "RAW" as const,
  unit: "KG",
  expiry_date: null,
};

function backward(): BackwardNode {
  const extra = {
    manufactured_at: null,
    supplier_id: null,
    supplier_code: null,
    supplier_name: null,
    supplier_lot_no: "",
    receipt_id: null,
    receipt_number: null,
    receipt_date: null,
  };
  return {
    ...base,
    ...extra,
    id: 30,
    lot_no: "D-261017-001",
    material_id: 60,
    material_code: "MM-750",
    material_name: "Bulaşık deterjanı",
    quantity: null,
    quantity_unit: null,
    children: [
      {
        ...base,
        ...extra,
        id: 7,
        lot_no: "H-261015-001",
        material_id: 50,
        material_code: "LABSA",
        material_name: "Lineer alkil benzen",
        quantity: "120.0000",
        quantity_unit: "KG",
        supplier_id: 3,
        supplier_code: "T001",
        supplier_name: "Kimya A.Ş.",
        supplier_lot_no: "TL-55",
        receipt_id: 4,
        receipt_number: "MK-2026-00001",
        receipt_date: "2026-10-15",
        children: [],
      },
    ],
  };
}

function forward(): ForwardNode {
  return {
    ...base,
    id: 7,
    lot_no: "H-261015-001",
    material_id: 50,
    material_code: "LABSA",
    material_name: "Lineer alkil benzen",
    quantity: null,
    quantity_unit: null,
    on_hand: "880.0000",
    shipped: "0.0000",
    returned: "0.0000",
    shipments: [],
    children: [
      {
        ...base,
        id: 30,
        lot_no: "D-261017-001",
        material_id: 60,
        material_code: "MM-750",
        material_name: "Bulaşık deterjanı",
        material_type: "FINISHED",
        unit: "ADET",
        // Mamule giden miktar girdinin (LABSA) biriminde: 120 KG, 120 ADET değil.
        quantity: "120.0000",
        quantity_unit: "KG",
        on_hand: "55.0000",
        shipped: "30.0000",
        returned: "5.0000",
        shipments: [],
        children: [],
      },
    ],
  };
}

function recall(): RecallResult {
  return {
    selected: [7],
    lots: [
      {
        id: 7,
        lot_no: "H-261015-001",
        status: "RELEASED",
        status_display: "Serbest",
        material_id: 50,
        material_code: "LABSA",
        material_name: "Lineer alkil benzen",
        material_type: "RAW",
        unit: "KG",
        expiry_date: null,
        is_selected: true,
        on_hand: "880.0000",
        shipped: "0.0000",
        returned: "0.0000",
      },
    ],
    stock: [],
    shipments: [],
    customers: [
      {
        customer_id: null,
        customer_code: null,
        customer_name: null,
        material_id: 60,
        material_code: "MM-750",
        material_name: "Bulaşık deterjanı",
        unit: "ADET",
        quantity: "30.0000",
        lots: ["D-261017-001"],
        documents: ["SV-2026-00001"],
      },
    ],
    summary: {
      lot_count: 2,
      finished_lot_count: 1,
      lots_in_stock: 2,
      shipped_lot_count: 1,
      shipment_count: 1,
      customer_count: 0,
    },
  };
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(authApi.fetchCsrf).mockResolvedValue();
  vi.mocked(workflowApi.fetchTasks).mockResolvedValue(page([]));
  vi.mocked(workflowApi.fetchNotifications).mockResolvedValue(page([]));
  vi.mocked(workflowApi.fetchUnreadCount).mockResolvedValue(0);
  vi.mocked(inventoryApi.listLots).mockResolvedValue(page([]));
  vi.mocked(inventoryApi.getLot).mockResolvedValue({
    id: 7,
    lot_no: "H-261015-001",
    material_code: "LABSA",
    material_name: "Lineer alkil benzen",
  } as LotDetail);
  vi.mocked(traceApi.getBackwardTrace).mockResolvedValue(backward());
  vi.mocked(traceApi.getForwardTrace).mockResolvedValue(forward());
  vi.mocked(traceApi.getRecall).mockResolvedValue(recall());
});

describe("izlenebilirlik", () => {
  it("geri izleme tedarikçi ve mal kabule kadar iner", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("laboratuvar"));
    renderApp("/izlenebilirlik/geri?lot=30");
    expect(await screen.findByText("Kimya A.Ş.")).toBeInTheDocument();
    expect(screen.getByText("TL-55")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /MK-2026-00001/ })).toHaveAttribute(
      "href",
      "/depo/mal-kabul/4",
    );
    expect(traceApi.getBackwardTrace).toHaveBeenCalledWith(30);
  });

  it("ileri izleme stok, sevk ve iade miktarlarını gösterir", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("yonetim"));
    renderApp("/izlenebilirlik/ileri?lot=7");
    expect(await screen.findByText("D-261017-001")).toBeInTheDocument();
    const rows = screen.getAllByTestId("trace-row");
    expect(rows[1]).toHaveTextContent("120 KG");
    expect(rows[1]).not.toHaveTextContent("120 ADET");
    expect(rows[1]).toHaveTextContent("Stokta: 55 ADET");
    expect(rows[1]).toHaveTextContent("Sevk: 30 ADET");
    expect(rows[1]).toHaveTextContent("İade: 5 ADET");
  });

  it("geri çağırma simülasyonu özet, müşteri ve çıktı bağlantılarını gösterir", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("laboratuvar"));
    renderApp("/izlenebilirlik/geri-cagirma?lot=7");
    expect(await screen.findByText("Müşteri bilgisi yok")).toBeInTheDocument();
    expect(traceApi.getRecall).toHaveBeenCalledWith([7]);
    expect(screen.getByRole("link", { name: "Excel" })).toHaveAttribute(
      "href",
      "/api/v1/traceability/recall/xlsx/?lot=7",
    );
    expect(screen.getByRole("link", { name: "PDF" })).toHaveAttribute(
      "href",
      "/api/v1/traceability/recall/pdf/?lot=7",
    );
    expect(screen.getAllByTestId("recall-summary")[0]).toHaveTextContent("Etkilenen lot2");
  });

  it("sekme değişince seçili lot korunur", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("laboratuvar"));
    renderApp("/izlenebilirlik/geri?lot=30");
    await screen.findByText("Kimya A.Ş.");
    await userEvent.click(screen.getByRole("tab", { name: "İleri izleme" }));
    await waitFor(() => expect(traceApi.getForwardTrace).toHaveBeenCalledWith(30));
  });

  it("depo rolü izlenebilirlik ekranını göremez", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("depo"));
    renderApp("/izlenebilirlik");
    expect(await screen.findByText("Yetkiniz yok")).toBeInTheDocument();
  });
});
