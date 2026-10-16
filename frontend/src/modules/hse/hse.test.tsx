import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as attachmentsApi from "../../api/attachments";
import * as authApi from "../../api/auth";
import * as hseApi from "../../api/hse";
import type { Incident, MaterialHazard, StorageUtilisation } from "../../api/hse";
import * as mdApi from "../../api/masterdata";
import type { Material } from "../../api/masterdata";
import type { Role } from "../../api/types";
import * as workflowApi from "../../api/workflow";
import { page, userWith } from "../../test/fixtures";
import { renderApp } from "../../test/render";
import { recordPath } from "../../workflow/recordLinks";

vi.mock("../../api/auth");
vi.mock("../../api/hse", async (importOriginal) => ({
  ...(await importOriginal<typeof hseApi>()),
  listIncidents: vi.fn(),
  getIncident: vi.fn(),
  reportIncident: vi.fn(),
  startInvestigation: vi.fn(),
  saveInvestigation: vi.fn(),
  closeIncident: vi.fn(),
  cancelIncident: vi.fn(),
  getSdsGaps: vi.fn(),
  listSds: vi.fn(),
  listMaterialHazards: vi.fn(),
  getMaterialHazard: vi.fn(),
  saveMaterialHazard: vi.fn(),
  listStatements: vi.fn(),
  getStorageUtilisation: vi.fn(),
  listStorageLimits: vi.fn(),
  listWasteRecords: vi.fn(),
  listContractors: vi.fn(),
  getHseSummary: vi.fn(),
  getHseSettings: vi.fn(),
}));
vi.mock("../../api/masterdata", async (importOriginal) => ({
  ...(await importOriginal<typeof mdApi>()),
  listRecords: vi.fn(),
}));
vi.mock("../../api/attachments", async (importOriginal) => ({
  ...(await importOriginal<typeof attachmentsApi>()),
  listAttachments: vi.fn(),
}));
vi.mock("../../api/workflow");

function incident(overrides: Partial<Incident> = {}): Incident {
  return {
    id: 9,
    number: "OL-2026-00001",
    status: "OPEN",
    status_display: "Açık",
    incident_type: "NEAR_MISS",
    incident_type_display: "Ramak kala",
    occurred_at: "2026-10-16T09:30:00+03:00",
    place: "Dolum hattı 2",
    location: null,
    location_code: null,
    equipment: null,
    equipment_code: null,
    description: "Islak zeminde kayma",
    injury: false,
    injured_person: "",
    severity: "LOW",
    severity_display: "Düşük",
    root_cause: "",
    corrective_action: "",
    action_owner: "",
    action_due: null,
    closed_note: "",
    cancel_reason: "",
    created_at: "2026-10-16T09:35:00+03:00",
    created_by_name: "Ali Dolum",
    allowed_transitions: ["INVESTIGATING", "CANCELLED"],
    ...overrides,
  };
}

function hazard(overrides: Partial<MaterialHazard> = {}): MaterialHazard {
  return {
    id: 1,
    material: 5,
    material_code: "HM-NAOH",
    material_name: "Kostik",
    is_hazardous: true,
    pictograms: ["GHS05"],
    pictogram_labels: ["Aşındırıcı"],
    signal_word: "DANGER",
    signal_word_display: "Tehlike",
    statements: [11],
    statement_rows: [
      { id: 11, code: "H314", kind: "H", text: "Ciddi cilt yanıklarına neden olur" },
    ],
    note: "",
    ...overrides,
  };
}

function usage(overrides: Partial<StorageUtilisation> = {}): StorageUtilisation {
  return {
    limit_id: 1,
    location_id: 2,
    location_code: "DP-A",
    location_name: "Hammadde deposu",
    hazard_class: "GHS02",
    hazard_class_display: "Yanıcı",
    limit_kg: "1000.0000",
    quantity_kg: "400.0000",
    pct: "40.00",
    exceeded: false,
    ...overrides,
  };
}

const naoh = {
  id: 5,
  code: "HM-NAOH",
  name: "Kostik",
  material_type: "RAW",
  material_type_display: "Hammadde",
  base_unit_code: "KG",
  is_hazardous: true,
  is_active: true,
} as unknown as Material;

