import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as authApi from "../../api/auth";
import * as masterdataApi from "../../api/masterdata";
import * as reportingApi from "../../api/reporting";
import type { ManagementDashboard, ReportInfo, ReportJob, ReportPage } from "../../api/reporting";
import * as workflowApi from "../../api/workflow";
import { page, userWith } from "../../test/fixtures";
import { renderApp } from "../../test/render";
import { defaultParams, formatValue } from "./format";

vi.mock("../../api/auth");
vi.mock("../../api/reporting", async (importOriginal) => ({
  ...(await importOriginal<typeof reportingApi>()),
  listDashboards: vi.fn(),
  getDashboard: vi.fn(),
  listReports: vi.fn(),
  getReport: vi.fn(),
  exportReport: vi.fn(),
  listJobs: vi.fn(),
}));
vi.mock("../../api/masterdata", async (importOriginal) => ({
  ...(await importOriginal<typeof masterdataApi>()),
  listRecords: vi.fn(),
}));
vi.mock("../../api/workflow");

function management(extra: Partial<ManagementDashboard> = {}): ManagementDashboard {
  const period = { bulk: [{ unit: "KG", quantity: "1950.0000", batches: 2 }], units: 975, runs: 1 };
  return {
    date: "2026-10-16",
    production: { today: period, week: period },
    open_orders: {
      production: [{ status: "IN_PRODUCTION", label: "Üretimde", count: 2 }],
      filling: [],
      sales: [],
    },
    qc_pending: { sample_count: 3, lot_count: 2, avg_wait_hours: "4.50", max_wait_hours: "9.00" },
    scrap: { days: 7, good_units: "975", scrap_units: "25", rate: "2.50" },
    critical_stock: {
      count: 1,
      items: [
        { material_id: 1, material: "LAS — LAS %96", stock: "10", min_stock: "500", unit: "KG" },
      ],
    },
    expiring_lots: { days: 30, count: 0, expired_count: 0, items: [] },
    tasks: {
      overdue_total: 4,
      by_role: [{ role: "depo", label: "Depo", open: 7, overdue: 4, max_delay_hours: "12.00" }],
    },
    maintenance: {
      days: 7,
      open_work_orders: 2,
      due_plans: 1,
      overdue_plans: 1,
      open_downtimes: 0,
      downtime_minutes: 200,
    },
    hse: { days: 30, incidents: 1, injuries: 0, open_incidents: 1 },
    stock_value: null,
    ...extra,
  };
}

const STOCK: ReportInfo = {
  code: "stock-movements",
  title: "Stok hareketleri",
  description: "Hareket defteri",
  filters: ["date_from", "date_to", "movement_type"],
  default_days: 30,
  columns: [],
};

function reportPage(extra: Partial<ReportPage> = {}): ReportPage {
  return {
    code: "stock-movements",
    title: "Stok hareketleri",
    columns: [
      { key: "lot_no", label: "Lot no", kind: "text" },
      { key: "quantity", label: "Miktar", kind: "number" },
      { key: "created_at", label: "Zaman", kind: "datetime" },
    ],
    summary: [{ key: "row_count", label: "Hareket", value: 1, kind: "number" }],
    filters: {},
    count: 1,
    sync_limit: 5000,
    results: [
      { lot_no: "H-261016-001", quantity: "-1250.5000", created_at: "2026-10-16T09:00:00Z" },
    ],
    ...extra,
  };
}

function job(extra: Partial<ReportJob> = {}): ReportJob {
  return {
    id: 5,
    report_code: "stock-movements",
    title: "Stok hareketleri",
    file_format: "xlsx",
    file_format_display: "Excel",
    params: {},
    status: "DONE",
    status_display: "Hazır",
    file_name: "stock-movements.xlsx",
    row_count: 12000,
    error: "",
    created_at: "2026-10-16T09:00:00Z",
    started_at: null,
    finished_at: null,
    expires_at: "2026-10-23T09:00:00Z",
    can_download: true,
    ...extra,
  };
}

