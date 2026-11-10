import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as attachmentsApi from "../../api/attachments";
import * as authApi from "../../api/auth";
import * as inventoryApi from "../../api/inventory";
import type { GoodsReceiptDetail, LotDetail, TraceNode } from "../../api/inventory";
import * as labelsApi from "../../api/labels";
import * as mdApi from "../../api/masterdata";
import * as qualityApi from "../../api/quality";
import * as workflowApi from "../../api/workflow";
import { page, userWith } from "../../test/fixtures";
import { renderApp } from "../../test/render";
import { recordPath } from "../../workflow/recordLinks";

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
  createPallet: vi.fn(),
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
  releaseLot: vi.fn(),
  getGoodsReceipt: vi.fn(),
  saveGoodsReceipt: vi.fn(),
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

function lot(overrides: Partial<LotDetail> = {}): LotDetail {
  return {
    id: 7,
    lot_no: "H-261015-001",
    material: 50,
    material_code: "LABSA",
    material_name: "Lineer alkil benzen sülfonik asit",
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
    balances: [
      {
        location: 2,
        location_code: "KAR-01",
        location_name: "Karantina",
        location_type: "QUARANTINE",
        quantity: "1000.0000",
      },
    ],
    receipt: { model: "inventory.goodsreceipt", id: 4, number: "MK-2026-00001" },
    ...overrides,
  };
}

function trace(): TraceNode {
  const node = (id: number, lotNo: string, children: TraceNode[] = []): TraceNode => ({
    id,
    lot_no: lotNo,
    status: "RELEASED",
    status_display: "Serbest",
    lot_source: "PRODUCTION",
    lot_source_display: "Üretim",
    material_id: 80,
    material_code: "BULK-1",
    material_name: "Bulaşık bulk",
    material_type: "BULK",
    unit: "KG",
    expiry_date: null,
    quantity: id === 7 ? null : "250.0000",
    quantity_unit: id === 7 ? null : "KG",
    children,
  });
  return node(7, "H-261015-001", [node(20, "B-261016-001", [node(30, "D-261017-001")])]);
}

const locations = [
  { id: 2, code: "KAR-01", name: "Karantina", location_type: "QUARANTINE", is_active: true },
  { id: 5, code: "HM-01", name: "Hammadde rafı", location_type: "STORAGE", is_active: true },
];

beforeEach(() => {
  vi.mocked(attachmentsApi.listAttachments).mockResolvedValue([]);
  vi.mocked(labelsApi.listPrinters).mockResolvedValue([]);
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
  vi.resetAllMocks();
  vi.mocked(authApi.fetchCsrf).mockResolvedValue();
  vi.mocked(workflowApi.fetchTasks).mockResolvedValue(page([]));
  vi.mocked(workflowApi.fetchNotifications).mockResolvedValue(page([]));
  vi.mocked(workflowApi.fetchUnreadCount).mockResolvedValue(0);
  vi.mocked(workflowApi.fetchComments).mockResolvedValue([]);
  vi.mocked(workflowApi.fetchRecordHistory).mockResolvedValue([]);
  vi.mocked(mdApi.listRecords).mockImplementation(async (endpoint) =>
    endpoint === "locations" ? page(locations) : page([]),
  );
  vi.mocked(inventoryApi.listLots).mockResolvedValue(page([]));
  vi.mocked(inventoryApi.listBalances).mockResolvedValue(page([]));
  vi.mocked(inventoryApi.listGoodsReceipts).mockResolvedValue(page([]));
  vi.mocked(inventoryApi.listAdjustments).mockResolvedValue(page([]));
  vi.mocked(inventoryApi.listMovements).mockResolvedValue(page([]));
  vi.mocked(inventoryApi.getLotTrace).mockResolvedValue(trace());
  vi.mocked(qualityApi.listSamples).mockResolvedValue(page([]));
});