function tabNames() {
  return screen.getAllByRole("tab").map((tab) => tab.textContent);
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(authApi.fetchCsrf).mockResolvedValue();
  vi.mocked(workflowApi.fetchTasks).mockResolvedValue(page([]));
  vi.mocked(workflowApi.fetchNotifications).mockResolvedValue(page([]));
  vi.mocked(workflowApi.fetchUnreadCount).mockResolvedValue(0);
  vi.mocked(workflowApi.fetchComments).mockResolvedValue([]);
  vi.mocked(workflowApi.fetchRecordHistory).mockResolvedValue([]);
  vi.mocked(attachmentsApi.listAttachments).mockResolvedValue([]);
  vi.mocked(mdApi.listRecords).mockImplementation(async (endpoint) =>
    endpoint === "materials" ? page([naoh]) : page([]),
  );
  vi.mocked(hseApi.listIncidents).mockResolvedValue(page([incident()]));
  vi.mocked(hseApi.getIncident).mockResolvedValue(incident());
  vi.mocked(hseApi.getSdsGaps).mockResolvedValue([]);
  vi.mocked(hseApi.listSds).mockResolvedValue(page([]));
  vi.mocked(hseApi.listMaterialHazards).mockResolvedValue(page([hazard()]));
  vi.mocked(hseApi.getMaterialHazard).mockResolvedValue(hazard());
  vi.mocked(hseApi.listStatements).mockResolvedValue(page([]));
  vi.mocked(hseApi.getStorageUtilisation).mockResolvedValue([]);
  vi.mocked(hseApi.listStorageLimits).mockResolvedValue(page([]));
  vi.mocked(hseApi.listWasteRecords).mockResolvedValue(page([]));
  vi.mocked(hseApi.listContractors).mockResolvedValue(page([]));
});

describe("İSG sekmeleri", () => {
  it("sevkiyat yalnızca olay ve tehlike bilgisi sekmelerini görür; kendi olaylarını listeler", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("sevkiyat"));
    renderApp("/isg");
    await within(await screen.findByTestId("hse-incidents")).findByText("OL-2026-00001");
    expect(tabNames()).toEqual(["Olaylar", "Tehlike bilgileri", "H/P ifadeleri"]);
    expect(screen.getByText(/Yalnızca bildirdiğiniz olaylar/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Olay bildir" })).toBeInTheDocument();
  });

  it("depo GBF ve depolama limitlerini görür, atık ve ayarları görmez", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("depo"));
    renderApp("/isg");
    await screen.findByTestId("hse-incidents");
    expect(tabNames()).toEqual([
      "Olaylar",
      "GBF arşivi",
      "Tehlike bilgileri",
      "H/P ifadeleri",
      "Depolama limitleri",
    ]);
  });

  it("yönetim tüm sekmeleri görür", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("yonetim"));
    vi.mocked(hseApi.getHseSettings).mockResolvedValue({ sds_max_age_months: 36 });
    renderApp("/isg/ayarlar");
    expect(await screen.findByLabelText(/GBF en çok yaşı/)).toHaveValue("36");
    expect(tabNames()).toEqual([
      "Olaylar",
      "GBF arşivi",
      "Tehlike bilgileri",
      "H/P ifadeleri",
      "Depolama limitleri",
      "Atık",
      "Özet",
      "Ayarlar",
    ]);
  });

  it("yetkisiz sekme adresi ilk sekmeye döner", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("uretim"));
    const { router } = renderApp("/isg/atik");
    await screen.findByTestId("hse-incidents");
    expect(router.state.location.pathname).toBe("/isg");
    expect(hseApi.listWasteRecords).not.toHaveBeenCalled();
  });
});

describe("olay bildirimi", () => {
  it("her rol olayı bildirir ve kayda gider", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("dolum"));
    vi.mocked(hseApi.reportIncident).mockResolvedValue(incident({ injury: true }));
    const { router } = renderApp("/isg");
    await userEvent.click(await screen.findByRole("button", { name: "Olay bildir" }));
    const dialog = await screen.findByRole("dialog");
    const submit = within(dialog).getByRole("button", { name: "Bildir" });
    expect(submit).toBeDisabled();

    await userEvent.click(within(dialog).getByRole("textbox", { name: /Olay türü/ }));
    await userEvent.click(await screen.findByRole("option", { name: "Ramak kala" }));
    await userEvent.type(within(dialog).getByLabelText(/^Yer/), "Dolum hattı 2");
    await userEvent.type(within(dialog).getByLabelText(/Ne oldu/), "Islak zeminde kayma");
    await userEvent.click(within(dialog).getByLabelText("Yaralanan var"));
    await userEvent.type(within(dialog).getByLabelText("Yaralanan kişi"), "Veli");
    await userEvent.click(within(dialog).getByText("Orta"));
    await userEvent.click(submit);

    await waitFor(() =>
      expect(hseApi.reportIncident).toHaveBeenCalledWith({
        incident_type: "NEAR_MISS",
        occurred_at: expect.stringMatching(/^\d{4}-\d{2}-\d{2}T/),
        place: "Dolum hattı 2",
        location: null,
        equipment: null,
        description: "Islak zeminde kayma",
        injury: true,
        injured_person: "Veli",
        severity: "MEDIUM",
      }),
    );
    await waitFor(() => expect(router.state.location.pathname).toBe("/isg/olaylar/9"));
  });
});

