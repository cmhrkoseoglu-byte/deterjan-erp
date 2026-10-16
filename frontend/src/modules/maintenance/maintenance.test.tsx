import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as attachmentsApi from "../../api/attachments";
import * as authApi from "../../api/auth";
import * as maintenanceApi from "../../api/maintenance";
import type { WorkOrder } from "../../api/maintenance";
import * as mdApi from "../../api/masterdata";
import * as workflowApi from "../../api/workflow";
import { page, userWith } from "../../test/fixtures";
import { renderApp } from "../../test/render";
import { recordPath } from "../../workflow/recordLinks";
import { formatMinutes } from "./strings";

vi.mock("../../api/auth");
vi.mock("../../api/maintenance", async (importOriginal) => ({
  ...(await importOriginal<typeof maintenanceApi>()),
  listWorkOrders: vi.fn(),
  getWorkOrder: vi.fn(),
  createWorkOrder: vi.fn(),
  startWorkOrder: vi.fn(),
  completeWorkOrder: vi.fn(),
  cancelWorkOrder: vi.fn(),
  addWorkOrderPart: vi.fn(),
  reportBreakdown: vi.fn(),
  listDowntimes: vi.fn(),
  startDowntime: vi.fn(),
  endDowntime: vi.fn(),
  getDowntimeSummary: vi.fn(),
  listPlans: vi.fn(),
  getCalibrationStatus: vi.fn(),
  listChangeoverRules: vi.fn(),
  getMaintenanceSettings: vi.fn(),
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

function workOrder(overrides: Partial<WorkOrder> = {}): WorkOrder {
  return {
    id: 7,
    number: "BK-2026-00001",
    status: "OPEN",
    status_display: "Açık",
    equipment: 3,
    equipment_code: "TNK-01",
    equipment_name: "Karıştırma tankı 1",
    plan: 2,
    plan_title: "Aylık bakım",
    source: "PLAN",
    source_display: "Bakım planı",
    kind: "PERIODIC",
    kind_display: "Periyodik bakım",
    title: "Aylık bakım",
    description: "Karıştırıcı ve contalar",
    responsible_role: "uretim",
    responsible_role_display: "Üretim",
    due_date: "2026-10-20",
    checklist_rows: [
      { item: "Conta kontrolü", done: false, note: "" },
      { item: "Motor yağlama", done: false, note: "" },
    ],
    previous_product: null,
    previous_product_code: null,
    started_at: null,
    started_by_name: null,
    completed_at: null,
    completed_by_name: null,
    work_done: "",
    duration_minutes: null,
    calibration_result: "",
    calibration_result_display: "",
    certificate_no: "",
    cancel_reason: "",
    created_at: "2026-10-16T07:00:00+03:00",
    created_by_name: null,
    parts: [],
    downtime_minutes: null,
    ...overrides,
  };
}

const equipment = [
  { id: 3, code: "TNK-01", name: "Karıştırma tankı 1", equipment_type: "MIXING_TANK" },
  { id: 4, code: "TRZ-01", name: "Terazi 1", equipment_type: "SCALE" },
] as unknown as mdApi.Equipment[];

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
    endpoint === "equipment" ? page(equipment) : page([]),
  );
  vi.mocked(maintenanceApi.listWorkOrders).mockResolvedValue(page([workOrder()]));
  vi.mocked(maintenanceApi.getWorkOrder).mockResolvedValue(workOrder());
  vi.mocked(maintenanceApi.listDowntimes).mockResolvedValue(page([]));
  vi.mocked(maintenanceApi.getDowntimeSummary).mockResolvedValue([]);
  vi.mocked(maintenanceApi.listPlans).mockResolvedValue(page([]));
  vi.mocked(maintenanceApi.getCalibrationStatus).mockResolvedValue([]);
  vi.mocked(maintenanceApi.listChangeoverRules).mockResolvedValue(page([]));
});