describe("depo sekmeleri", () => {
  it("üretim rolü yalnızca stok sorgu ve lotları görür", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("uretim"));
    renderApp("/depo");
    const tabs = await screen.findAllByRole("tab");
    expect(tabs.map((tab) => tab.textContent)).toEqual(["Stok sorgu", "Lotlar"]);
    expect(screen.queryByText("Açılış stoku içe aktar")).not.toBeInTheDocument();
  });

  it("laboratuvarın lot onay sekmesi yoktur; karar kalite modülündedir", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("laboratuvar"));
    renderApp("/depo");
    expect(await screen.findByRole("tab", { name: "Stok sorgu" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.queryByRole("tab", { name: "Lot onay" })).not.toBeInTheDocument();
  });

  it("rolün göremediği sekmenin adresi varsayılan sekmeye döner", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("uretim"));
    const { router } = renderApp("/depo/sayim");
    await waitFor(() => expect(router.state.location.pathname).toBe("/depo"));
    expect(await screen.findByRole("tab", { name: "Stok sorgu" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("depo rolü mal kabul ve sayım sekmelerini ve açılış stokunu görür", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("depo"));
    renderApp("/depo/stok");
    expect(await screen.findByText("Açılış stoku içe aktar")).toBeInTheDocument();
    const tabs = screen.getAllByRole("tab").map((tab) => tab.textContent);
    expect(tabs).toEqual(["Stok sorgu", "Lotlar", "Mal kabul", "Sayım düzeltme"]);
  });
});

describe("lot detay", () => {
  it("laboratuvar lotu serbest bırakamaz; numunelerini görür ve bloke edebilir", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("laboratuvar"));
    vi.mocked(inventoryApi.getLot).mockResolvedValue(lot());
    vi.mocked(qualityApi.listSamples).mockResolvedValue(
      page([
        {
          id: 31,
          number: "NM-2026-00001",
          status: "IN_TEST",
          status_display: "Testte",
          lot: 7,
          lot_no: "H-261015-001",
          lot_status: "QUARANTINE",
          material: 50,
          material_code: "LABSA",
          material_name: "Lineer alkil benzen sülfonik asit",
          material_type: "RAW",
          stage: "INCOMING",
          stage_display: "Giriş kontrolü",
          origin: "GOODS_RECEIPT",
          origin_display: "Mal kabul",
          specification: 2,
          specification_label: "v1",
          taken_by: null,
          taken_by_name: null,
          taken_at: "2026-10-15T10:00:00+03:00",
          retain_location: null,
          retain_location_code: null,
          note: "",
          decided_at: null,
          created_by_name: null,
          created_at: "2026-10-15T10:00:00+03:00",
          waiting_minutes: 30,
        },
      ]),
    );
    renderApp("/depo/lotlar/7");

    expect(await screen.findByRole("heading", { name: "H-261015-001" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "MK-2026-00001" })).toHaveAttribute(
      "href",
      "/depo/mal-kabul/4",
    );
    expect(await screen.findByRole("link", { name: "NM-2026-00001" })).toHaveAttribute(
      "href",
      "/kalite/numuneler/31",
    );
    // Açık numune varken yenisi açılmaz; serbest bırakma ve ret numune kararıyladır.
    expect(screen.queryByRole("button", { name: "Numune aç" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /serbest bırak/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reddet" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Bloke et" })).toBeInTheDocument();
    // Transfer depo işidir; laboratuvar görmez.
    expect(screen.queryByRole("button", { name: "Transfer" })).not.toBeInTheDocument();
  });

  it("admin gerekçeyle elle serbest bırakır (D-5)", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("admin"));
    vi.mocked(inventoryApi.getLot).mockResolvedValue(lot());
    vi.mocked(inventoryApi.releaseLot).mockResolvedValue(lot({ status: "RELEASED" }));
    renderApp("/depo/lotlar/7");

    await user.click(await screen.findByRole("button", { name: "Elle serbest bırak" }));
    const dialog = await screen.findByRole("dialog");
    const submit = within(dialog).getByRole("button", { name: "Serbest bırak" });
    await user.click(within(dialog).getByRole("textbox", { name: /Hedef lokasyon/ }));
    await user.click(await screen.findByRole("option", { name: "HM-01 - Hammadde rafı" }));
    expect(submit).toBeDisabled(); // gerekçe zorunlu
    await user.type(within(dialog).getByRole("textbox", { name: /Neden/ }), "Acil sevkiyat");
    await user.click(submit);
    await waitFor(() =>
      expect(inventoryApi.releaseLot).toHaveBeenCalledWith(7, "Acil sevkiyat", 5),
    );
  });

  it("soy ağacını iç içe gösterir; depo rolü karar veremez ama transfer yapabilir", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("depo"));
    vi.mocked(inventoryApi.getLot).mockResolvedValue(lot({ status: "RELEASED" }));
    renderApp("/depo/lotlar/7");

    const nodes = await screen.findAllByTestId("trace-node");
    expect(nodes.map((node) => within(node).getByRole("link").textContent)).toEqual([
      "B-261016-001",
      "D-261017-001",
    ]);
    expect(screen.getByRole("button", { name: "Transfer" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Serbest bırak" })).not.toBeInTheDocument();
  });
});