describe("olay detayı", () => {
  it("bildiren rol inceleme düğmelerini görmez", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("dolum"));
    renderApp("/isg/olaylar/9");
    expect(await screen.findByText("Olay OL-2026-00001")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "İncelemeye al" })).toBeNull();
    expect(screen.queryByRole("button", { name: "İptal et" })).toBeNull();
    expect(screen.getByText(/İnceleme bilgisi henüz girilmedi/)).toBeInTheDocument();
  });

  it("yönetim incelemeye alır, kök neden ve faaliyetle kapatır", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("yonetim"));
    const investigating = incident({
      status: "INVESTIGATING",
      allowed_transitions: ["CLOSED", "CANCELLED"],
    });
    vi.mocked(hseApi.getIncident)
      .mockResolvedValueOnce(incident())
      .mockResolvedValue(investigating);
    vi.mocked(hseApi.startInvestigation).mockResolvedValue(investigating);
    vi.mocked(hseApi.closeIncident).mockResolvedValue(
      incident({ status: "CLOSED", allowed_transitions: [] }),
    );
    renderApp("/isg/olaylar/9");
    await userEvent.click(await screen.findByRole("button", { name: "İncelemeye al" }));
    await waitFor(() =>
      expect(hseApi.startInvestigation).toHaveBeenCalledWith(9, expect.anything()),
    );

    await userEvent.click(await screen.findByRole("button", { name: "Kapat" }));
    const dialog = await screen.findByRole("dialog");
    const submit = within(dialog).getByRole("button", { name: "Kapat" });
    expect(submit).toBeDisabled();
    await userEvent.type(within(dialog).getByLabelText("Kök neden"), "Sızıntı");
    await userEvent.type(within(dialog).getByLabelText("Düzeltici faaliyet"), "Conta değişti");
    await userEvent.click(submit);
    await waitFor(() =>
      expect(hseApi.closeIncident).toHaveBeenCalledWith(9, {
        severity: "LOW",
        root_cause: "Sızıntı",
        corrective_action: "Conta değişti",
        action_owner: "",
        action_due: null,
        closed_note: "",
      }),
    );
  });

  it("olay kaydı bağlantısı detay sayfasına gider", () => {
    expect(recordPath({ model: "hse.incident", id: 4, repr: "OL-2026-00004" })).toBe(
      "/isg/olaylar/4",
    );
    expect(recordPath({ model: "hse.wasterecord", id: 2, repr: "AT-2026-00002" })).toBe(
      "/isg/atik",
    );
  });
});

