import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as attachmentsApi from "../api/attachments";
import type { Attachment } from "../api/attachments";
import * as labelsApi from "../api/labels";
import * as scanApi from "../api/scan";
import type { ScanLot, ScanResult } from "../api/scan";
import { httpError } from "../test/fixtures";
import { renderWithProviders } from "../test/render";
import { AttachmentPanel } from "./attachments/AttachmentPanel";
import { LabelPrintModal } from "./labels/LabelPrintModal";
import { ScanInput } from "./scan/ScanInput";

vi.mock("../api/scan");
vi.mock("../api/attachments", async (importOriginal) => ({
  ...(await importOriginal<typeof attachmentsApi>()),
  listAttachments: vi.fn(),
  uploadAttachment: vi.fn(),
  removeAttachment: vi.fn(),
}));
vi.mock("../api/labels", async (importOriginal) => ({
  ...(await importOriginal<typeof labelsApi>()),
  listPrinters: vi.fn(),
  getLabelSettings: vi.fn(),
  printLabel: vi.fn(),
}));

function scanLot(overrides: Partial<ScanLot> = {}): ScanLot {
  return {
    id: 7,
    lot_no: "H-261015-001",
    material: 50,
    material_code: "LAS",
    material_name: "LAS %96",
    material_type: "RAW",
    unit: "KG",
    status: "RELEASED",
    status_display: "Serbest",
    expiry_date: null,
    is_expired: false,
    ...overrides,
  };
}

function scanResult(lots: ScanLot[]): ScanResult {
  return {
    kind: "lot",
    code: lots[0]?.lot_no ?? "",
    lots,
    material: null,
    location: null,
    pallet: null,
    gs1: {},
  };
}

function attachment(overrides: Partial<Attachment> = {}): Attachment {
  return {
    id: 1,
    content_type: "inventory.lot",
    object_id: 7,
    kind: "SUPPLIER_COA",
    kind_display: "Tedarikçi analiz sertifikası",
    original_name: "coa.pdf",
    size: 2048,
    mime_type: "application/pdf",
    note: "",
    is_active: true,
    uploaded_by_name: "Depo Kullanıcısı",
    created_at: "2026-10-15T09:00:00+03:00",
    removed_at: null,
    removed_by_name: null,
    removal_reason: "",
    download_url: "/api/v1/attachments/1/download/",
    can_remove: true,
    ...overrides,
  };
}

beforeEach(() => {
  vi.mocked(labelsApi.getLabelSettings).mockResolvedValue({
    company_name: "Inncos",
    gs1_company_prefix: "",
    sscc_extension_digit: 0,
    next_sscc_serial: 1,
    default_printer: 2,
    default_printer_code: null,
    sscc_enabled: false,
    updated_at: "2026-10-15T09:00:00+03:00",
  });
});

describe("ScanInput", () => {
  it("beklenen malzemenin lotunu kabul eder", async () => {
    vi.mocked(scanApi.scanCode).mockResolvedValue(scanResult([scanLot()]));
    const onLot = vi.fn();
    renderWithProviders(
      <ScanInput expect="lot" expectedMaterial={{ id: 50, code: "LAS" }} onLot={onLot} />,
    );
    await userEvent.type(screen.getByTestId("scan-input"), "LOT:H-261015-001{Enter}");
    await waitFor(() => expect(onLot).toHaveBeenCalledWith(scanLot(), expect.anything()));
    expect(scanApi.scanCode).toHaveBeenCalledWith("LOT:H-261015-001");
    expect(await screen.findByTestId("scan-ok")).toHaveTextContent("H-261015-001");
    expect(screen.getByTestId("scan-input")).toHaveValue("");
  });

  it("yanlış malzemenin lotunda kırmızı uyarı verir", async () => {
    vi.mocked(scanApi.scanCode).mockResolvedValue(
      scanResult([scanLot({ material: 51, material_code: "NACL" })]),
    );
    const onLot = vi.fn();
    renderWithProviders(
      <ScanInput expect="lot" expectedMaterial={{ id: 50, code: "LAS" }} onLot={onLot} />,
    );
    await userEvent.type(screen.getByTestId("scan-input"), "H-261015-002{Enter}");
    const alert = await screen.findByTestId("scan-error");
    expect(alert).toHaveTextContent("Yanlış malzeme! Beklenen LAS, okutulan NACL.");
    expect(alert).toHaveAttribute("data-variant", "filled");
    expect(onLot).not.toHaveBeenCalled();
  });

  it("bulunamayan kodda sunucunun mesajını gösterir", async () => {
    vi.mocked(scanApi.scanCode).mockRejectedValue(
      httpError(400, { code: "scan_not_found", detail: "Okutulan kod tanınmadı: XYZ" }),
    );
    renderWithProviders(<ScanInput expect="lot" />);
    await userEvent.type(screen.getByTestId("scan-input"), "XYZ{Enter}");
    expect(await screen.findByTestId("scan-error")).toHaveTextContent("tanınmadı");
  });

  it("lokasyon beklenirken lot okutulursa reddeder", async () => {
    vi.mocked(scanApi.scanCode).mockResolvedValue(scanResult([scanLot()]));
    const onLocation = vi.fn();
    renderWithProviders(<ScanInput expect="location" onLocation={onLocation} />);
    await userEvent.type(screen.getByTestId("scan-input"), "H-261015-001{Enter}");
    expect(await screen.findByTestId("scan-error")).toHaveTextContent("lokasyon değil");
    expect(onLocation).not.toHaveBeenCalled();
  });
});