describe("bakım", () => {
  it("üretim sekmeleri görür, ayarları görmez", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("uretim"));
    renderApp("/bakim");
    await within(await screen.findByTestId("maintenance-work-orders")).findByText("BK-2026-00001");
    for (const name of [
      "İş emirleri",
      "Duruşlar",
      "Bakım planları",
      "Kalibrasyon",
      "Temizliksiz geçişler",
    ]) {
      expect(screen.getByRole("tab", { name })).toBeInTheDocument();
    }
    expect(screen.queryByRole("tab", { name: "Ayarlar" })).toBeNull();
    expect(screen.getByRole("button", { name: "Yeni iş emri" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Arıza bildir" })).toBeInTheDocument();
    // Varsayılan filtre açık ve yapılan iş emirleri.
    expect(maintenanceApi.listWorkOrders).toHaveBeenCalledWith(expect.anything(), [
      "OPEN",
      "IN_PROGRESS",
    ]);
  });

  it("yönetim ayarlar sekmesini görür", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("yonetim"));
    vi.mocked(maintenanceApi.getMaintenanceSettings).mockResolvedValue({
      calibration_warning_days: 7,
      plan_lead_days: 7,
    });
    renderApp("/bakim/ayarlar");
    expect(await screen.findByLabelText(/Kalibrasyon uyarı süresi/)).toHaveValue("7");
    expect(screen.getByRole("tab", { name: "Ayarlar" })).toBeInTheDocument();
  });

  it("planlama yeni iş emri açamaz ve ayarları görmez", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("planlama"));
    renderApp("/bakim");
    await screen.findByTestId("maintenance-work-orders");
    expect(screen.queryByRole("button", { name: "Yeni iş emri" })).toBeNull();
    expect(screen.queryByRole("tab", { name: "Ayarlar" })).toBeNull();
  });

  it("depo bakım sayfasına giremez", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("depo"));
    renderApp("/bakim");
    expect(await screen.findByText(/yetkiniz yok|erişim/i)).toBeInTheDocument();
    expect(screen.queryByTestId("maintenance-work-orders")).toBeNull();
  });

  it("iş emri listeden açılır ve kontrol listesiyle tamamlanır", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("uretim"));
    vi.mocked(maintenanceApi.completeWorkOrder).mockResolvedValue(
      workOrder({ status: "COMPLETED" }),
    );
    renderApp("/bakim");
    const table = await screen.findByTestId("maintenance-work-orders");
    await userEvent.click(await within(table).findByText("BK-2026-00001"));

    expect(await screen.findByText("Bakım iş emri BK-2026-00001")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Tamamla" }));
    const dialog = await screen.findByRole("dialog");
    const submit = within(dialog).getByRole("button", { name: "Tamamla" });
    expect(submit).toBeDisabled();
    await userEvent.click(within(dialog).getByLabelText("Conta kontrolü"));
    await userEvent.click(within(dialog).getByLabelText("Motor yağlama"));
    await userEvent.type(within(dialog).getByLabelText("Not: Motor yağlama"), "Gres eklendi");
    await userEvent.type(within(dialog).getByLabelText(/Yapılan iş/), "Contalar değişti");
    await userEvent.type(within(dialog).getByLabelText(/Süre/), "45");
    await userEvent.click(submit);
    await waitFor(() =>
      expect(maintenanceApi.completeWorkOrder).toHaveBeenCalledWith(7, {
        work_done: "Contalar değişti",
        duration_minutes: 45,
        checklist: [
          { done: true, note: "" },
          { done: true, note: "Gres eklendi" },
        ],
        calibration_result: "",
        certificate_no: "",
      }),
    );
  });

  it("kalibrasyon iş emrinde sonuç seçilmeden tamamlanamaz", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("laboratuvar"));
    vi.mocked(maintenanceApi.getWorkOrder).mockResolvedValue(
      workOrder({ kind: "CALIBRATION", responsible_role: "laboratuvar", checklist_rows: [] }),
    );
    vi.mocked(maintenanceApi.completeWorkOrder).mockResolvedValue(
      workOrder({ status: "COMPLETED" }),
    );
    renderApp("/bakim/is-emirleri/7");
    await userEvent.click(await screen.findByRole("button", { name: "Tamamla" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText(/Yapılan iş/), "Ağırlıkla kontrol");
    const submit = within(dialog).getByRole("button", { name: "Tamamla" });
    expect(submit).toBeDisabled();
    await userEvent.click(within(dialog).getByRole("textbox", { name: /Kalibrasyon sonucu/ }));
    await userEvent.click(await screen.findByRole("option", { name: "Uygun değil" }));
    await userEvent.type(within(dialog).getByLabelText(/Sertifika no/), "K-12");
    await userEvent.click(submit);
    await waitFor(() =>
      expect(maintenanceApi.completeWorkOrder).toHaveBeenCalledWith(
        7,
        expect.objectContaining({ calibration_result: "FAILED", certificate_no: "K-12" }),
      ),
    );
  });

  it("sorumlu olmayan birim iş emrini yürütemez", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("dolum"));
    renderApp("/bakim/is-emirleri/7");
    expect(await screen.findByText(/yalnızca sorumlu birim/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Tamamla" })).toBeNull();
    expect(screen.queryByRole("button", { name: "İşe başla" })).toBeNull();
  });

  it("arıza bildirimi iş emri açar ve duruşu başlatır", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("uretim"));
    vi.mocked(maintenanceApi.reportBreakdown).mockResolvedValue(
      workOrder({ id: 8, number: "BK-2026-00002", kind: "REPAIR", source: "BREAKDOWN" }),
    );
    renderApp("/bakim");
    await userEvent.click(await screen.findByRole("button", { name: "Arıza bildir" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByLabelText("Ekipman durdu (duruş başlat)")).toBeChecked();
    await userEvent.click(within(dialog).getByRole("textbox", { name: /Ekipman/ }));
    await userEvent.click(
      await screen.findByRole("option", { name: "TNK-01 - Karıştırma tankı 1" }),
    );
    await userEvent.type(within(dialog).getByLabelText(/Arıza açıklaması/), "Motor ses yapıyor");
    await userEvent.click(within(dialog).getByRole("button", { name: "Bildir" }));
    await waitFor(() =>
      expect(maintenanceApi.reportBreakdown).toHaveBeenCalledWith({
        equipment: 3,
        description: "Motor ses yapıyor",
        stop_equipment: true,
      }),
    );
  });

  it("ana sayfada her rol arıza bildirebilir", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("sevkiyat"));
    renderApp("/");
    expect(await screen.findByRole("button", { name: "Arıza bildir" })).toBeInTheDocument();
  });

  it("kalibrasyon durumları renkli rozetle gösterilir", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("laboratuvar"));
    vi.mocked(maintenanceApi.getCalibrationStatus).mockResolvedValue([
      {
        equipment: 4,
        equipment_code: "TRZ-01",
        equipment_name: "Terazi 1",
        status: "OK",
        label: "Geçerli",
        next_due_date: "2026-12-01",
        days_left: 46,
        is_down: false,
      },
      {
        equipment: 5,
        equipment_code: "TRZ-02",
        equipment_name: "Terazi 2",
        status: "DUE_SOON",
        label: "Yaklaşıyor",
        next_due_date: "2026-10-20",
        days_left: 4,
        is_down: false,
      },
      {
        equipment: 6,
        equipment_code: "TRZ-03",
        equipment_name: "Terazi 3",
        status: "OVERDUE",
        label: "Süresi geçti",
        next_due_date: "2026-10-10",
        days_left: -6,
        is_down: true,
      },
      {
        equipment: 7,
        equipment_code: "TRZ-04",
        equipment_name: "Terazi 4",
        status: "NO_PLAN",
        label: "Kalibrasyon planı yok",
        next_due_date: null,
        days_left: null,
        is_down: false,
      },
    ]);
    renderApp("/bakim/kalibrasyon");
    const table = await screen.findByTestId("calibration-status");
    const colors = { Geçerli: "green", Yaklaşıyor: "yellow", "Süresi geçti": "red" } as const;
    for (const [label, color] of Object.entries(colors)) {
      const badge = within(table).getByText(label).closest(".mantine-Badge-root");
      expect(badge?.getAttribute("style") ?? "").toContain(`--mantine-color-${color}`);
    }
    expect(
      within(table).getByText("Kalibrasyon planı yok").closest("[data-status]"),
    ).toHaveAttribute("data-status", "NO_PLAN");
    expect(table).toHaveTextContent("6 gün geçti");
    expect(within(table).getByText("Duruşta")).toBeInTheDocument();
  });

  it("temizliksiz geçiş tanımlamayı yalnızca laboratuvar görür", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("uretim"));
    renderApp("/bakim/temizliksiz-gecisler");
    await screen.findByTestId("changeover-rules");
    expect(screen.getByText(/temizlik kaydı zorunludur/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Yeni geçiş" })).toBeNull();
  });

  it("laboratuvar temizliksiz geçiş ekleyebilir", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("laboratuvar"));
    renderApp("/bakim/temizliksiz-gecisler");
    await screen.findByTestId("changeover-rules");
    expect(screen.getByRole("button", { name: "Yeni geçiş" })).toBeInTheDocument();
  });

  it("açık duruş vurgulanır ve notla bitirilir; özet süreyi saat ve dakikayla yazar", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("planlama"));
    const open = {
      id: 11,
      equipment: 3,
      equipment_code: "TNK-01",
      equipment_name: "Karıştırma tankı 1",
      reason: "BREAKDOWN" as const,
      reason_display: "Arıza",
      started_at: "2026-10-16T08:00:00+03:00",
      ended_at: null,
      note: "",
      end_note: "",
      work_order: 7,
      work_order_number: "BK-2026-00001",
      created_by_name: null,
      ended_by_name: null,
      minutes: null,
    };
    vi.mocked(maintenanceApi.listDowntimes).mockResolvedValue(page([open]));
    vi.mocked(maintenanceApi.getDowntimeSummary).mockResolvedValue([
      {
        equipment_id: 3,
        equipment_code: "TNK-01",
        equipment_name: "Karıştırma tankı 1",
        reason: "BREAKDOWN",
        reason_display: "Arıza",
        count: 2,
        minutes: 200,
      },
    ]);
    vi.mocked(maintenanceApi.endDowntime).mockResolvedValue({ ...open, ended_at: "x" });
    renderApp("/bakim/duruslar");
    const cards = await screen.findByTestId("open-downtimes");
    expect(await screen.findByTestId("downtime-summary")).toHaveTextContent("3 sa 20 dk");
    await userEvent.click(within(cards).getByRole("button", { name: "Bitir" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText("Not"), "Rulman değişti");
    await userEvent.click(within(dialog).getByRole("button", { name: "Bitir" }));
    await waitFor(() =>
      expect(maintenanceApi.endDowntime).toHaveBeenCalledWith(11, { note: "Rulman değişti" }),
    );
  });

  it("dakika biçimi ve iş emri kayıt bağlantısı", () => {
    expect(formatMinutes(200)).toBe("3 sa 20 dk");
    expect(formatMinutes(45)).toBe("45 dk");
    expect(recordPath({ model: "maintenance.maintenanceworkorder", id: 7, repr: "" })).toBe(
      "/bakim/is-emirleri/7",
    );
  });
});