describe("GBF ve depolama", () => {
  it("eksik GBF raporu durumlarıyla ve Excel bağlantısıyla görünür", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("laboratuvar"));
    vi.mocked(hseApi.getSdsGaps).mockResolvedValue([
      {
        material_id: 5,
        material_code: "HM-NAOH",
        material_name: "Kostik",
        material_type: "RAW",
        material_type_display: "Hammadde",
        is_hazardous: true,
        status: "MISSING",
        status_display: "GBF yok",
        sds_id: null,
        revision_no: "",
        revision_date: null,
        valid_until: null,
        has_file: false,
      },
      {
        material_id: 6,
        material_code: "HM-LAS",
        material_name: "LAS",
        material_type: "RAW",
        material_type_display: "Hammadde",
        is_hazardous: false,
        status: "EXPIRED",
        status_display: "Geçerliliği geçti",
        sds_id: 3,
        revision_no: "R2",
        revision_date: "2021-01-10",
        valid_until: "2026-01-10",
        has_file: true,
      },
    ]);
    renderApp("/isg/gbf");
    const table = await screen.findByTestId("sds-gaps");
    expect(await within(table).findByText("HM-NAOH - Kostik")).toBeInTheDocument();
    expect(within(table).getByText("GBF yok").closest("[data-status]")).toHaveAttribute(
      "data-status",
      "MISSING",
    );
    expect(within(table).getByText("Geçerliliği geçti")).toBeInTheDocument();
    expect(within(table).getByText("10.01.2026")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Excel'e aktar/ })).toHaveAttribute(
      "href",
      "/api/v1/hse/sds-gaps/export/",
    );
    // GBF'yi yalnızca yönetim girer.
    expect(screen.queryByRole("button", { name: "Yeni GBF" })).toBeNull();
    expect(hseApi.listSds).toHaveBeenCalledWith(expect.objectContaining({ current: true }));
  });

  it("aşılan depolama limiti kırmızı çubukla gösterilir", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("depo"));
    vi.mocked(hseApi.getStorageUtilisation).mockResolvedValue([
      usage(),
      usage({
        limit_id: 2,
        hazard_class: "GHS05",
        hazard_class_display: "Aşındırıcı",
        limit_kg: "500.0000",
        quantity_kg: "650.0000",
        pct: "130.00",
        exceeded: true,
      }),
    ]);
    renderApp("/isg/depolama");
    const ok = await screen.findByTestId("utilisation-1");
    const over = screen.getByTestId("utilisation-2");
    expect(ok).toHaveAttribute("data-exceeded", "false");
    expect(within(ok).queryByText("Limit aşıldı")).toBeNull();
    expect(over).toHaveAttribute("data-exceeded", "true");
    expect(within(over).getByText("Limit aşıldı")).toBeInTheDocument();
    expect(within(over).getByText("650 / 500 kg (%130)")).toBeInTheDocument();
    expect(over.querySelector("[data-color]")).toHaveAttribute("data-color", "red");
    expect(ok.querySelector("[data-color]")).toHaveAttribute("data-color", "teal");
    // Limitleri yalnızca yönetim yazar.
    expect(screen.queryByRole("button", { name: "Yeni limit" })).toBeNull();
  });
});

describe("malzeme tehlike bilgisi", () => {
  async function openFromMaterials(role: Role) {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith(role));
    renderApp("/ana-veriler/malzemeler");
    await userEvent.click(await screen.findByRole("button", { name: "Tehlike bilgisi: HM-NAOH" }));
    return screen.findByRole("dialog");
  }

  it("planlama malzeme kartında tehlike bilgisini görür ama düzenleyemez", async () => {
    const dialog = await openFromMaterials("planlama");
    const summary = await within(dialog).findByTestId("hazard-summary");
    expect(within(summary).getByText("GHS05")).toBeInTheDocument();
    expect(within(summary).getByText("Tehlike")).toBeInTheDocument();
    expect(within(summary).getByText("H314")).toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: "Düzenle" })).toBeNull();
    expect(hseApi.getMaterialHazard).toHaveBeenCalledWith(5);
  });

  it("yönetim piktogram ekleyip kaydeder", async () => {
    vi.mocked(hseApi.saveMaterialHazard).mockResolvedValue(
      hazard({ pictograms: ["GHS05", "GHS07"] }),
    );
    const dialog = await openFromMaterials("yonetim");
    await userEvent.click(await within(dialog).findByRole("button", { name: "Düzenle" }));
    expect(within(dialog).getByLabelText("GHS05 Aşındırıcı")).toBeChecked();
    await userEvent.click(within(dialog).getByLabelText("GHS07 Zararlı / tahriş edici"));
    await userEvent.click(within(dialog).getByRole("button", { name: "Kaydet" }));
    await waitFor(() =>
      expect(hseApi.saveMaterialHazard).toHaveBeenCalledWith(5, {
        pictograms: ["GHS05", "GHS07"],
        signal_word: "DANGER",
        statements: [11],
        note: "",
      }),
    );
  });

  it("laboratuvar İSG tehlike bilgileri sekmesinden düzenleyebilir", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("laboratuvar"));
    renderApp("/isg/tehlike");
    const table = await screen.findByTestId("hse-hazards");
    await userEvent.click(await within(table).findByText("HM-NAOH - Kostik"));
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByRole("button", { name: "Düzenle" })).toBeInTheDocument();
  });
});