beforeEach(() => {
  vi.mocked(authApi.fetchCsrf).mockResolvedValue();
  vi.mocked(workflowApi.fetchTasks).mockResolvedValue(page([]));
  vi.mocked(workflowApi.fetchNotifications).mockResolvedValue(page([]));
  vi.mocked(workflowApi.fetchUnreadCount).mockResolvedValue(0);
  vi.mocked(masterdataApi.listRecords).mockResolvedValue(page([]));
  vi.mocked(reportingApi.listDashboards).mockResolvedValue([
    { code: "management", title: "Yönetim panosu" },
  ]);
  vi.mocked(reportingApi.getDashboard).mockResolvedValue(management());
  vi.mocked(reportingApi.listReports).mockResolvedValue([STOCK]);
  vi.mocked(reportingApi.getReport).mockResolvedValue(reportPage());
  vi.mocked(reportingApi.listJobs).mockResolvedValue(page([job()]));
});

describe("panolar", () => {
  it("yönetim panosu üretimi, QC bekleyeni, fireyi ve gecikmiş görevleri gösterir", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("planlama"));
    renderApp("/raporlar");
    expect((await screen.findAllByText("1.950 KG")).length).toBeGreaterThan(0);
    expect(screen.getByText("2 lot")).toBeInTheDocument();
    expect(screen.getByText("%2,50")).toBeInTheDocument();
    expect(screen.getByText("LAS — LAS %96")).toBeInTheDocument();
    expect(screen.getByText("2 açık iş emri")).toBeInTheDocument();
    expect(screen.getByText("İSG olayları (son 30 gün)")).toBeInTheDocument();
    // Stok değeri yalnızca yönetime döner; planlamada kutu yok.
    expect(screen.queryByText("Stok değeri")).not.toBeInTheDocument();
  });

  it("stok değeri geldiyse gösterilir", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("yonetim"));
    vi.mocked(reportingApi.getDashboard).mockResolvedValue(
      management({ stock_value: { total: "1086680.00", by_type: [], has_uncosted: true } }),
    );
    renderApp("/raporlar/panolar");
    expect(await screen.findByText("1.086.680,00 TL")).toBeInTheDocument();
  });

  it("rolüne pano açık değilse bilgi verir", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("dolum"));
    vi.mocked(reportingApi.listDashboards).mockResolvedValue([]);
    renderApp("/raporlar");
    expect(await screen.findByText("Rolünüze açık bir pano yok.")).toBeInTheDocument();
  });
});

describe("raporlar", () => {
  it("rapor sütunları Türkçe biçimle gösterilir, Excel indirilir", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("depo"));
    vi.mocked(reportingApi.exportReport).mockResolvedValue({ kind: "file", fileName: "a.xlsx" });
    renderApp("/raporlar/raporlar");
    expect(await screen.findByText("H-261016-001")).toBeInTheDocument();
    expect(screen.getByText("-1.250,5")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Excel" }));
    await waitFor(() =>
      expect(reportingApi.exportReport).toHaveBeenCalledWith(
        "stock-movements",
        "xlsx",
        expect.objectContaining({ date_from: expect.any(String) }),
      ),
    );
  });

  it("büyük rapor arka plana alınır", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("depo"));
    vi.mocked(reportingApi.getReport).mockResolvedValue(reportPage({ count: 12000 }));
    vi.mocked(reportingApi.exportReport).mockResolvedValue({ kind: "job", job: job() });
    renderApp("/raporlar/raporlar");
    expect(await screen.findByText(/arka planda hazırlanır/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "PDF" }));
    await waitFor(() =>
      expect(reportingApi.exportReport).toHaveBeenCalledWith(
        "stock-movements",
        "pdf",
        expect.any(Object),
      ),
    );
  });
});

describe("indirmeler", () => {
  it("hazır dosya indirme bağlantısıyla listelenir", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("depo"));
    renderApp("/raporlar/indirmeler");
    expect(await screen.findByRole("link", { name: "İndir" })).toHaveAttribute(
      "href",
      "/api/v1/reporting/jobs/5/download/",
    );
    expect(screen.getByText("Hazır")).toBeInTheDocument();
  });
});

describe("biçim", () => {
  it("değer türüne göre biçimler", () => {
    expect(formatValue("12.5000", "percent")).toBe("12,50");
    expect(formatValue(true, "boolean")).toBe("Evet");
    expect(formatValue(null, "number")).toBe("");
    expect(formatValue("2026-10-16", "date")).toBe("16.10.2026");
  });

  it("tarihli raporda varsayılan son 30 gün", () => {
    const params = defaultParams(STOCK);
    expect(params.date_from && params.date_to && params.date_from < params.date_to).toBe(true);
    expect(defaultParams({ ...STOCK, default_days: null })).toEqual({});
  });
});