describe("AttachmentPanel", () => {
  it("ekleri listeler ve seçilen dosyayı türüyle yükler", async () => {
    vi.mocked(attachmentsApi.listAttachments).mockResolvedValue([attachment()]);
    vi.mocked(attachmentsApi.uploadAttachment).mockResolvedValue(attachment({ id: 2 }));
    renderWithProviders(
      <AttachmentPanel contentType="inventory.lot" objectId={7} defaultKind="SUPPLIER_COA" />,
    );
    expect(await screen.findByRole("link", { name: /coa\.pdf/ })).toHaveAttribute(
      "href",
      "/api/v1/attachments/1/download/",
    );
    const file = new File(["%PDF-1.4"], "irsaliye.pdf", { type: "application/pdf" });
    await userEvent.upload(screen.getByTestId("attachment-file"), file);
    await waitFor(() =>
      expect(attachmentsApi.uploadAttachment).toHaveBeenCalledWith("inventory.lot", 7, file, {
        kind: "SUPPLIER_COA",
        note: "",
      }),
    );
  });

  it("kamera fotoğrafı Fotoğraf türüyle yüklenir", async () => {
    vi.mocked(attachmentsApi.listAttachments).mockResolvedValue([]);
    vi.mocked(attachmentsApi.uploadAttachment).mockResolvedValue(attachment({ kind: "PHOTO" }));
    renderWithProviders(<AttachmentPanel contentType="quality.sample" objectId={3} />);
    expect(await screen.findByText("Ek yok.")).toBeInTheDocument();
    const photo = new File(["jpeg"], "kamera.jpg", { type: "image/jpeg" });
    await userEvent.upload(screen.getByTestId("attachment-camera"), photo);
    await waitFor(() =>
      expect(attachmentsApi.uploadAttachment).toHaveBeenCalledWith(
        "quality.sample",
        3,
        photo,
        expect.objectContaining({ kind: "PHOTO" }),
      ),
    );
  });
});

describe("LabelPrintModal", () => {
  const options = [
    {
      value: "lot",
      label: "Lot etiketi",
      downloadPath: "/inventory/lots/7/label/",
      printPath: "/inventory/lots/7/print-label/",
      printKind: "lot" as const,
    },
  ];

  it("varsayılan yazıcıya gönderir", async () => {
    vi.mocked(labelsApi.listPrinters).mockResolvedValue([
      printer({ id: 1, code: "ZB-1" }),
      printer({ id: 2, code: "ZB-2" }),
    ]);
    vi.mocked(labelsApi.printLabel).mockResolvedValue({ printed: 1, printer: "ZB-2" });
    renderWithProviders(<LabelPrintModal opened onClose={vi.fn()} options={options} />);
    await waitFor(() =>
      expect(screen.getByRole("textbox", { name: "Yazıcı" })).toHaveValue("ZB-2 - Zebra"),
    );
    await userEvent.click(screen.getByRole("button", { name: "Gönder" }));
    await waitFor(() =>
      expect(labelsApi.printLabel).toHaveBeenCalledWith("/inventory/lots/7/print-label/", {
        printer: 2,
        copies: 1,
        kind: "lot",
      }),
    );
  });

  it("yazıcı yoksa PDF bağlantısı verir", async () => {
    vi.mocked(labelsApi.listPrinters).mockResolvedValue([]);
    renderWithProviders(<LabelPrintModal opened onClose={vi.fn()} options={options} />);
    expect(await screen.findByText(/Tanımlı yazıcı yok/)).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "Aç" });
    expect(link.getAttribute("href")).toContain("/inventory/lots/7/label/");
    expect(link.getAttribute("href")).toContain("output=pdf");
  });
});

function printer(overrides: Partial<labelsApi.Printer> = {}): labelsApi.Printer {
  return {
    id: 1,
    code: "ZB-1",
    name: "Zebra",
    printer_type: "ZPL",
    host: "192.168.1.50",
    port: 9100,
    dpi: 203,
    location: null,
    location_code: null,
    note: "",
    is_active: true,
    ...overrides,
  } as labelsApi.Printer;
}