describe("lot etiketleri (GS1)", () => {
  const settings: labelsApi.LabelSettings = {
    company_name: "",
    gs1_company_prefix: "8690000",
    sscc_extension_digit: 0,
    next_sscc_serial: 42,
    default_printer: null,
    default_printer_code: null,
    sscc_enabled: true,
    updated_at: "2026-10-15T09:00:00+03:00",
  };
  const finished = (caseGtin: string, gs1Label?: boolean, gtin = "8690000000012") =>
    lot({
      material_type: "FINISHED",
      material_gtin: gtin,
      material_case_gtin: caseGtin,
      status: "RELEASED",
      gs1_label: gs1Label,
    });
  const pallet: labelsApi.PalletLabel = {
    id: 3,
    sscc: "086900000000000417",
    lot: 7,
    lot_no: "D-261015-001",
    material_code: "BULASIK-750",
    material_name: "Bulaşık deterjanı 750 ml",
    case_count: 40,
    units_per_case: 12,
    created_by_name: "Depo",
    created_at: "2026-10-15T12:00:00+03:00",
  };
  /** GS1 barkodu basılamayan lotun sarı uyarısı (palet etiketinde SSCC her zaman basılır). */
  const noGs1 = {
    koli: "Bu lotun koli etiketine GS1 barkodu basılmaz (lot numarası GS1'e uymuyor ya da GTIN geçersiz); firma içi barkod ya da QR kodu basılır.",
    palet:
      "Bu lotun palet etiketine GTIN ve lot için GS1 barkodu basılmaz (lot numarası GS1'e uymuyor ya da GTIN geçersiz); yerine firma içi lot barkodu basılır (Türkçe harfli ya da > içeren lot numarasında basılmaz). Paletin SSCC barkodu her zaman basılır.",
  };

  /** Lotun sayfasını açar ve koli etiketinin ya da paletin etiket penceresini açar (palette SSCC
   * açık, lotun bir paleti var). */
  async function openLabel(detail: LotDetail, kind: "koli" | "palet") {
    if (kind === "palet") {
      vi.mocked(labelsApi.getLabelSettings).mockResolvedValue(settings);
      vi.mocked(labelsApi.listPallets).mockResolvedValue([pallet]);
    }
    vi.mocked(inventoryApi.getLot).mockResolvedValue(detail);
    renderApp("/depo/lotlar/7");
    if (kind === "palet") {
      const row = (await screen.findByText(pallet.sscc)).closest("tr")!;
      await userEvent.click(within(row).getByRole("button", { name: "Etiket yazdır" }));
      return screen.findByRole("dialog", { name: `Palet etiketi (SSCC): ${pallet.sscc}` });
    }
    await userEvent.click(await screen.findByRole("button", { name: "Etiket yazdır" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("textbox", { name: "Etiket" }));
    await userEvent.click(await screen.findByRole("option", { name: "Koli etiketi" }));
    return dialog;
  }

  beforeEach(() => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("depo"));
    vi.mocked(labelsApi.listPrinters).mockResolvedValue([]);
    vi.mocked(labelsApi.getLabelSettings).mockResolvedValue({ ...settings, sscc_enabled: false });
    vi.mocked(labelsApi.listPallets).mockResolvedValue([]);
    vi.mocked(attachmentsApi.listAttachments).mockResolvedValue([]);
  });

  it.each([
    [
      "koli GTIN'i varsa koli GTIN'i basılır",
      "18690000000019",
      "Koli etiketine koli GTIN'i basılır.",
    ],
    [
      "koli GTIN'i yoksa ürün GTIN'i için sarı uyarı verir",
      "",
      "Bu lotun koli GTIN'i yok; koli etiketine ürün GTIN'i basılır.",
    ],
  ])("mamul lotunun koli etiketinde %s", async (_name, caseGtin, text) => {
    vi.mocked(inventoryApi.getLot).mockResolvedValue(finished(caseGtin));
    renderApp("/depo/lotlar/7");

    await userEvent.click(await screen.findByRole("button", { name: "Etiket yazdır" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("textbox", { name: "Etiket" }));
    await userEvent.click(await screen.findByRole("option", { name: "Koli etiketi" }));
    expect(within(dialog).getByText(text)).toBeInTheDocument();
    if (caseGtin) {
      expect(within(dialog).queryByTestId("label-warning")).not.toBeInTheDocument();
    } else {
      const warning = within(dialog).getByTestId("label-warning");
      expect(warning).toHaveTextContent(text);
      expect(alertStyle(warning)).toContain("--mantine-color-yellow-light"); // sarı
    }
    // Koli GTIN'i lot kaydından gelir; etiket penceresi lotu yeniden istemez.
    expect(inventoryApi.getLot).toHaveBeenCalledTimes(1);
  });

  it("palet etiketi koli GTIN'i yoksa ürün GTIN'i basılacağını söyler", async () => {
    vi.mocked(labelsApi.getLabelSettings).mockResolvedValue(settings);
    vi.mocked(labelsApi.listPallets).mockResolvedValue([pallet]);
    vi.mocked(inventoryApi.getLot).mockResolvedValue(finished(""));
    renderApp("/depo/lotlar/7");

    const row = (await screen.findByText("086900000000000417")).closest("tr")!;
    await userEvent.click(within(row).getByRole("button", { name: "Etiket yazdır" }));
    const dialog = await screen.findByRole("dialog", {
      name: "Palet etiketi (SSCC): 086900000000000417",
    });
    const warning = within(dialog).getByTestId("label-warning");
    expect(warning).toHaveTextContent(
      "Bu lotun koli GTIN'i yok; palet etiketine ürün GTIN'i basılır.",
    );
    expect(alertStyle(warning)).toContain("--mantine-color-yellow-light"); // sarı
  });

  /** Koli GTIN'iyle çelişen koli içi adedin sarı uyarısı (12'lik koli). */
  const unitsWarning =
    "Bu lotun koli GTIN'i 12 adetlik koli içindir; farklı adet etikette barkodla çelişir.";

  it("koli etiketinde koli içi adet lotun koli içi miktarıyla gelir; koli GTIN'iyle çelişen adet sarı uyarı verir", async () => {
    const dialog = await openLabel(
      { ...finished("18690000000019"), case_units: "12.000000" },
      "koli",
    );
    const units = within(dialog).getByRole("textbox", { name: "Koli içi adet" });
    const link = () => within(dialog).getByRole("link", { name: "Aç" }).getAttribute("href");
    expect(units).toHaveValue("12");
    expect(link()).toContain("units_per_case=12");
    expect(within(dialog).queryByTestId("units-warning")).not.toBeInTheDocument();

    await userEvent.clear(units);
    await userEvent.type(units, "24");
    const warning = within(dialog).getByTestId("units-warning");
    expect(warning).toHaveTextContent(unitsWarning);
    expect(alertStyle(warning)).toContain("--mantine-color-yellow-light"); // sarı
    // Uyarı basmayı engellemez (eksik son koli): yazılan adet basılır.
    expect(link()).toContain("units_per_case=24");
    // Lotun miktarına dönülünce uyarı kalkar.
    await userEvent.clear(units);
    await userEvent.type(units, "12");
    expect(within(dialog).queryByTestId("units-warning")).not.toBeInTheDocument();

    // Pencere yeniden açılınca yazılan adet unutulur, lotun miktarı gelir.
    await userEvent.clear(units);
    await userEvent.type(units, "24");
    await userEvent.click(within(dialog).getByRole("button", { name: "Vazgeç" }));
    await userEvent.click(screen.getByRole("button", { name: "Etiket yazdır" }));
    const again = await screen.findByRole("dialog");
    await userEvent.click(within(again).getByRole("textbox", { name: "Etiket" }));
    await userEvent.click(await screen.findByRole("option", { name: "Koli etiketi" }));
    expect(within(again).getByRole("textbox", { name: "Koli içi adet" })).toHaveValue("12");
  });

  it("lotun koli GTIN'i yoksa koli içi adet yine lotun miktarıyla gelir; farklı adet uyarı vermez", async () => {
    const dialog = await openLabel({ ...finished(""), case_units: "12.000000" }, "koli");
    const units = within(dialog).getByRole("textbox", { name: "Koli içi adet" });
    expect(units).toHaveValue("12");
    await userEvent.clear(units);
    await userEvent.type(units, "24");
    expect(within(dialog).queryByTestId("units-warning")).not.toBeInTheDocument();
  });

  it.each([
    ["adet birimli olmayan lotta (null)", null],
    ["tam sayı olmayan miktarda", "12.500000"],
  ])("koli içi adet %s boş gelir", async (_name, caseUnits) => {
    const dialog = await openLabel(
      { ...finished("18690000000019"), case_units: caseUnits },
      "koli",
    );
    expect(within(dialog).getByRole("textbox", { name: "Koli içi adet" })).toHaveValue("");
    expect(within(dialog).queryByTestId("units-warning")).not.toBeInTheDocument();
  });

  it("palet formunda koli içi adet lotun koli içi miktarıyla gelir ve gönderilir; çelişen adet sarı uyarı verir", async () => {
    vi.mocked(labelsApi.getLabelSettings).mockResolvedValue(settings);
    vi.mocked(labelsApi.createPallet).mockResolvedValue(pallet);
    vi.mocked(inventoryApi.getLot).mockResolvedValue({
      ...finished("18690000000019"),
      case_units: "12.000000",
    });
    renderApp("/depo/lotlar/7");

    const units = await screen.findByRole("textbox", { name: "Koli içi adet" });
    expect(units).toHaveValue("12");
    expect(screen.queryByTestId("units-warning")).not.toBeInTheDocument();
    await userEvent.type(screen.getByRole("textbox", { name: "Koli sayısı" }), "40");
    await userEvent.click(screen.getByRole("button", { name: "SSCC al" }));
    await waitFor(() =>
      expect(labelsApi.createPallet).toHaveBeenCalledWith({
        lot: 7,
        case_count: 40,
        units_per_case: 12,
      }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Vazgeç" })); // palet etiketi penceresi

    await userEvent.clear(units);
    await userEvent.type(units, "24");
    const warning = screen.getByTestId("units-warning");
    expect(warning).toHaveTextContent(unitsWarning);
    expect(alertStyle(warning)).toContain("--mantine-color-yellow-light"); // sarı
  });

  it.each([
    ["koli", "8690000000012", "18690000000019"],
    ["koli", "8690000000012", ""],
    ["koli", "", "18690000000019"], // yalnız koli GTIN'i
    ["palet", "8690000000012", "18690000000019"],
    ["palet", "8690000000012", ""],
    ["palet", "", "18690000000019"],
  ] as const)(
    "GS1 barkodu basılamayan lotta (gs1_label false) %s etiketi GS1 ipucu yerine sarı uyarı verir (ürün GTIN'i %j, koli GTIN'i %j)",
    async (kind, gtin, caseGtin) => {
      const dialog = await openLabel(finished(caseGtin, false, gtin), kind);
      const warning = within(dialog).getByTestId("label-warning");
      expect(warning).toHaveTextContent(noGs1[kind]);
      expect(alertStyle(warning)).toContain("--mantine-color-yellow-light"); // sarı
      // GS1 / koli GTIN'i ipuçlarının hiçbiri çıkmaz (hepsi "GTIN'i" der, uyarı demez).
      expect(within(dialog).queryByText(/GTIN'i/)).not.toBeInTheDocument();
    },
  );

  it.each([
    ["koli", "Koli etiketine koli GTIN'i basılır."],
    ["palet", "Palet etiketine koli GTIN'i ve koli sayısı basılır."],
  ] as const)(
    "GS1 barkodu basılan lotta (gs1_label true) %s etiketinin ipucu değişmez",
    async (kind, text) => {
      const dialog = await openLabel(finished("18690000000019", true), kind);
      expect(within(dialog).getByText(text)).toBeInTheDocument();
      expect(within(dialog).queryByTestId("label-warning")).not.toBeInTheDocument();
    },
  );

  it("GTIN'i olmayan mamul lotunda gs1_label false olsa da firma içi barkod ipucu kalır", async () => {
    const dialog = await openLabel(
      lot({ material_type: "FINISHED", status: "RELEASED", gs1_label: false }),
      "koli",
    );
    expect(
      within(dialog).getByText("Malzemenin GTIN'i yok: firma içi barkod basılır."),
    ).toBeInTheDocument();
    expect(within(dialog).queryByTestId("label-warning")).not.toBeInTheDocument();
  });
});

/** Mantine uyarısının rengi kök öğenin stilindeki değişkenlerde (--alert-bg, --alert-color). */
function alertStyle(element: HTMLElement): string {
  return element.closest(".mantine-Alert-root")?.getAttribute("style") ?? "";
}

describe("mal kabul", () => {
  it("kaydedilmiş mal kabul salt okunur; oluşan lotlara bağlantı verir", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("depo"));
    const doc: GoodsReceiptDetail = {
      id: 4,
      number: "MK-2026-00001",
      status: "POSTED",
      status_display: "Kaydedildi",
      cancel_reason: "",
      cancelled_at: null,
      extra_costs: null,
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
          unit_price: null,
          created_lot: 7,
          created_lot_no: "H-261015-001",
          created_lot_status: "QUARANTINE",
        },
      ],
    };
    vi.mocked(inventoryApi.getGoodsReceipt).mockResolvedValue(doc);
    renderApp("/depo/mal-kabul/4");

    expect(await screen.findByRole("link", { name: "H-261015-001" })).toHaveAttribute(
      "href",
      "/depo/lotlar/7",
    );
    expect(screen.queryByRole("button", { name: "Taslağı kaydet" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Lot etiketleri/ }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("link", { name: "Aç" }).getAttribute("href")).toContain(
      "/inventory/goods-receipts/",
    );
  });

  it("malzeme ve depo lokasyonu seçiminde eski kodla da aranır", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("depo"));
    vi.mocked(mdApi.listRecords).mockImplementation(async (endpoint) => {
      if (endpoint === "locations") {
        return page([
          ...locations,
          {
            id: 6,
            code: "LOC-0000006",
            name: "B rafı",
            location_type: "STORAGE",
            is_active: true,
            former_codes: ["RAF-B"],
          },
        ]);
      }
      if (endpoint === "materials") {
        return page([
          {
            id: 50,
            code: "MLZ-0000001",
            name: "LABSA",
            former_codes: ["HM-LAS"],
            base_unit: 1,
            requires_incoming_qc: true,
            is_active: true,
          },
        ]);
      }
      return page([]);
    });
    renderApp("/depo/mal-kabul/yeni");

    await user.type(await screen.findByRole("textbox", { name: /Depo lokasyonu/ }), "raf-b");
    expect(
      await screen.findByRole("option", { name: "LOC-0000006 - B rafı (eski: RAF-B)" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "HM-01 - Hammadde rafı" })).not.toBeInTheDocument();
    await user.keyboard("{Escape}");

    // Satır açılışta bir kez yeniden kurulur; öğe her seferinde yeniden aranır.
    const line = screen.getByTestId("receipt-line");
    await user.type(within(line).getByRole("textbox", { name: /Malzeme/ }), "HM-LAS");
    expect(
      await screen.findByRole("option", { name: "MLZ-0000001 - LABSA (eski: HM-LAS)" }),
    ).toBeInTheDocument();
  });

  it("yeni mal kabul taslağı başlık ve satırlarla gönderilir", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("depo"));
    vi.mocked(inventoryApi.saveGoodsReceipt).mockRejectedValue(new Error("Tedarikçi zorunlu."));
    renderApp("/depo/mal-kabul/yeni");

    await user.click(await screen.findByRole("button", { name: "Taslağı kaydet" }));
    await waitFor(() =>
      expect(inventoryApi.saveGoodsReceipt).toHaveBeenCalledWith(
        null,
        expect.objectContaining({ supplier: null, lines: [] }),
      ),
    );
  });
});

describe("kayıt bağlantıları", () => {
  it("görevlerdeki depo kayıtları detay sayfasına gider", () => {
    expect(recordPath({ model: "inventory.lot", id: 7, repr: "" })).toBe("/depo/lotlar/7");
    expect(recordPath({ model: "inventory.goodsreceipt", id: 4, repr: "" })).toBe(
      "/depo/mal-kabul/4",
    );
    expect(recordPath({ model: "inventory.stockadjustment", id: 2, repr: "" })).toBe(
      "/depo/sayim/2",
    );
  });
});
